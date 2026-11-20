# -*- mode: python ; coding: utf-8 -*-
"""
Builds "QA Report Studio Setup.exe" - the one file you send to people.

Run build_exe.bat rather than this directly: the payload it carries
(build/payload/payload.zip) is made by the earlier stages of that script.

The setup program uses only Python's standard library, so the .exe is a few MB
of bootloader plus the payload. Everything heavy is inside payload.zip, which
is unpacked once at install time and never again.

console=True on purpose: a setup that shows a progress bar for half a minute
is reassuring; one that shows nothing looks stuck. The app it installs has no
console window at all.
"""

import os
import sys

HERE = os.path.abspath(SPECPATH)
sys.path.insert(0, HERE)
import app_info                             # noqa: E402

payload = (os.environ.get("QARS_PAYLOAD", "").strip()
           or os.path.join(HERE, "build", "payload", "payload.zip"))
if not os.path.isfile(payload):
    raise SystemExit("installer.spec: build/payload/payload.zip is missing.\n"
                     "Run build_exe.bat, which builds the program folder and zips it first.")
print(f"[installer] payload: {os.path.getsize(payload) / 1e6:.1f} MB")

icon_file = os.path.join(HERE, "icon.ico")
icon_file = icon_file if os.path.isfile(icon_file) else None

a = Analysis(
    [os.path.join(HERE, "installer.py")],
    pathex=[HERE],
    binaries=[],
    datas=[(payload, ".")],
    hiddenimports=["app_info"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "_tkinter", "numpy", "pandas", "matplotlib", "PIL", "streamlit",
              "pyarrow", "altair", "reportlab", "openpyxl", "pptx", "lxml", "IPython",
              "pytest", "setuptools", "pip", "qars"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=app_info.SETUP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,
    uac_uiaccess=False,
    icon=icon_file,
)
