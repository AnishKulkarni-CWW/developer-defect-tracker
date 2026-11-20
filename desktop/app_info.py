"""
The desktop app's names, in one place.

Read by the launcher, the installer, both PyInstaller specs and the build
script, so renaming the program is one edit here. The window's title is the
page title in app.py (APP_TITLE there); keep the two the same.
"""

# What people see: the program folder, the shortcut, the .exe and the window.
APP_NAME = "QA Report Studio"

# The per-user data folder (%LOCALAPPDATA%\QAReportStudio) and the name of the
# lock that stops two copies running at once. No spaces, never translated.
APP_ID = "QAReportStudio"

TAGLINE = "Defects to better products"
VERSION = "1.0.0"

EXE_NAME = APP_NAME + ".exe"
SETUP_NAME = APP_NAME + " Setup"

# Ports on 127.0.0.1 only, so Windows Firewall never asks anything. The server
# moves to any free port if this one is taken. Deliberately not 8501 (every
# other Streamlit app, including the QA Hours Dashboard) and not the QA Hours
# Dashboard's lock port (8599), so both programs can be open at once.
PREFERRED_PORT = 8531
LOCK_PORT = 8631          # single-instance lock where there is no named mutex
