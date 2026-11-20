"""
CI on a real Windows machine: drive the INSTALLED app the way a person would.

Opens it from its program file, waits for the Edge app window, imports a month,
downloads a report, then quits three ways - the Shut down button, the window's
close button (WM_CLOSE), and a second launch while it is open. Talks to the
window over Edge's debugging port (QARS_BROWSER_ARGS), which only tests use.
"""
import ctypes
import glob
import os
import subprocess
import sys
import time
import urllib.request
from ctypes import wintypes

from playwright.sync_api import sync_playwright

LOCAL = os.environ["LOCALAPPDATA"]
EXE = os.path.join(LOCAL, "Programs", "QA Report Studio", "QA Report Studio.exe")
HOME = os.path.join(LOCAL, "QAReportStudio")
LOG = os.path.join(HOME, "launcher.log")
SHOTS = sys.argv[1] if len(sys.argv) > 1 else "ci-shots"
os.makedirs(SHOTS, exist_ok=True)
ENV = dict(os.environ, QARS_BROWSER_ARGS="--remote-debugging-port=9222")
results = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + label + (f"  --  {detail}" if detail else ""),
          flush=True)


def log_text():
    try:
        with open(LOG, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def wait_for(fn, timeout, step=0.25):
    end = time.time() + timeout
    while time.time() < end:
        value = fn()
        if value:
            return value
        time.sleep(step)
    return None


def cdp_up():
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=2):
            return True
    except Exception:
        return False


def start():
    started = time.time()
    proc = subprocess.Popen([EXE], env=ENV)
    return proc, started


def app_windows():
    user32 = ctypes.WinDLL("user32")
    found = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if buf.value == "QA Report Studio" and cls.value.startswith("Chrome_WidgetWin"):
            found.append(hwnd)
        return True

    user32.EnumWindows(proto(visit), 0)
    return found


def page_of(browser):
    for ctx in browser.contexts:
        for pg in ctx.pages:
            if pg.url.startswith("http://127.0.0.1"):
                return pg
    return None


def sheet():
    lines = ["Mail Title,Date,Test Environment,Developer Name,Status,Error Type,Error Severity"]
    for i in range(30):
        status = "Error" if i % 10 == 0 else "First Time Correct"
        lines.append(f"Oct task {i + 1},2026-10-{i % 27 + 1:02d},Test,Neha Lal,{status},"
                     f"{'Content Related' if status == 'Error' else ''},"
                     f"{'Major' if status == 'Error' else ''}")
    path = os.path.join(SHOTS, "October 2026 India.csv")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


# ------------------------------------------------------------- 1st start
proc, t0 = start()
shown = wait_for(lambda: "start-up page on screen" in log_text(), 60)
ready = wait_for(lambda: "app ready" in log_text(), 240)
check("The start-up window opens", shown, f"{time.time() - t0:.1f}s after launch")
check("The app is ready in its window", ready)
print(log_text(), flush=True)
check("Edge's debugging port answers (the window is Edge)", wait_for(cdp_up, 30))
time.sleep(5)
check("The window process stays its own (no hand-over to another browser)",
      "handed over at once" not in log_text())

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    page = wait_for(lambda: page_of(browser), 60)
    check("The window shows the app", page is not None, page.url if page else "")
    page.set_default_timeout(90000)
    page.get_by_role("button", name="⏻  Shut down app").wait_for()
    check("Page title is the app's", page.title() == "QA Report Studio", page.title())
    bars = page.evaluate("() => [window.locationbar.visible, window.toolbar.visible,"
                         " window.menubar.visible]")
    check("No address bar, toolbar or menu bar (a standalone app window)",
          bars == [False, False, False], str(bars))
    page.screenshot(path=os.path.join(SHOTS, "1_home.png"))
    check("A native window titled 'QA Report Studio' is on screen", len(app_windows()) >= 1,
          str(app_windows()))

    page.get_by_role("button", name="☁️ Upload & Configure").click()
    page.wait_for_selector('input[type="file"]', state="attached")
    page.locator('input[type="file"]').first.set_input_files(sheet())
    page.get_by_role("button", name="Read file(s)").click()
    page.get_by_role("button", name="✅  Confirm and import").click()
    page.get_by_text("saved to the report library on this computer").wait_for()
    page.screenshot(path=os.path.join(SHOTS, "2_imported.png"))
    kept = glob.glob(os.path.join(HOME, "library", "India", "2026-10_*"))
    check("An imported month is saved in the user's own library", kept, str(kept))

    downloads = os.path.join(os.environ["USERPROFILE"], "Downloads")
    before = set(glob.glob(os.path.join(downloads, "*.pptx")))
    page.get_by_role("button", name="Generate report").first.click()
    page.get_by_role("button", name="PowerPoint (.pptx)").click()
    got = wait_for(lambda: set(glob.glob(os.path.join(downloads, "*.pptx"))) - before, 60)
    check("A report downloads from the window to the Downloads folder", got, str(got))
    page.screenshot(path=os.path.join(SHOTS, "3_results.png"))

    page.get_by_role("button", name="⏻  Shut down app").click()
    try:
        proc.wait(timeout=30)
        exited = True
    except subprocess.TimeoutExpired:
        exited = False
    check("Shut down app ends the program", exited)
    check("…and closes the window", wait_for(lambda: not cdp_up(), 20)
          and not app_windows())

# ------------------------------------------------- 2nd start: close button
proc, t0 = start()
ready = wait_for(lambda: "app ready" in log_text(), 240)
check("Second start is ready", ready, log_text().split("app ready after")[-1].split("\n")[0])
check("Second start finds the library already in place", "report library: current" in log_text())
hwnds = wait_for(app_windows, 30)
time.sleep(3)
second, t1 = start()
try:
    second.wait(timeout=60)
    quick = True
except subprocess.TimeoutExpired:
    quick = False
again = ""
try:
    with open(os.path.join(HOME, "launcher-again.log"), encoding="utf-8") as fh:
        again = fh.read()
except OSError:
    pass
check("Opening it again while it runs starts no second copy", quick, again.strip())
time.sleep(2)
for hwnd in app_windows():
    ctypes.WinDLL("user32").PostMessageW(hwnd, 0x0010, 0, 0)       # WM_CLOSE: the X button
try:
    proc.wait(timeout=30)
    exited = True
except subprocess.TimeoutExpired:
    exited = False
check("Closing the window ends the program", exited)
print(log_text(), flush=True)

print(f"\n{sum(results)} of {len(results)} checks passed", flush=True)
sys.exit(0 if all(results) else 1)
