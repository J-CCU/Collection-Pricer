# PyInstaller build for Windows (one CardPricer.exe) and macOS (CardPricer.app).
#   Windows:  build_windows.bat
#   macOS:    ./build_mac.sh
# PyInstaller can't cross-build: the .exe must be built on Windows and the
# .app on a Mac. Card data and settings are never bundled; they live in the
# user's data folder (paths.py), so rebuilding the app keeps them.
import sys

APP_NAME = "CardPricer"
VERSION = "3.0.0"

a = Analysis(
    ["run_pricer.py"],
    pathex=["."],
    hiddenimports=["openpyxl"],  # imported inside write_xlsx
    excludes=["numpy", "pandas", "matplotlib", "scipy", "PIL", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # A .app has to be a folder build; the bundle wraps it into one icon.
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP_NAME,
              console=False, upx=False, argv_emulation=False)
    coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, upx=False)
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        bundle_identifier="com.cardpricer.app",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "Card Pricer",
            "CFBundleShortVersionString": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=APP_NAME,
              console=False, upx=False)
