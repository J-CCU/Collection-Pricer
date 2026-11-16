@echo off
rem Builds dist\CardPricer.exe (one file, no console window).
cd /d "%~dp0"
py -m pip install --upgrade pyinstaller requests openpyxl || goto :fail
py -m PyInstaller --noconfirm --clean CardPricer.spec || goto :fail
echo.
echo Built: %~dp0dist\CardPricer.exe
exit /b 0
:fail
echo Build failed.
exit /b 1
