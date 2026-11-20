#!/usr/bin/env python3
"""
QA Report Studio — desktop launcher
===================================
The entry point PyInstaller freezes into "QA Report Studio.exe". It is the only
file that knows the app is packaged: app.py stays an ordinary Streamlit script
that still runs with `streamlit run app.py`, on a laptop or on Streamlit Cloud.

What it does, in the order the user notices it:

1.  Within a second of the double-click, a window opens on a "Starting up…"
    page. The window is Microsoft Edge in app mode — no tabs, no address bar,
    its own taskbar button and icon — running on a private profile, so it
    looks and behaves like any installed program. Edge is part of every
    Windows 10 and 11 installation; Chrome, Brave or Vivaldi are used if Edge
    is missing, and the default browser as the very last resort.
2.  Meanwhile the report library is put in place in the user's own folder
    (%LOCALAPPDATA%\\QAReportStudio — see qars/desktop.py) and the Streamlit
    server starts on 127.0.0.1. Loopback only: Windows Firewall never asks,
    and nothing on the network can reach it.
3.  When the server answers, the start-up page turns into the app.
4.  Closing the window stops the server and the program. So does the
    "Shut down app" button in the app's menu.

No administrator rights anywhere: the program runs from the user's AppData,
writes only to the user's AppData, and starts nothing that needs elevation.

--------------------------------------------------------------------------
WHY A START-UP PAGE THAT REWRITES ITSELF
--------------------------------------------------------------------------
A file:// page cannot fetch() http://127.0.0.1 (the browser blocks it), so the
page never asks the server anything. It reloads itself every 1.2 seconds, and
when the server is ready the launcher rewrites the file with a redirect; the
next reload follows it. `import streamlit` — by far the slowest thing here —
happens after the window is on screen, so it overlaps with what the user sees
instead of delaying it.

--------------------------------------------------------------------------
WHY THE WINDOW HAS A PROFILE OF ITS OWN
--------------------------------------------------------------------------
Streamlit's frontend is ~300 JavaScript files whose names carry a content
hash, listed in index.html. A browser that cached index.html from one build
asks the next build for files that no longer exist, and every widget dies with
"Failed to fetch dynamically imported module". The private profile is keyed to
the exact frontend build, so an update always starts with a clean cache. It
also keeps the user's own Edge — their tabs, sign-in and extensions — entirely
out of it.

Environment overrides, for support only:
    QARS_WINDOW=browser   open in the default browser instead of a window
    QARS_ZOOM=1.25        start at 125% (0.8 to fit more); Ctrl +/- also works
    QARS_HOME=<folder>    keep the library and logs somewhere else
    QARS_BROWSER=<exe>    use this Chromium-family browser for the window
    QARS_BROWSER_ARGS=…   extra switches for it (automated tests use this)
"""
from __future__ import annotations

import base64
import hashlib
import json
import multiprocessing
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

if not getattr(sys, "frozen", False):
    # Run from a checkout: app_info sits beside this file, qars one level up.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app_info                                               # noqa: E402

APP_TITLE = app_info.APP_NAME
BIND_HOST = "127.0.0.1"
STARTUP_TIMEOUT_SECONDS = 180

# A window process that exits sooner than this probably handed its window to
# a browser process that was already running (a managed Edge can do that).
# Then closing "our" process means nothing, so the launcher watches for the
# app's browser sessions instead.
HANDOFF_GRACE_SECONDS = 4

try:
    ZOOM = float(os.environ.get("QARS_ZOOM", "1.0"))
except ValueError:
    ZOOM = 1.0
ZOOM = min(3.0, max(0.25, ZOOM))
WINDOW_MODE = os.environ.get("QARS_WINDOW", "window").strip().lower()

_instance_guard = []      # holds the mutex handle / lock socket for the process lifetime
_no_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ---------------------------------------------------------------- locations
def bundle_dir() -> Path:
    """Where app.py, qars/library, desktop/ and .streamlit/ are at run time."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def redirect_streams(log_path: Path) -> None:
    """
    Send stdout and stderr to the log. A windowed build has no console, so
    sys.stdout is None — and Streamlit writes to it, so without this the app
    would die on start-up with no visible reason. The previous run's log is
    kept as launcher.prev.log.
    """
    try:
        if log_path.name == "launcher.log" and log_path.exists():
            os.replace(log_path, log_path.with_name("launcher.prev.log"))
    except OSError:
        pass
    try:
        handle = open(log_path, "w", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        return
    frozen = getattr(sys, "frozen", False)

    def replace(stream) -> bool:
        if stream is None or not hasattr(stream, "write"):
            return True
        if frozen:
            # The program has no console. A stream it was handed anyway — the
            # null device, when setup starts it — would swallow the log; only a
            # real terminal (a console debug build) is kept.
            try:
                return not stream.isatty()
            except Exception:                                 # noqa: BLE001
                return True
        return False

    if replace(sys.stdout):
        sys.stdout = handle
    if replace(sys.stderr):
        sys.stderr = handle
    if sys.stdin is None:
        try:
            sys.stdin = open(os.devnull, "r")
        except OSError:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                     # noqa: BLE001
            pass


def log(message: str) -> None:
    try:
        print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)
    except Exception:                                         # noqa: BLE001
        pass


# ------------------------------------------------------------ single instance
def claim_single_instance() -> bool:
    """
    True if this is the only copy running for this Windows user.

    A named mutex on Windows, a bound socket elsewhere. Either way the
    operating system releases it the moment the process ends, however it
    ends, so a crash can never block the next start.
    """
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                              wintypes.LPCWSTR]
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            ctypes.set_last_error(0)
            handle = kernel32.CreateMutexW(None, False, f"Local\\{app_info.APP_ID}-running")
            if handle:
                if ctypes.get_last_error() == 183:            # ERROR_ALREADY_EXISTS
                    kernel32.CloseHandle(handle)
                    return False
                _instance_guard.append(handle)
                return True
        except Exception as exc:                              # noqa: BLE001
            log(f"mutex unavailable ({exc}); using the lock port")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((BIND_HOST, app_info.LOCK_PORT))
        s.listen(1)
    except OSError:
        s.close()
        return False
    _instance_guard.append(s)
    return True


def focus_existing_window() -> bool:
    """Bring an open app window to the front, as clicking any program's
    shortcut again would. False when there is none to bring."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
        for name in ("IsWindowVisible", "GetWindowTextLengthW", "IsIconic",
                     "SetForegroundWindow"):
            getattr(user32, name).argtypes = [wintypes.HWND]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        found = []

        @enum_proc
        def visit(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0 or length > 200:
                return True
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            if title.value != APP_TITLE:
                return True
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            if not cls.value.startswith("Chrome_WidgetWin"):
                return True
            found.append(hwnd)
            return False

        user32.EnumWindows(visit, 0)
        if not found:
            return False
        if user32.IsIconic(found[0]):
            user32.ShowWindow(found[0], 9)                     # SW_RESTORE
        user32.SetForegroundWindow(found[0])
        return True
    except Exception as exc:                                  # noqa: BLE001
        log(f"could not bring the open window forward ({exc})")
        return False


# ------------------------------------------------------------------ server
def pick_port(preferred: int) -> int:
    """
    The usual port when it is free, any free port otherwise. Staying on one
    port matters: the window remembers its zoom per address, so a new port
    every start would forget it.
    """
    for candidate in (preferred, 0):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name != "nt":
            # Ignore connections from the last run still in TIME_WAIT, as the
            # server itself does. (On Windows the same option would let two
            # programs share a port, so it is not set there.)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((BIND_HOST, candidate))
            port = s.getsockname()[1]
            s.close()
            return port
        except OSError:
            s.close()
    return preferred


def server_answers(url: str, timeout: float = 1.5) -> bool:
    """
    True once Streamlit is serving. Asked without any proxy: a company proxy
    configured in Windows must never see, or slow down, a call to 127.0.0.1.
    Any HTTP answer except "unavailable" counts, so a renamed health check in
    a later Streamlit cannot leave the window waiting forever.
    """
    try:
        with _no_proxy.open(f"{url}/_stcore/health", timeout=timeout) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        return exc.code != 503
    except Exception:                                         # noqa: BLE001
        return False


def wait_for_server(url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if server_answers(url):
            return True
        time.sleep(0.25)
    return False


def known_config_options() -> set:
    """Option names this Streamlit accepts, so an option a future version drops
    costs that one setting instead of the whole start-up."""
    try:
        from streamlit import config as st_config
        names = set(getattr(st_config, "_config_options_template", {}) or {})
        names |= set(getattr(st_config, "_config_options", {}) or {})
        return names
    except Exception:                                         # noqa: BLE001
        return set()


def streamlit_argv(script: Path, port: int) -> list:
    known = known_config_options()
    argv = ["streamlit", "run", str(script)]

    def add(name: str, value: str) -> None:
        if not known or name in known:
            argv.append(f"--{name}={value}")

    add("global.developmentMode", "false")
    add("server.address", BIND_HOST)
    add("server.port", str(port))
    add("server.headless", "true")
    add("server.fileWatcherType", "none")
    add("server.runOnSave", "false")
    add("browser.gatherUsageStats", "false")
    add("browser.serverAddress", BIND_HOST)
    add("browser.serverPort", str(port))
    add("client.toolbarMode", "minimal")
    return argv


def apply_env(state: Path, port: int) -> None:
    """The same settings as the flags, as environment variables too: an unknown
    STREAMLIT_* variable is ignored, where an unknown flag stops start-up."""
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
    os.environ["STREAMLIT_SERVER_ADDRESS"] = BIND_HOST
    os.environ["STREAMLIT_SERVER_PORT"] = str(port)
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    # matplotlib needs a writable cache; the program folder is not the place.
    mpl = state / "mpl-cache"
    try:
        mpl.mkdir(parents=True, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = str(mpl)
    except OSError:
        pass


def warm_matplotlib(state: Path) -> None:
    """
    On the first run only, build matplotlib's font list in the background.

    It scans every font Windows has — several seconds on a typical PC — and
    would otherwise do it in the middle of drawing the first chart. Done once,
    it is cached in the user's folder for every later start.
    """
    if list((state / "mpl-cache").glob("fontlist-*.json")):
        return

    def run():
        started = time.time()
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.font_manager                    # noqa: F401
            log(f"matplotlib font list built in {time.time() - started:.1f}s")
        except Exception as exc:                              # noqa: BLE001
            log(f"matplotlib warm-up skipped ({exc})")

    threading.Thread(target=run, name="mpl-warmup", daemon=True).start()


# ------------------------------------------------------------- start-up page
_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
{icon_link}
<style>
  html,body{{height:100%;margin:0;background:#FFFFFF;color:#171A23;
    font-family:"Segoe UI",system-ui,-apple-system,sans-serif;}}
  .wrap{{height:100%;display:flex;flex-direction:column;align-items:center;
    justify-content:center;gap:16px;text-align:center;padding:0 24px;}}
  .icon{{width:76px;height:76px;margin-bottom:4px;}}
  h1{{margin:0;font-size:28px;font-weight:700;letter-spacing:-.01em;color:#1F3A5F;}}
  .tag{{font-size:13px;color:#6B7280;margin-top:-8px;}}
  .bar{{width:260px;height:4px;border-radius:2px;background:#E8EDF4;overflow:hidden;
    margin-top:14px;}}
  .bar i{{display:block;height:100%;width:36%;border-radius:2px;background:#1F3A5F;
    animation:slide 1.2s ease-in-out infinite;}}
  .bar.stop i{{animation:none;width:100%;background:#B42318;}}
  @keyframes slide{{0%{{transform:translateX(-105%)}}100%{{transform:translateX(300%)}}}}
  .msg{{font-size:14px;color:#1F2937;font-weight:600;}}
  .hint{{font-size:12.5px;color:#6B7280;max-width:440px;line-height:1.6;}}
  code{{font-family:Consolas,monospace;font-size:12px;background:#F3F5F8;padding:1px 5px;
    border-radius:4px;word-break:break-all;}}
</style></head>
<body><div class="wrap">
  {icon_img}
  <h1>{title}</h1>
  <div class="tag">{tagline}</div>
  <div class="bar{bar_class}"><i></i></div>
  <div class="msg">{message}</div>
  <div class="hint">{hint}</div>
</div>
<script>{script}</script>
</body></html>
"""


def _icon_data_uri() -> str:
    try:
        raw = (bundle_dir() / "desktop" / "icon.png").read_bytes()
        return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    except OSError:
        return ""


_ICON = None


def write_page(state: Path, message: str, hint: str = "", redirect_to: str = "",
               failed: bool = False) -> Path:
    """(Re)write the start-up page. While waiting it reloads itself; once the
    server is up the launcher rewrites it with a redirect to the app."""
    global _ICON
    if _ICON is None:
        _ICON = _icon_data_uri()
    if redirect_to:
        # Straight on to the app while this page is fresh (the normal start).
        # Opened later from a stale pin of the window, it first checks the app
        # is running - by loading the server's own icon, which a file:// page
        # may do - and otherwise says how to start it, instead of showing the
        # browser's "can't reach this page".
        script = (
            "(function(){var url=" + json.dumps(redirect_to) + ",written="
            + str(int(time.time() * 1000)) + ";"
            "if(Date.now()-written<60000){location.replace(url);return;}"
            "function probe(){var i=new Image();"
            "i.onload=function(){location.replace(url);};"
            "i.onerror=function(){"
            "document.querySelector('.msg').textContent=" + json.dumps(f"{APP_TITLE} is not running") + ";"
            "document.querySelector('.hint').textContent="
            + json.dumps(f"Open it from the {APP_TITLE} shortcut on the Desktop or in the "
                         "Start menu. This window can be closed.") + ";"
            "document.querySelector('.bar').className='bar stop';"
            "setTimeout(probe,3000);};"
            "i.src=url+'/favicon.png?t='+Date.now();}probe();})();")
    elif failed:
        script = ""
    else:
        script = ("setTimeout(function(){location.replace('startup.html?t='+Date.now());},"
                  "1200);")
    icon_link = f'<link rel="icon" href="{_ICON}">' if _ICON else ""
    icon_img = f'<img class="icon" src="{_ICON}" alt="">' if _ICON else ""
    path = state / "startup.html"
    try:
        path.write_text(_PAGE.format(title=APP_TITLE, tagline=app_info.TAGLINE,
                                     icon_link=icon_link, icon_img=icon_img,
                                     message=message, hint=hint, script=script,
                                     bar_class=" stop" if failed else ""),
                        encoding="utf-8")
    except OSError:
        pass
    return path


# -------------------------------------------------------------- the window
def find_chromium():
    """Any Chromium-family browser. Edge first: it ships with every supported
    Windows and cannot normally be removed, so it is the one sure to be there."""
    candidates = []
    if sys.platform.startswith("win"):
        relative = [
            r"Microsoft\Edge\Application\msedge.exe",
            r"Google\Chrome\Application\chrome.exe",
            r"BraveSoftware\Brave-Browser\Application\brave.exe",
            r"Vivaldi\Application\vivaldi.exe",
            r"Chromium\Application\chrome.exe",
        ]
        roots = [os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"),
                 os.environ.get("LOCALAPPDATA")]
        for root in roots:
            if root:
                candidates += [Path(root) / rel for rel in relative]
        try:
            import winreg
            for exe in ("msedge.exe", "chrome.exe"):
                for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + exe
                        with winreg.OpenKey(hive, key) as handle:
                            value, _ = winreg.QueryValueEx(handle, "")
                            if value:
                                candidates.append(Path(value.strip('"')))
                    except OSError:
                        continue
        except ImportError:
            pass
    elif sys.platform == "darwin":
        candidates += [
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        ]
    for name in ("msedge", "microsoft-edge", "google-chrome", "google-chrome-stable",
                 "chromium", "chromium-browser", "brave-browser", "chrome"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    extra = os.environ.get("QARS_BROWSER", "").strip()
    if extra:
        candidates.insert(0, Path(extra))
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def streamlit_static_dir() -> Path:
    """streamlit/static, found without importing streamlit."""
    candidate = bundle_dir() / "streamlit" / "static"
    if candidate.is_dir():
        return candidate
    try:
        import importlib.util
        spec = importlib.util.find_spec("streamlit")
        if spec and spec.origin:
            return Path(spec.origin).parent / "static"
    except Exception:                                         # noqa: BLE001
        pass
    return candidate


def frontend_stamp() -> str:
    """A short fingerprint of this frontend build (its index.html)."""
    try:
        return hashlib.md5((streamlit_static_dir() / "index.html").read_bytes()).hexdigest()[:10]
    except OSError:
        return "default"


def log_frontend_inventory() -> None:
    try:
        js = streamlit_static_dir() / "static" / "js"
        count = len(list(js.glob("*.js"))) if js.is_dir() else 0
        log(f"frontend: {count} JS chunks bundled")
        if count < 50:
            log("WARNING: far fewer frontend files than expected - the build looks "
                "incomplete. Rebuild after deleting desktop\\build and desktop\\dist.")
    except Exception as exc:                                  # noqa: BLE001
        log(f"frontend: could not count the files ({exc})")


def profile_dir(state: Path) -> Path:
    """The window's private browser profile, keyed to this frontend build.
    Profiles from any other build are deleted, so no stale cache survives."""
    root = state / "app-window"
    root.mkdir(parents=True, exist_ok=True)
    profile = root / ("profile-" + frontend_stamp())
    for old in root.glob("profile-*"):
        if old != profile:
            shutil.rmtree(old, ignore_errors=True)
            log(f"cleared the cache of an earlier build: {old.name}")
    profile.mkdir(parents=True, exist_ok=True)
    _mark_clean_exit(profile)
    return profile


def _mark_clean_exit(profile: Path) -> None:
    """A window ended by Shut down, a logoff or a power cut would otherwise
    greet the next start with "Restore pages?". Tell the profile it exited
    cleanly, so the app opens on itself and nothing else."""
    prefs = profile / "Default" / "Preferences"
    try:
        data = json.loads(prefs.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    prof = data.setdefault("profile", {})
    if prof.get("exit_type") != "Normal" or prof.get("exited_cleanly") is not True:
        prof["exit_type"] = "Normal"
        prof["exited_cleanly"] = True
        try:
            prefs.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass


def os_scale_factor() -> float:
    """
    Display scaling Windows applies (1.0 at 100%, 1.5 at 150%).

    GetDpiForSystem reports 96 to a DPI-unaware process, which a frozen Python
    is, so it is wrong on a scaled display. The ratio of the true pixel width
    (DESKTOPHORZRES) to the virtualised one (HORZRES) is the real factor; only
    when that is 1.0 is GetDpiForSystem trustworthy.
    """
    if not sys.platform.startswith("win"):
        return 1.0
    scale = 1.0
    try:
        import ctypes
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        hdc = user32.GetDC(0)
        if hdc:
            try:
                logical = gdi32.GetDeviceCaps(hdc, 8)          # HORZRES
                physical = gdi32.GetDeviceCaps(hdc, 118)       # DESKTOPHORZRES
            finally:
                user32.ReleaseDC(0, hdc)
            if logical > 0 and physical > 0:
                scale = physical / float(logical)
        if scale <= 1.01:
            dpi = user32.GetDpiForSystem()
            if dpi and dpi > 96:
                scale = dpi / 96.0
    except Exception:                                         # noqa: BLE001
        return 1.0
    return min(4.0, max(0.5, scale))


def open_in_default_browser(url: str) -> None:
    """Last resort. The build-stamped query keeps a shared browser cache from
    serving an index.html that points at files this build does not have."""
    target = url if url.startswith("file:") else f"{url}/?_build={frontend_stamp()}"
    webbrowser.open(target)


def launch_window(url: str, state: Path):
    """Open the app window on `url`. Returns its process, or None when it fell
    back to the default browser (whose closing must not stop the server)."""
    if WINDOW_MODE == "browser":
        log("QARS_WINDOW=browser - using the default browser")
        open_in_default_browser(url)
        return None
    browser = find_chromium()
    if browser is None:
        log("no Chromium-family browser found - falling back to the default browser")
        open_in_default_browser(url)
        return None

    zoom_args, zoom_note = [], "native display size"
    if abs(ZOOM - 1.0) > 0.001:
        display = os_scale_factor()
        scale = round(display * ZOOM, 4)
        zoom_args = [f"--force-device-scale-factor={scale}"]
        zoom_note = f"{int(ZOOM * 100)}% (display {display:.2f}x -> device scale {scale})"

    args = [
        str(browser),
        f"--app={url}",
        f"--user-data-dir={profile_dir(state)}",
        *zoom_args,
        "--start-maximized",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-mode",
        "--disable-sync",
        "--disable-extensions",
        "--hide-crash-restore-bubble",
        # The window only ever shows 127.0.0.1 and its own start-up page.
        "--no-proxy-server",
        "--disable-features=Translate,TranslateUI,msEdgeWelcomePage,msImplicitSignin",
    ]
    # For support and automated testing only: extra switches for the window.
    args += [a for a in os.environ.get("QARS_BROWSER_ARGS", "").split() if a.startswith("--")]
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, creationflags=flags)
        log(f"window opened with {browser.name} at {zoom_note}")
        return proc
    except Exception as exc:                                  # noqa: BLE001
        log(f"could not open the window ({exc}) - falling back to the default browser")
        open_in_default_browser(url)
        return None


def close_window(proc) -> None:
    """Close the window the way its close button would, so Edge saves its
    settings (zoom included); force it only if that has not worked."""
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(["taskkill", "/PID", str(proc.pid)], capture_output=True,
                           creationflags=flags, timeout=10)
            try:
                proc.wait(timeout=4)
                return
            except subprocess.TimeoutExpired:
                pass
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, creationflags=flags, timeout=10)
        else:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception as exc:                                  # noqa: BLE001
        log(f"could not close the window cleanly ({exc})")


# --------------------------------------------------------------- watchers
def active_session_count() -> int:
    """Browsers connected, or -1 if it cannot be known (an internal API that a
    future Streamlit may move — -1 disables the backstop rather than firing it)."""
    try:
        from streamlit.runtime import get_instance
        return len(get_instance()._session_mgr.list_active_sessions())
    except Exception:                                         # noqa: BLE001
        return -1


def watch_sessions(idle_seconds: float = 30.0) -> None:
    """Quit once no browser has been connected for a while. Used when the
    window is not a process of ours to watch."""
    seen, last_active = False, time.time()
    while True:
        time.sleep(3.0)
        count = active_session_count()
        if count > 0:
            seen, last_active = True, time.time()
        elif count == 0 and seen and time.time() - last_active > idle_seconds:
            log(f"no window connected for {idle_seconds:.0f}s - shutting down")
            os._exit(0)


def watch_window(proc, opened_at: float) -> None:
    """Stop the server when the window closes, so nothing is left running."""
    try:
        proc.wait()
    except Exception:                                         # noqa: BLE001
        return
    if time.time() - opened_at < HANDOFF_GRACE_SECONDS:
        log("window process handed over at once - watching the app's sessions instead")
        watch_sessions()
        return
    log("window closed - shutting down")
    os._exit(0)


# --------------------------------------------------------------------- main
def selftest() -> int:
    """
    `QA Report Studio.exe --selftest <report.txt>`: run desktop/check_app.py
    inside the packaged program and write what it found to the file. Opens no
    window and touches no user data, so a build can be verified on a machine
    nobody is sitting at.
    """
    at = sys.argv.index("--selftest")
    target = (Path(sys.argv[at + 1]) if len(sys.argv) > at + 1
              else Path(tempfile.gettempdir()) / "qars-selftest.txt")
    redirect_streams(target.with_name(target.name + ".log"))
    lines = []
    try:
        import check_app
        ok = check_app.run(out=lines.append)
    except Exception:                                         # noqa: BLE001
        import traceback
        lines.append(traceback.format_exc())
        ok = False
    try:
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0 if ok else 1


def second_instance(state: Path) -> int:
    """The program is already running: show it rather than start another."""
    if focus_existing_window():
        log("already running - brought its window to the front")
        return 0
    try:
        url = (state / "url.txt").read_text(encoding="utf-8").strip()
    except OSError:
        url = ""
    if url and server_answers(url, timeout=3):
        log("already running - opening another window onto it")
        launch_window(url, state)
    else:
        log("already starting - its own window is on the way")
    return 0


def main() -> int:
    multiprocessing.freeze_support()
    if "--selftest" in sys.argv:
        return selftest()
    from qars import desktop

    started = time.time()
    state = Path(desktop.home(app_info.APP_ID))
    if not claim_single_instance():
        # The running copy owns launcher.log; this one notes what it did aside.
        redirect_streams(state / "launcher-again.log")
        return second_instance(state)
    redirect_streams(state / "launcher.log")
    log(f"{APP_TITLE} {app_info.VERSION} - Python {sys.version.split()[0]}, "
        f"{'frozen' if getattr(sys, 'frozen', False) else 'from source'}")

    root = bundle_dir()
    script = root / "app.py"
    port = pick_port(app_info.PREFERRED_PORT)
    url = f"http://{BIND_HOST}:{port}"
    try:
        (state / "url.txt").write_text(url, encoding="utf-8")
    except OSError:
        pass
    log(f"program folder: {root}")
    log(f"user folder:    {state}")
    log(f"address:        {url}")

    # The window first, so something is on screen within a second; every
    # other step happens while it shows the start-up page.
    page = write_page(state, "Starting up…",
                      "The first start after installing takes a little longer. "
                      "This window switches to the app by itself.")
    window = {"proc": None, "opened": time.time()}
    window["proc"] = launch_window(page.as_uri(), state)
    log(f"start-up page on screen after {time.time() - started:.2f}s")
    # Watched from this moment, so closing the window during start-up quits
    # too, and a window that hands over at once is told apart from one the
    # user closed later however long the server takes to come up.
    if window["proc"] is not None:
        threading.Thread(target=watch_window, args=(window["proc"], window["opened"]),
                         name="window-watch", daemon=True).start()
    else:
        threading.Thread(target=watch_sessions, name="session-watch", daemon=True).start()

    def end_program():
        log("Shut down pressed in the app")
        time.sleep(0.8)          # let the "closing" page reach the window first
        close_window(window["proc"])
        os._exit(0)

    desktop.on_shutdown(end_program)

    if not script.is_file():
        log(f"FATAL: app.py is missing from {root}")
        write_page(state, "The program files are incomplete",
                   "Run the setup file again to repair the installation.", failed=True)
        time.sleep(3)
        return 2

    try:
        os.chdir(root)            # Streamlit reads .streamlit/config.toml from here
    except OSError:
        pass

    home, report = desktop.prepare(str(root / "qars" / "library"), root=str(state))
    log(f"report library: {report['action']} "
        f"(+{len(report['added'])} ~{len(report['updated'])} -{len(report['removed'])}) "
        f"in {os.environ.get('QARS_LIBRARY_DIR', '(program folder)')}")
    apply_env(state, port)
    warm_matplotlib(state)

    def when_ready():
        log_frontend_inventory()
        if wait_for_server(url, STARTUP_TIMEOUT_SECONDS):
            write_page(state, "Opening…", redirect_to=url)
            log(f"app ready after {time.time() - started:.2f}s")
        else:
            log(f"the server did not answer within {STARTUP_TIMEOUT_SECONDS}s")
            write_page(state, f"{APP_TITLE} could not start",
                       f"The reason is in <code>{state / 'launcher.log'}</code>. "
                       "Close this window and try again.", failed=True)

    threading.Thread(target=when_ready, name="ready-check", daemon=True).start()

    try:
        from streamlit.web import cli as stcli
        sys.argv = streamlit_argv(script, port)
        return stcli.main()
    except SystemExit:
        raise
    except BaseException:                                     # noqa: BLE001
        import traceback
        traceback.print_exc()
        write_page(state, f"{APP_TITLE} could not start",
                   f"The reason is in <code>{state / 'launcher.log'}</code>. "
                   "Close this window and try again.", failed=True)
        time.sleep(3)
        return 1


if __name__ == "__main__":
    sys.exit(main())
