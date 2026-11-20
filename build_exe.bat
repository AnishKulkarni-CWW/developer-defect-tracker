@echo off
setlocal EnableExtensions
title QA Report Studio - build the setup file
REM Change folder before delayed expansion is on, so a "!" in the folder's
REM name cannot be mistaken for a variable.
cd /d "%~dp0desktop" || (echo  [X] The desktop folder is missing next to this file. & pause & exit /b 1)
set "SRC=%CD%"
setlocal EnableDelayedExpansion
set "NOPAUSE="
if defined CI set "NOPAUSE=1"
if /i "%~1"=="/nopause" set "NOPAUSE=1"

echo.
echo ============================================================
echo    QA Report Studio  -  build the Windows setup file
echo ============================================================
echo.
echo  This makes ONE file to give to people:
echo     QA Report Studio Setup.exe
echo.
echo  They double-click it once. It installs itself in a few
echo  seconds - no administrator password - puts a shortcut on
echo  the Desktop and opens the app in its own window.
echo.
echo  This computer needs the internet ONCE, now, to download the
echo  libraries. The finished app works completely offline.
echo.

REM ------------------------------------------------------------------ 1/6
REM Python 3.11 to 3.14. The py launcher comes with every python.org install
REM and finds a suitable version even when several are installed.
set "PY="
for %%V in (3.12 3.13 3.11 3.14) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 14) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo  [X] No suitable Python was found.
    echo.
    echo      Install Python 3.12 from https://www.python.org/downloads/
    echo      - on its first screen, tick "Add python.exe to PATH".
    echo      It can sit next to any other Python you already have.
    echo      Then double-click build_exe.bat again.
    echo.
    if not defined NOPAUSE pause
    exit /b 1
)
for /f "usebackq delims=" %%v in (`%PY% -c "import sys; print(sys.version.split()[0])"`) do set "PYVER=%%v"
for /f "usebackq delims=" %%e in (`%PY% -c "import sys; print(sys.executable)"`) do set "PYEXE=%%e"
echo  [1/6] Python !PYVER! found.
echo !PYEXE! | find /i "WindowsApps" >nul && (
    echo        Note: this is the Microsoft Store Python. If the build fails,
    echo        install Python 3.12 from python.org instead and run this again.
)

REM ------------------------------------------------------------------ 2/6
REM The build tools live in a SHORT folder under AppData, not here: a zip
REM unpacked inside Downloads easily makes paths too long for Windows, and
REM then the build breaks half-way through with "file not found".
set "WORK=%LOCALAPPDATA%\QARS-build"
set "VENV=!WORK!\venv"
set "VPY=!VENV!\Scripts\python.exe"
if exist "!VPY!" (
    "!VPY!" -c "import sys" >nul 2>&1 || rmdir /s /q "!VENV!"
)
if not exist "!VPY!" (
    echo  [2/6] Creating a private build environment in !VENV! ...
    if not exist "!WORK!" mkdir "!WORK!"
    %PY% -m venv "!VENV!"
    if errorlevel 1 (
        echo  [X] Could not create the build environment.
        if not defined NOPAUSE pause
        exit /b 1
    )
) else (
    echo  [2/6] Re-using the build environment in !VENV!.
)

REM ------------------------------------------------------------------ 3/6
echo  [3/6] Installing the libraries - the slow part, 3 to 8 minutes the
echo        first time, seconds after that ...
"!VPY!" -m pip install --upgrade pip --disable-pip-version-check -q >nul 2>&1
"!VPY!" -m pip install -r requirements-lock.txt --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo  [X] Installing the libraries failed. Almost always one of:
    echo      - no internet, or a company proxy / firewall blocking pypi.org
    echo      - an unusual Python: install 3.12 from python.org, delete the
    echo        folder !VENV! and run this again
    echo.
    if not defined NOPAUSE pause
    exit /b 1
)
REM "call" first: cmd strips the quotes off a command that starts with one.
for /f "usebackq delims=" %%n in (`call "!VPY!" -c "import app_info; print(app_info.APP_NAME)"`) do set "APPNAME=%%n"
if not defined APPNAME set "APPNAME=QA Report Studio"
echo        Libraries ready.

REM ------------------------------------------------------------------ 4/6
echo  [4/6] Checking the app itself ...
"!VPY!" check_app.py
if errorlevel 1 (
    echo.
    echo  [X] The app's own check failed - see the message above. Nothing
    echo      was built, because the setup file would carry the same fault.
    if not defined NOPAUSE pause
    exit /b 1
)

REM ------------------------------------------------------------------ 5/6
echo  [5/6] Building the program folder - 3 to 10 minutes. Lots of
echo        scrolling text and a few WARNING lines are normal ...
if exist "!WORK!\dist" rmdir /s /q "!WORK!\dist"
if exist "!WORK!\build" rmdir /s /q "!WORK!\build"
if exist "build" rmdir /s /q "build"
if exist "!WORK!\dist" (
    echo  [X] An earlier build is still in use. Close QA Report Studio if it
    echo      is running from the build folder, then run this again.
    if not defined NOPAUSE pause
    exit /b 1
)
"!VPY!" -m PyInstaller --noconfirm --clean --distpath "!WORK!\dist" --workpath "!WORK!\build\app" qa_report_studio.spec
if errorlevel 1 (
    echo.
    echo  [X] The build failed. Scroll up to the FIRST line that says ERROR -
    echo      that is the real cause; everything after it is fallout.
    echo      "Access is denied" usually means antivirus was scanning a file:
    echo      just run build_exe.bat again.
    if not defined NOPAUSE pause
    exit /b 1
)
if not exist "!WORK!\dist\!APPNAME!\!APPNAME!.exe" (
    echo  [X] The build finished but no program was produced.
    if not defined NOPAUSE pause
    exit /b 1
)

REM ------------------------------------------------------------------ 6/6
echo  [6/6] Packing the program into the setup file ...
set "QARS_PAYLOAD=!WORK!\build\payload\payload.zip"
"!VPY!" make_payload.py --source "!WORK!\dist\!APPNAME!" --out "!QARS_PAYLOAD!"
if errorlevel 1 (
    echo  [X] Could not pack the program.
    if not defined NOPAUSE pause
    exit /b 1
)
"!VPY!" -m PyInstaller --noconfirm --clean --distpath "!WORK!\dist" --workpath "!WORK!\build\setup" installer.spec
if errorlevel 1 (
    echo  [X] Building the setup file failed - see the first ERROR above.
    if not defined NOPAUSE pause
    exit /b 1
)
if not exist "dist" mkdir "dist"
copy /y "!WORK!\dist\!APPNAME! Setup.exe" "dist\" >nul
set "SETUP=!SRC!\dist\!APPNAME! Setup.exe"
if not exist "!SETUP!" (
    echo  [X] The build reported success but the setup file is missing.
    if not defined NOPAUSE pause
    exit /b 1
)
for %%A in ("!SETUP!") do set "SZ=%%~zA"
set /a SZMB=!SZ!/1048576

echo.
echo ============================================================
echo    DONE
echo ============================================================
echo.
echo    The file to give to people:
echo       !SETUP!
echo    Size: !SZMB! MB
echo.
echo    What they do:
echo      1. Double-click it. A small window shows a progress bar
echo         while it installs into their own AppData folder.
echo         No administrator password is asked for.
echo      2. It adds a Desktop shortcut and opens the app.
echo      3. From then on they open it from that shortcut.
echo.
echo    Windows may show "Windows protected your PC" the first time
echo    a downloaded copy is opened: click "More info", then
echo    "Run anyway". It does that for any program that is not
echo    signed with a paid certificate.
echo.
if defined NOPAUSE exit /b 0
choice /c YN /m "    Show the file in Explorer now"
if not errorlevel 2 explorer /select,"!SETUP!"
echo.
pause
