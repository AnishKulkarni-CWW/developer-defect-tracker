#!/usr/bin/env python3
"""
QA Report Studio — the one-file setup program
=============================================
This is what you send to people: a single .exe. No Python, no administrator
password, no internet.

What it does when double-clicked:

  1. unpacks the program folder into the user's own
     %LOCALAPPDATA%\\Programs\\QA Report Studio   (a progress bar runs meanwhile);
  2. puts a "QA Report Studio" shortcut on the Desktop and in the Start menu;
  3. starts the app.

From then on the app opens from that shortcut in a second or two. Running the
setup file again is safe: the same version just opens the app; a newer one
replaces the program folder. The report library and everything imported is
kept in %LOCALAPPDATA%\\QAReportStudio, which setup never touches.

WHY NO ADMINISTRATOR RIGHTS ARE EVER NEEDED
Everything goes into the user's own profile — the program folder, the
shortcuts, the data. Program Files would need elevation; AppData does not. The
.exe is built with an "asInvoker" manifest, so Windows has no reason to ask.

WHY AN INSTALLER, RATHER THAN ONE BIG SELF-EXTRACTING APP
A one-file app unpacks ~400 MB to a temp folder on every start (several
seconds, more while antivirus scans it). Unpacked once here, every start is
folder speed. Still one file to send.

Options, for IT departments and scripted installs:
    --quiet      no pauses, no prompts (errors are still printed)
    --no-launch  do not start the app at the end
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import app_info                                               # noqa: E402

APP_NAME = app_info.APP_NAME
PAYLOAD_NAME = "payload.zip"
VERSION_FILE = ".installed-version"
BAR_WIDTH = 34

QUIET = "--quiet" in sys.argv
NO_LAUNCH = "--no-launch" in sys.argv


# ----------------------------------------------------------------- output
def say(text: str = "") -> None:
    try:
        print(text, flush=True)
    except Exception:                                         # noqa: BLE001
        pass


def progress(done: int, total: int, label: str) -> None:
    if total <= 0 or QUIET:
        return
    frac = done / total
    filled = int(BAR_WIDTH * frac)
    try:
        sys.stdout.write(f"\r   [{'#' * filled}{'.' * (BAR_WIDTH - filled)}] "
                         f"{frac * 100:5.1f}%  {label}   ")
        sys.stdout.flush()
    except Exception:                                         # noqa: BLE001
        pass


def pause(prompt: str = "   Press Enter to close. ") -> None:
    if QUIET:
        return
    try:
        input("\n" + prompt)
    except Exception:                                         # noqa: BLE001
        pass


_LOG = []


def note(text: str) -> None:
    """Kept for install.log, next to the app's own launcher.log."""
    _LOG.append(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {text}")


def write_log() -> None:
    try:
        folder = data_root()
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / "install.log", "a", encoding="utf-8") as fh:
            fh.write("\n".join(_LOG) + "\n")
    except OSError:
        pass


# -------------------------------------------------------------- locations
def bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
                or Path.home() / ".local" / "share")


def install_root() -> Path:
    """%LOCALAPPDATA%\\Programs\\<app>: Windows' own place for per-user programs.
    Needs no elevation, never syncs to OneDrive, survives a reboot."""
    override = os.environ.get("QARS_INSTALL_DIR", "").strip()
    if override:
        return Path(override)
    return local_appdata() / "Programs" / APP_NAME


def data_root() -> Path:
    override = os.environ.get("QARS_HOME", "").strip()
    return Path(override) if override else local_appdata() / app_info.APP_ID


def app_exe(target: Path) -> Path:
    """The installed program. The extension-less name lets this installer be
    exercised on the Linux build machine too."""
    exe = target / app_info.EXE_NAME
    if exe.is_file():
        return exe
    plain = target / app_info.APP_NAME
    return plain if plain.is_file() else exe


# ---------------------------------------------------------------- checks
def payload_version(payload: Path) -> str:
    """A fingerprint of the payload (names, checksums and sizes of every file),
    so a rebuilt app replaces an older install and the same one does not."""
    try:
        with zipfile.ZipFile(payload) as zf:
            digest = hashlib.sha1()
            for info in sorted(zf.infolist(), key=lambda i: i.filename):
                digest.update(f"{info.filename}:{info.CRC}:{info.file_size};".encode("utf-8"))
            return digest.hexdigest()[:16]
    except (OSError, zipfile.BadZipFile):
        return "unknown"


def payload_size(payload: Path) -> int:
    try:
        with zipfile.ZipFile(payload) as zf:
            return sum(i.file_size for i in zf.infolist())
    except (OSError, zipfile.BadZipFile):
        return 0


def already_installed(target: Path, version: str) -> bool:
    try:
        return (app_exe(target).is_file()
                and (target / VERSION_FILE).read_text(encoding="utf-8").strip() == version)
    except OSError:
        return False


def app_is_running() -> bool:
    """The app holds a named mutex (a lock port off Windows) for as long as it
    runs. Its files are open then, and replacing them would fail half-way."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenMutexW.restype = wintypes.HANDLE
            kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel32.OpenMutexW(0x00100000, False,          # SYNCHRONIZE
                                         f"Local\\{app_info.APP_ID}-running")
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:                                     # noqa: BLE001
            pass
    import socket
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", app_info.LOCK_PORT))
        return False
    except OSError:
        return True
    finally:
        s.close()


def wait_until_closed() -> bool:
    """Ask the user to close the running app, and carry on the moment they do."""
    say(f"   {APP_NAME} is open. Close its window (or press Shut down app")
    say("   in its menu) and setup will continue by itself.")
    for _ in range(600):
        if not app_is_running():
            time.sleep(1.0)              # let its files close
            return True
        time.sleep(1.0)
    return False


# --------------------------------------------------------------- install
def _rmtree(path: Path) -> None:
    """Remove a folder, read-only files included."""
    def retry(func, p, _exc):
        try:
            os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass
    if not path.exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


def extract(payload: Path, target: Path) -> None:
    """Unpack beside the target, then swap the folders, so an interrupted run
    can never leave a half-installed program behind."""
    tmp = target.parent / (target.name + ".new")
    _rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(payload) as zf:
        members = zf.infolist()
        total = len(members)
        for index, member in enumerate(members, 1):
            mode = member.external_attr >> 16
            if os.name != "nt" and stat.S_ISLNK(mode):
                link = tmp / member.filename
                link.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(zf.read(member).decode("utf-8"), link)
                continue
            written = Path(zf.extract(member, tmp))
            # zip drops Unix permission bits; restore them so the installer can
            # also be tested on the (Linux) build machine. Meaningless on Windows.
            if mode and os.name != "nt":
                try:
                    os.chmod(written, mode & 0o7777)
                except OSError:
                    pass
            if index % 25 == 0 or index == total:
                progress(index, total, f"{index:,}/{total:,} files")
    if not QUIET:
        say()

    old = target.parent / (target.name + ".old")
    if target.exists():
        _rmtree(old)
        for attempt in range(10):
            try:
                target.rename(old)
                break
            except OSError:
                # Antivirus may still be scanning a file of the old version.
                if attempt == 9:
                    raise
                time.sleep(1.0)
    tmp.rename(target)
    _rmtree(old)


# -------------------------------------------------------------- shortcuts
def _guid(text):
    import ctypes
    import uuid

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                    ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    u = uuid.UUID(text)
    return GUID(u.time_low, u.time_mid, u.time_hi_version,
                (ctypes.c_ubyte * 8)(*u.bytes[8:]))


def known_folder(folder_id: str):
    """A Windows known folder, wherever it really is — a Desktop moved to
    OneDrive (common on company laptops) included."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        shell32 = ctypes.WinDLL("shell32")
        ole32 = ctypes.WinDLL("ole32")
        shell32.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                                 wintypes.HANDLE,
                                                 ctypes.POINTER(ctypes.c_wchar_p)]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        guid = _guid(folder_id)
        out = ctypes.c_wchar_p()
        if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out)) != 0:
            return None
        path = out.value
        ole32.CoTaskMemFree(ctypes.cast(out, ctypes.c_void_p))
        return Path(path) if path else None
    except Exception:                                         # noqa: BLE001
        return None


FOLDERID_DESKTOP = "B4BFCC3A-DB2C-424C-B029-7FE99A87C641"
FOLDERID_PROGRAMS = "A77F5D77-2E2B-44C3-A6A2-ABA601054A51"


def desktop_folder():
    found = known_folder(FOLDERID_DESKTOP)
    if found and found.is_dir():
        return found
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    for candidate in [home / "Desktop", *sorted(home.glob("OneDrive*/Desktop"))]:
        if candidate.is_dir():
            return candidate
    return None


def start_menu_folder():
    found = known_folder(FOLDERID_PROGRAMS)
    if found:
        return found
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return None


def _shortcut_com(link: Path, exe: Path, icon: Path, description: str) -> bool:
    """Write a .lnk through the Shell's own IShellLink object. Works where
    PowerShell is locked down by company policy."""
    import ctypes
    from ctypes import wintypes
    ole32 = ctypes.OleDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                                       ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    try:
        ole32.CoInitializeEx(None, 0x2)                       # COINIT_APARTMENTTHREADED
    except OSError:
        pass                                                  # already initialised: fine

    clsid = _guid("00021401-0000-0000-C000-000000000046")    # CLSID_ShellLink
    iid_link = _guid("000214F9-0000-0000-C000-000000000046")  # IID_IShellLinkW
    iid_file = _guid("0000010b-0000-0000-C000-000000000046")  # IID_IPersistFile
    link_ptr = ctypes.c_void_p()
    ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid_link),
                           ctypes.byref(link_ptr))

    def method(ptr, index, *argtypes):
        vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        fn = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtable[index])
        return lambda *args: fn(ptr, *args)

    file_ptr = ctypes.c_void_p()
    try:
        method(link_ptr, 20, wintypes.LPCWSTR)(str(exe))                  # SetPath
        method(link_ptr, 9, wintypes.LPCWSTR)(str(exe.parent))            # SetWorkingDirectory
        method(link_ptr, 7, wintypes.LPCWSTR)(description)                # SetDescription
        method(link_ptr, 17, wintypes.LPCWSTR, ctypes.c_int)(str(icon), 0)  # SetIconLocation
        method(link_ptr, 0, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
            ctypes.byref(iid_file), ctypes.byref(file_ptr))               # QueryInterface
        method(file_ptr, 6, wintypes.LPCWSTR, wintypes.BOOL)(str(link), True)  # Save
    finally:
        for ptr in (file_ptr, link_ptr):
            if ptr.value:
                vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])(ptr)  # Release
    return link.exists()


def _shortcut_powershell(link: Path, exe: Path, icon: Path, description: str) -> bool:
    def q(value) -> str:              # a PowerShell single-quoted string
        return "'" + str(value).replace("'", "''") + "'"
    ps = ("$w = New-Object -ComObject WScript.Shell; "
          f"$l = $w.CreateShortcut({q(link)}); "
          f"$l.TargetPath = {q(exe)}; "
          f"$l.WorkingDirectory = {q(exe.parent)}; "
          f"$l.IconLocation = {q(str(icon) + ',0')}; "
          f"$l.Description = {q(description)}; "
          "$l.Save()")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", ps],
        capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=60)
    return result.returncode == 0 and link.exists()


def make_shortcut(link: Path, exe: Path, icon: Path) -> bool:
    if os.name != "nt":
        return False
    description = f"{APP_NAME} - {app_info.TAGLINE}"
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    for how in (_shortcut_com, _shortcut_powershell):
        try:
            if how(link, exe, icon, description):
                note(f"shortcut {link} ({how.__name__})")
                return True
        except Exception as exc:                              # noqa: BLE001
            note(f"shortcut {link}: {how.__name__} failed: {exc}")
    return False


def make_shortcuts(target: Path) -> list:
    exe = app_exe(target)
    made = []
    desktop = desktop_folder()
    if desktop and make_shortcut(desktop / f"{APP_NAME}.lnk", exe, exe):
        made.append("Desktop")
    start = start_menu_folder()
    if start and make_shortcut(start / f"{APP_NAME}.lnk", exe, exe):
        made.append("Start menu")
    return made


# ----------------------------------------------------------------- launch
def launch(target: Path) -> bool:
    exe = app_exe(target)
    env = dict(os.environ)
    # This setup program is itself a PyInstaller app. Without this, the app it
    # starts can mistake itself for part of setup and look for its files in
    # setup's temporary folder, which is deleted the moment setup closes.
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    for key in [k for k in env if k.startswith("_PYI_") or k == "_MEIPASS2"]:
        env.pop(key, None)
    flags = 0
    if os.name == "nt":
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        subprocess.Popen([str(exe)], cwd=str(target), env=env, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
        return True
    except Exception as exc:                                  # noqa: BLE001
        say(f"   Could not start it automatically: {exc}")
        note(f"launch failed: {exc}")
        return False


# ------------------------------------------------------------------- main
def main() -> int:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(f"{APP_NAME} Setup")
        except Exception:                                     # noqa: BLE001
            pass
    say()
    say("=" * 62)
    say(f"   {APP_NAME} {app_info.VERSION}  -  Setup")
    say("=" * 62)
    say()

    payload = bundle_dir() / PAYLOAD_NAME
    if not payload.is_file():
        say("   ERROR: this setup file is incomplete (no payload inside).")
        say("   Build it again with build_exe.bat.")
        pause()
        return 2

    target = install_root()
    version = payload_version(payload)
    note(f"setup {app_info.VERSION} payload {version} -> {target}")

    if already_installed(target, version):
        say(f"   {APP_NAME} is already installed and up to date.")
        made = make_shortcuts(target)            # put back a deleted shortcut
        if not NO_LAUNCH:
            say("   Opening it now...")
            launch(target)
        say()
        say(f"   Next time, open it from the '{APP_NAME}' shortcut")
        say("   on your Desktop or in the Start menu.")
        note(f"already installed; shortcuts: {made}")
        write_log()
        time.sleep(0 if QUIET else 3)
        return 0

    if app_is_running():
        if QUIET or not wait_until_closed():
            say(f"   {APP_NAME} is still open. Close it, then run setup again.")
            note("aborted: app still running")
            write_log()
            pause()
            return 1
        say()

    need = payload_size(payload)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(target.parent).free
    except OSError:
        free = need * 3
    if need and free < need * 1.2:
        say(f"   Not enough free disk space: {need / 1e6:.0f} MB is needed, "
            f"{free / 1e6:.0f} MB is free.")
        note("aborted: disk space")
        write_log()
        pause()
        return 3

    say(f"   Installing to:  {target}")
    say("   This happens once and takes about half a minute.")
    say("   No administrator password is needed.")
    say()
    try:
        extract(payload, target)
        (target / VERSION_FILE).write_text(version, encoding="utf-8")
    except Exception as exc:                                  # noqa: BLE001
        say()
        say(f"   ERROR: setup could not finish - {exc}")
        say("   Close the app if it is open, check there is free disk space,")
        say("   and run setup again.")
        note(f"install failed: {exc}")
        write_log()
        pause()
        return 4

    made = make_shortcuts(target)
    say()
    if made:
        say(f"   Shortcut added: {' and '.join(made)}")
    elif os.name == "nt":
        say("   No shortcut could be made. The program is:")
        say(f"     {app_exe(target)}")
    say(f"   Your reports and imported months live in {data_root()}")
    say("   and are kept when the app is updated.")
    say()
    say("=" * 62)
    if NO_LAUNCH:
        say("   DONE.")
    else:
        say(f"   DONE. Opening {APP_NAME}...")
        launch(target)
    say()
    say(f"   From now on, open it with the '{APP_NAME}' shortcut.")
    say("   You can delete this setup file.")
    say("=" * 62)
    note(f"installed; shortcuts: {made}")
    write_log()
    time.sleep(0 if QUIET else 4)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
    except Exception:                                         # noqa: BLE001
        import traceback
        traceback.print_exc()
        pause()
        sys.exit(9)
