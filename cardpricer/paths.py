"""Persistent data directory and shared constants."""

import os
import sys
from pathlib import Path

# ------------------------------------------------------------
# Persistent application data directory
# ------------------------------------------------------------
# IMPORTANT FOR PYINSTALLER:
# A --onefile executable is unpacked into a temporary directory each time it
# starts.  Never store the Scryfall bulk file, metadata, index, or search cache
# beside __file__ when running from a bundled executable, or the cache can
# disappear on every launch and the program will repeatedly rebuild/download
# the database.
#
# Keep all mutable database files in the user's persistent application-data
# directory instead.  This makes normal launches fast: metadata check -> load
# existing index -> self-test.
# ------------------------------------------------------------
def get_data_dir():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        root = Path(base) / "MTGCollectionBuyer"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "MTGCollectionBuyer"
    else:
        base = os.environ.get("XDG_DATA_HOME")
        root = (Path(base) if base else Path.home() / ".local" / "share") / "MTGCollectionBuyer"
    root.mkdir(parents=True, exist_ok=True)
    return root

DATA_DIR = get_data_dir()

BUNDLE_DIR = Path(__file__).resolve().parent

SETTINGS = DATA_DIR / "pricer_settings.json"

UA = {"User-Agent": "MTGCollectionBuyer/2.0 (personal collection pricing)"}
