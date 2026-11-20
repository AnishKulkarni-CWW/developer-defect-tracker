# QA Report Studio as a Windows program

`build_exe.bat` turns the app into **one file to give to people** —
`QA Report Studio Setup.exe`. They double-click it once, and from then on the
app opens from a Desktop icon **in its own window**, like any installed
program: no browser tab, no address bar, no "localhost", no Python, no
internet, and no administrator password at any point.

The quick version is in [`START_HERE.txt`](../START_HERE.txt). This page has
the detail.

---

## 1. What the person you give it to sees

1. **They double-click `QA Report Studio Setup.exe`.** A small window shows a
   progress bar for a few seconds while it installs itself into their own
   user folder (`%LOCALAPPDATA%\Programs\QA Report Studio`). Nothing is asked.
2. **A "QA Report Studio" icon appears** on their Desktop and in the Start
   menu, and the app opens.
3. **Every start after that:** a window with a "Starting up…" page appears
   within a second, and turns into the app a second or two later (measured
   on Windows: the window in 0.1 s, the app ready in 1–2 s). The window has
   its own taskbar button and the app's ladybug icon.
4. **To quit:** close the window, or press **⏻ Shut down app** at the bottom of
   the menu. Either way the whole program stops; nothing is left running.

Opening the icon again while the app is open brings its window to the front
instead of starting a second copy.

> **"Windows protected your PC"** — the first time a *downloaded* copy is
> opened, Windows SmartScreen may show this. Click **More info → Run anyway**.
> Windows says it about every program that is not signed with a paid
> code-signing certificate. It is not an administrator prompt and it does not
> come back. (A copy built on the same PC, or copied from a USB stick, usually
> does not show it at all.)

### Why it needs no administrator rights

| What | Where | Why that needs no admin |
|---|---|---|
| The program | `%LOCALAPPDATA%\Programs\QA Report Studio` | Windows' own place for per-user programs |
| Shortcuts | the user's Desktop and Start menu | the user's own folders, found even when the Desktop is moved to OneDrive |
| Reports, imports, settings | `%LOCALAPPDATA%\QAReportStudio` | the user's own folder |
| The app's server | `127.0.0.1` only | loopback: Windows Firewall never asks, and nothing on the network can reach it |

Both `.exe` files carry an *asInvoker* manifest, so Windows has no reason to
ask for elevation. The test run on GitHub checks that on every build.

### Works offline, on any Windows 10 or 11 PC

Everything the app needs is inside the program folder — Python, Streamlit,
the report engine, the fonts of the charts, and the report library. The window
is drawn by **Microsoft Edge**, which is part of every Windows 10 and 11
installation; the app uses Edge in "app mode" on a private profile of its own,
so it never touches the user's own Edge tabs, sign-in or extensions. If Edge
were missing, Chrome, Brave or Vivaldi is used, and as the very last resort the
default browser.

---

## 2. Building the setup file

### What the build PC needs

- **Windows 10 or 11**, 64-bit.
- **Python 3.12, 3.13 or 3.14** (64-bit) from
  [python.org](https://www.python.org/downloads/windows/). On the installer's
  first screen tick **Add python.exe to PATH**; with no admin rights, untick
  **Use admin privileges when installing py.exe**. Python 3.15 is too new for
  some of the libraries; `build_exe.bat` picks a suitable version by itself
  when several are installed.
  One-line alternative: `winget install -e --id Python.Python.3.12 --scope user`
- **Internet, once**, while the libraries download (~350 MB).
- About **3 GB free** for the build tools.

Only this PC needs any of that. The people you give the setup file to need
nothing.

### The build

Double-click **`build_exe.bat`** in the main folder. It runs six steps:

| Step | What happens | First time | After that |
|---|---|---|---|
| 1/6 | Finds Python 3.11–3.14 | seconds | seconds |
| 2/6 | Creates a private build environment in `%LOCALAPPDATA%\QARS-build` | 30 s | reused |
| 3/6 | Installs the exact library versions in `desktop\requirements-lock.txt` | 3–8 min | seconds |
| 4/6 | Checks the app: reads every report in the library and builds a PowerPoint and a PDF for each market | 15 s | 15 s |
| 5/6 | Builds the program folder with PyInstaller | 3–10 min | 3–10 min |
| 6/6 | Packs it into the setup file | 1–2 min | 1–2 min |

It finishes with **DONE**, prints where the file is, and offers to show it in
Explorer:

```
desktop\dist\QA Report Studio Setup.exe      (about 100 MB)
```

Scrolling text and a few `WARNING` lines during step 5 are normal.

**Why the build tools live in `%LOCALAPPDATA%\QARS-build`:** a zip unpacked
inside Downloads easily makes file paths longer than Windows allows, and the
build then fails half-way with "file not found". The short folder avoids that.
It is safe to delete at any time; the next build recreates it.

### Or let GitHub build it

The repository has a workflow, **Windows desktop build**
(`.github/workflows/desktop-build.yml`), that runs `build_exe.bat` on a fresh
Windows machine whenever the app changes, then installs the result and uses it
the way a person would: opens the window in Edge, imports a month, downloads
a report, and quits with Shut down app, with the window's close button, and
with a second click on the icon.

To take its setup file: **Actions** tab → **Windows desktop build** → the
latest run with a green tick → **Artifacts** → **QA-Report-Studio-Setup**.
Download, unzip, done. (Artifacts are kept 14 days; once this branch is
merged, the **Run workflow** button on that page makes a fresh one any time.)

---

## 3. Updating

When the app changes — new code, or new months embedded in `qars/library/` —
pull the repository, run `build_exe.bat` again, and send the new setup file.

People run the new setup file over the old installation. It replaces the
program folder (asking them to close the app first if it is open) and keeps
everything they imported. Running the **same** version's setup again simply
opens the app, and puts back a Desktop shortcut that was deleted.

**What happens to the report library on an update:**

- Months the new build ships with are added — including any month imported
  into the repository since the last build.
- A shipped file the new build no longer carries is retired, exactly as it was
  retired in the repository.
- Everything imported on that computer stays exactly as it was. If someone
  re-imported a corrected sheet over a shipped one, their version is kept.
- Name decisions made on that computer win over shipped ones.

---

## 4. Using the desktop app

It is the same app as the online one, with three differences:

1. **Months are kept on the computer.** An imported sheet is saved to
   `%LOCALAPPDATA%\QAReportStudio\library` and loaded every time the app
   starts. *Data Manager → Report library* shows the folder and has an
   **Open the library folder** button.
2. **No publishing to GitHub.** The desktop app is for working offline;
   it makes no network calls at all.
3. **A Shut down app button** at the bottom of the menu.

**Moving history between computers, or to and from the online app:**
*Data Manager → Report library → Download the library pack* on one, and
*Restore a library pack* on the other.

**Downloads** — the PowerPoint, PDF and CSV — go to the user's Downloads
folder, and Edge lists each one as it finishes.

**Text size:** Ctrl + plus / Ctrl + minus (Ctrl + 0 resets), remembered
between starts.

**Pinning to the taskbar:** right-click **QA Report Studio** in the Start menu
→ **Pin to taskbar**. (Pin the program, not the open window: the window
belongs to Edge, so its own pin would start Edge rather than the app.)

### Where it writes

Only in the user's own folder — never in the program folder:

```
%LOCALAPPDATA%\QAReportStudio\
    library\          the report library: shipped reports and sheets + imports
    data\             the working copy, settings and automatic backups
    launcher.log      the start-up log - the first thing to read if something fails
    install.log       what setup did
    app-window\       the window's private browser profile
    mpl-cache\        the charts' font cache
    startup.html, url.txt
```

### Removing it

Delete `%LOCALAPPDATA%\Programs\QA Report Studio` and the two shortcuts
(Desktop, and Start menu → QA Report Studio). To remove the data too, delete
`%LOCALAPPDATA%\QAReportStudio` — download a library pack first if the months
in it matter.

---

## 5. If something goes wrong

| What you see | What to do |
|---|---|
| **Windows protected your PC** | More info → Run anyway (see section 1). |
| **The antivirus removes or blocks the setup file** | Programs built with PyInstaller are sometimes flagged by mistake (the build already avoids UPX, the most common trigger). Ask IT to allow `QA Report Studio Setup.exe` and the folder `%LOCALAPPDATA%\Programs\QA Report Studio`. |
| **build_exe.bat: "No suitable Python was found"** | Install Python 3.12 as in section 2, then run it again. |
| **build_exe.bat: installing the libraries failed** | Usually no internet, or a company proxy blocking pypi.org. Try from another network. If you changed Python, delete `%LOCALAPPDATA%\QARS-build` and run it again. |
| **build_exe.bat: "Access is denied" during step 5** | The antivirus was scanning a file. Run `build_exe.bat` again. |
| **build_exe.bat: step 4 fails** | The app itself has a problem with this copy of the files (for example a damaged sheet in `qars\library`); the message names it. Nothing is built, because the setup file would carry the same fault. |
| **Setup says the app is still open** | Close its window (or press Shut down app); setup carries on by itself. |
| **The window stays on "Starting up…"** | Wait a minute on the very first start after installing. If it then says it could not start, open `%LOCALAPPDATA%\QAReportStudio\launcher.log`: the reason is at the end. |
| **The app opens in a browser tab instead of a window** | No Edge or Chrome was found, so the default browser was used. Everything works the same; close the tab when you are done (the app stops by itself 30 seconds later). |
| **"Restore pages?" or an Edge welcome screen** | Should not appear (the app suppresses both). If it does, close it once; the app's window profile is private, so it will not affect the user's own Edge. |
| **Text too small or too large** | Ctrl + plus / minus. To start at a fixed size, set the user environment variable `QARS_ZOOM` (for example `1.25`). |
| **Anything else** | Send the two log files from `%LOCALAPPDATA%\QAReportStudio` (`launcher.log`, `launcher.prev.log`). |

The packaged program can check itself without opening a window:

```
"%LOCALAPPDATA%\Programs\QA Report Studio\QA Report Studio.exe" --selftest "%USERPROFILE%\Desktop\selftest.txt"
```

It reads every report in its library and builds a PowerPoint and a PDF for
each market, then writes what it found to that file.

---

## 6. For IT departments

- Per-user install, no elevation, no services, no registry changes, no
  scheduled tasks, no network listeners except `127.0.0.1`.
- Silent install: `"QA Report Studio Setup.exe" --quiet` (add `--no-launch`
  to not open the app afterwards). Exit code 0 on success, 1 if the app is
  open, 3 for disk space, 4 for a failed install.
- Install size about 200 MB; the per-user data folder grows with the
  imported sheets (kilobytes per month).
- The app makes no outbound network connections.

---

## 7. How it is put together

| File | What it does |
|---|---|
| `build_exe.bat` (main folder) | The one-click build. |
| `desktop/run_app.py` | The launcher frozen into `QA Report Studio.exe`: the start-up window, the Edge app window, the server, shutting down. The only file that knows the app is packaged — `app.py` still runs with `streamlit run app.py`. |
| `qars/desktop.py` | Gives each user their own library and working copy, and merges a new build's library into it. |
| `desktop/qa_report_studio.spec` | The PyInstaller recipe for the program folder. |
| `desktop/make_payload.py` | Zips the program folder for the setup file. |
| `desktop/installer.py` + `installer.spec` | The one-file setup program. |
| `desktop/check_app.py` | The check `build_exe.bat` runs before building, and `--selftest` runs inside the program. |
| `desktop/app_info.py` | The program's name, version and ports, in one place. |
| `desktop/requirements-lock.txt` | The exact library versions every build uses. |
| `desktop/icon.ico`, `icon.png` | The program, shortcut and window icon. |
| `.github/workflows/desktop-build.yml` | The Windows build-and-test run on GitHub. |

**Why a setup file rather than one big self-contained .exe:** a one-file
PyInstaller program unpacks ~400 MB to a temporary folder on every start —
several seconds, more while antivirus scans it — and leaves that behind if it
crashes. Unpacked once by setup, every start is folder speed. It is still one
file to send.

**Why the window opens on a page of its own first:** `import streamlit` is the
slowest part of starting, so the window is opened before it, on a local
"Starting up…" page, and the launcher redirects that page to the app the moment
the server answers. Something is on screen within a second of the double-click.

**Why the window has a private profile:** Streamlit's frontend is several
hundred files named by content hash. A browser cache shared between two
versions serves one version's index to the other and every widget breaks. The
profile is keyed to the exact frontend build, so an update starts clean — and
the user's own Edge is never involved.

**Why no Tcl/Tk:** packaged tkinter is the usual source of "Failed to load Tcl
DLL" errors. Nothing here needs a GUI toolkit; the start-up page is HTML in the
app's own window.

**Security:** the server listens on `127.0.0.1` only; the build refuses to
include a `.streamlit/secrets.toml`, so a GitHub token on the build PC can never
travel inside the setup file; the desktop app switches publishing off.

**Renaming the program:** change `APP_NAME` in `desktop/app_info.py` and
`APP_TITLE` in `app.py` to the same text, then build.
