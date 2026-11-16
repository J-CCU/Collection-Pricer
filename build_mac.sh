#!/bin/bash
# Builds dist/CardPricer.app and dist/CardPricer-mac.zip. Run on a Mac:
#   chmod +x build_mac.sh && ./build_mac.sh
# Needs Python 3.10+ from python.org (its Tk works on current macOS; the
# Apple-supplied /usr/bin/python3 Tk is too old). The app is built for the
# Mac's own chip (Apple Silicon or Intel).
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
"$PY" -c 'import tkinter, sys; assert sys.version_info >= (3, 10), sys.version' \
  || { echo "Install Python 3.10+ from https://www.python.org/downloads/macos/"; exit 1; }

"$PY" -m venv .venv-build
.venv-build/bin/pip install --upgrade pip pyinstaller requests openpyxl
.venv-build/bin/python -m PyInstaller --noconfirm --clean CardPricer.spec

# Zip with ditto so the bundle's symlinks and attributes survive.
rm -f dist/CardPricer-mac.zip
ditto -c -k --keepParent dist/CardPricer.app dist/CardPricer-mac.zip
echo
echo "Built: $(pwd)/dist/CardPricer.app"
echo "Share: $(pwd)/dist/CardPricer-mac.zip"
