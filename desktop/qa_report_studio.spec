# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller recipe for the QA Report Studio PROGRAM FOLDER.

Run build_exe.bat (in the folder above) rather than this directly. It runs
three stages, all from this desktop folder:

    1. this spec          ->  dist/QA Report Studio/           the program folder
    2. make_payload.py    ->  build/payload/payload.zip        that folder, zipped
    3. installer.spec     ->  dist/QA Report Studio Setup.exe  <-- the file you send

The setup file unpacks the folder once into the user's own AppData. Every start
after that is folder speed — about a second — because nothing is left to
extract. (A one-file app would unpack ~400 MB to a temp folder on every start.)

--------------------------------------------------------------------------
WHAT GOES IN
--------------------------------------------------------------------------
  * app.py — as DATA: Streamlit runs it by file path, not as an import;
  * the qars package — compiled in, with every library it imports;
  * qars/library — the reports and sheets the app ships with (the seed of each
    user's own library, see qars/desktop.py);
  * .streamlit/config.toml — the theme. NEVER secrets.toml: a GitHub token on
    the build machine must not travel inside a file you hand to other people;
  * desktop/icon.png and icon.ico — the window, shortcut and .exe icon.

--------------------------------------------------------------------------
WHAT IS KEPT OUT
--------------------------------------------------------------------------
  * Tcl/Tk. tkinter is the only thing that pulls it in, and it is what caused
    "Failed to load Tcl DLL" errors in packaged apps. The start-up screen is a
    plain HTML page in the app window, so no GUI toolkit is needed at all.
  * UPX compression: a well-known trigger for antivirus false positives.
  * pydeck (maps) and the parts of Arrow the app never touches.
"""

import os
import sys
import time

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

# ==========================================================================
# BUILD OPTIONS
# ==========================================================================
# False = no console window. Set True for one build to watch a start-up error
# live instead of reading %LOCALAPPDATA%\QAReportStudio\launcher.log.
CONSOLE = False

HERE = os.path.abspath(SPECPATH)            # desktop/
ROOT = os.path.dirname(HERE)                # the repository: app.py, qars/
sys.path.insert(0, HERE)
import app_info                             # noqa: E402

datas = []
binaries = []
hiddenimports = []


def add_all(package, **kwargs):
    global datas, binaries, hiddenimports
    try:
        d, b, h = collect_all(package, **kwargs)
        datas += d
        binaries += b
        hiddenimports += h
        print(f"[spec] collected {package}: {len(d)} data, {len(b)} binaries, {len(h)} modules")
    except Exception as exc:
        print(f"[spec] SKIP collect_all({package}): {exc}")


def add_submodules(package):
    global hiddenimports
    try:
        mods = collect_submodules(package)
        hiddenimports += mods
        print(f"[spec] submodules of {package}: {len(mods)}")
    except Exception as exc:
        print(f"[spec] SKIP collect_submodules({package}): {exc}")


def add_metadata(dist):
    global datas
    try:
        datas += copy_metadata(dist)
    except Exception:
        print(f"[spec] SKIP copy_metadata({dist}) - not installed")


# --------------------------------------------------------------------------
# 1. Our own files
# --------------------------------------------------------------------------
datas += [(os.path.join(ROOT, "app.py"), ".")]

# The theme only. secrets.toml is excluded by construction: only this one
# named file is ever copied from .streamlit/.
config_toml = os.path.join(ROOT, ".streamlit", "config.toml")
if os.path.isfile(config_toml):
    datas += [(config_toml, ".streamlit")]

for icon in ("icon.png", "icon.ico"):
    path = os.path.join(HERE, icon)
    if os.path.isfile(path):
        datas += [(path, "desktop")]

# The report library: index.json, aliases.json if any, and every report and
# sheet it lists. Temporary and hidden files are left behind.
LIB = os.path.join(ROOT, "qars", "library")
lib_files = 0
for folder, _dirs, files in os.walk(LIB):
    for name in files:
        if name.startswith(".") or name.endswith((".tmp", ".probe", ".part")):
            continue
        if not name.lower().endswith((".json", ".xlsx", ".xlsm", ".xls", ".csv", ".pptx")):
            continue
        rel = os.path.relpath(folder, ROOT)
        datas.append((os.path.join(folder, name), rel))
        lib_files += 1
print(f"[spec] report library: {lib_files} file(s)")

# The qars package is imported by app.py at run time, which PyInstaller cannot
# see (app.py is data), so every module is named here. Analysing them also
# brings in everything they import: pandas, openpyxl, python-pptx, reportlab,
# matplotlib.
qars_modules = sorted(
    "qars." + name[:-3] for name in os.listdir(os.path.join(ROOT, "qars"))
    if name.endswith(".py") and name != "__init__.py")
hiddenimports += ["qars"] + qars_modules
print(f"[spec] qars modules: {', '.join(m.split('.')[1] for m in qars_modules)}")

# --------------------------------------------------------------------------
# 2. Package metadata (read with importlib.metadata at run time)
# --------------------------------------------------------------------------
for dist in ["streamlit", "altair", "pandas", "numpy", "pyarrow", "matplotlib", "pillow",
             "openpyxl", "python-pptx", "reportlab", "XlsxWriter", "lxml", "narwhals",
             "click", "protobuf", "packaging", "typing_extensions", "starlette", "uvicorn",
             "anyio", "websockets", "python-multipart", "itsdangerous", "watchdog",
             "requests", "jsonschema", "jinja2", "fonttools"]:
    add_metadata(dist)

# --------------------------------------------------------------------------
# 3. Packages that load parts of themselves by name
# --------------------------------------------------------------------------
# include_py_files=False: the modules are compiled into the archive anyway; a
# second copy of every .py file as data would add thousands of files on disk.
for pkg in ["streamlit", "altair", "reportlab"]:
    add_all(pkg, include_py_files=False)
for pkg in ["uvicorn", "starlette", "anyio", "websockets", "h11", "python_multipart",
            "itsdangerous"]:
    add_submodules(pkg)
try:
    datas += collect_data_files("pptx")          # its default templates
    print("[spec] collected python-pptx templates")
except Exception as exc:
    print(f"[spec] SKIP pptx templates: {exc}")

# --------------------------------------------------------------------------
# 4. Imported by string at run time
# --------------------------------------------------------------------------
hiddenimports += [
    "app_info", "check_app",
    "streamlit.web.cli",
    "streamlit.runtime.scriptrunner.magic_funcs",
    "openpyxl", "openpyxl.cell._writer", "et_xmlfile",
    "pptx", "lxml.etree", "lxml._elementpath", "xlsxwriter",
    # pyarrow is required: st.dataframe fails without it.
    "pyarrow", "pyarrow.lib", "pyarrow.vendored.version",
    "matplotlib", "matplotlib.backends.backend_agg",
    "PIL", "PIL.Image",
    "reportlab.pdfbase._fontdata", "reportlab.rl_settings",
    "multipart", "python_multipart",
    "importlib.metadata", "encodings.idna",
]

# --------------------------------------------------------------------------
# 5. Left out on purpose
# --------------------------------------------------------------------------
excludes = [
    "tkinter", "_tkinter", "Tkinter", "tkinter.ttk", "PIL.ImageTk",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
    "pydeck", "plotly", "bokeh",
    "IPython", "jupyter", "notebook", "nbconvert", "nbformat", "ipykernel",
    "pytest", "sphinx",
    "matplotlib.tests", "numpy.tests", "pandas.tests", "pyarrow.tests", "PIL.tests",
    "xlrd",
]

a = Analysis(
    [os.path.join(HERE, "run_app.py")],
    pathex=[HERE, ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={"matplotlib": {"backends": "Agg"}},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# --------------------------------------------------------------------------
# 6. Drop files that only matter when compiling against a package
# --------------------------------------------------------------------------
_JUNK_SUFFIXES = (".lib", ".a", ".h", ".hpp", ".pyx", ".pxd", ".pxi",
                  ".c", ".cc", ".cpp", ".cmake", ".pc", ".exp", ".map")
# streamlit/.agents holds templates for the `streamlit skills` command, never
# used by `streamlit run` - and the deepest paths in the whole program.
_JUNK_PARTS = ("/include/", "/includes/", "/tests/", "/test/",
               "/sample_data/", "/__pycache__/", "/streamlit/.agents/")


def _is_junk(dest):
    norm = "/" + dest.replace("\\", "/").strip("/") + "/"
    if any(part in norm for part in _JUNK_PARTS):
        return True
    return dest.lower().endswith(_JUNK_SUFFIXES)


_before = len(a.datas)
a.datas = [entry for entry in a.datas if not _is_junk(entry[0])]
print(f"[spec] pruned {_before - len(a.datas)} build-only files")

# --------------------------------------------------------------------------
# 6b. The parts of Arrow the app never loads
# --------------------------------------------------------------------------
# pyarrow cannot go (st.dataframe needs it) but ships the whole Arrow C++
# stack. Its unused Python extension MODULES are dropped. Its shared LIBRARIES
# are kept, except Flight and parquet encryption: pyarrow's core module links
# against the others, and without them "import pyarrow" itself fails — which
# no test that only blocks imports can reveal.
_ARROW_UNUSED_MODULES = {
    "_flight", "_dataset", "_dataset_orc", "_dataset_parquet",
    "_dataset_parquet_encryption", "_acero", "_substrait", "_orc", "_csv",
    "_json", "_feather", "_fs", "_s3fs", "_hdfs", "_gcsfs", "_azurefs",
    "_parquet", "_parquet_encryption", "_pyarrow_cpp_tests",
}
_ARROW_UNUSED_LIBS = {"arrow_flight", "arrow_python_flight", "arrow_python_parquet_encryption"}


def _is_unused_arrow(entry):
    dest = entry[0].replace("\\", "/")
    source = str(entry[1]).replace("\\", "/") if len(entry) > 1 else ""
    if "pyarrow" not in dest and "pyarrow" not in source:
        return False
    name = os.path.basename(dest)
    lower = name.lower()
    stem = lower.split(".", 1)[0]
    is_module = lower.endswith(".pyd") or ".cpython-" in lower or name.startswith("_")
    if is_module:
        return stem in _ARROW_UNUSED_MODULES
    if lower.endswith((".dll", ".dylib")) or ".so" in lower:
        if stem.startswith("lib"):
            stem = stem[3:]
        return stem in _ARROW_UNUSED_LIBS
    return False


for _attr in ("binaries", "datas"):
    _items = getattr(a, _attr)
    _kept = [e for e in _items if not _is_unused_arrow(e)]
    if len(_kept) != len(_items):
        print(f"[spec] dropped {len(_items) - len(_kept)} unused Arrow files from {_attr}")
    setattr(a, _attr, _kept)

# Nothing from the build machine's .streamlit folder except the theme.
for _attr in ("datas", "binaries"):
    for _entry in getattr(a, _attr):
        if "secrets.toml" in _entry[0].replace("\\", "/"):
            raise SystemExit("[spec] refusing to bundle a secrets.toml - remove it from the build")

pyz = PYZ(a.pure)

# --------------------------------------------------------------------------
# 7. Windows file properties (right-click the .exe -> Properties -> Details)
# --------------------------------------------------------------------------
version_file = None
if sys.platform.startswith("win"):
    parts = (app_info.VERSION.split(".") + ["0", "0", "0", "0"])[:4]
    nums = ", ".join(str(int(p)) if p.isdigit() else "0" for p in parts)
    dotted = ".".join(str(int(p)) if p.isdigit() else "0" for p in parts)
    version_file = os.path.join(workpath, "file_version_info.txt")
    with open(version_file, "w", encoding="utf-8") as fh:
        fh.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({nums}), prodvers=({nums}), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'QA team'),
      StringStruct('FileDescription', '{app_info.APP_NAME}'),
      StringStruct('FileVersion', '{dotted}'),
      StringStruct('InternalName', '{app_info.APP_ID}'),
      StringStruct('OriginalFilename', '{app_info.EXE_NAME}'),
      StringStruct('ProductName', '{app_info.APP_NAME}'),
      StringStruct('ProductVersion', '{dotted}'),
      StringStruct('LegalCopyright', 'Copyright {time.strftime("%Y")}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""")

icon_file = os.path.join(HERE, "icon.ico")
icon_file = icon_file if os.path.isfile(icon_file) else None

# uac_admin=False -> an "asInvoker" manifest: Windows never asks for an
# administrator password. With the server on 127.0.0.1 there is no firewall
# prompt either, so a standard user account sees no prompt of any kind.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_info.APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,
    uac_uiaccess=False,
    icon=icon_file,
    version=version_file,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=app_info.APP_NAME,
)
