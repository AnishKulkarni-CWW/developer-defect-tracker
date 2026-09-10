#!/usr/bin/env bash
# QA Report Studio - macOS / Linux launcher
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Install Python 3.10 or newer and try again."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating a private environment (one time only)..."
  python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "Starting QA Report Studio..."
streamlit run app.py
