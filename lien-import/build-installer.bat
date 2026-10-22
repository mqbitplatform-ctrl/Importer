@echo off
setlocal
cd /d "%~dp0"
title Build the Lien Import installer

REM ==================================================================
REM  FOR THE DEVELOPER ONLY - end users never run this.
REM  Produces  dist\LienImport-Setup-<version>.exe : one file to send to
REM  the user. It bundles Python + the app, so the user's PC needs nothing.
REM
REM  Needs on THIS PC: Python 3.11+ and Inno Setup 6
REM    (winget install --id JRSoftware.InnoSetup -e)
REM ==================================================================

set "VERSION=1.0.0"
if not "%~1"=="" set "VERSION=%~1"
set "BV=%~dp0.build-venv"
set "PYI=%~dp0build\pyinstaller"

echo [1/3] Preparing the build environment ...
if not exist "%BV%\Scripts\python.exe" (
  python -m venv "%BV%" || goto fail
)
"%BV%\Scripts\python.exe" -m pip install --quiet --upgrade pip || goto fail
"%BV%\Scripts\python.exe" -m pip install --quiet "pyinstaller==6.22.3" "PyMySQL>=1.0.2" || goto fail

echo [2/3] Bundling the app (Python + Lien Import) ...
"%BV%\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed ^
  --name LienImport ^
  --icon "%~dp0packaging\lien-import.ico" ^
  --paths "%~dp0." ^
  --collect-submodules lien_import ^
  --distpath "%PYI%\dist" --workpath "%PYI%\work" --specpath "%PYI%" ^
  "%~dp0packaging\launcher.py" || goto fail

echo [3/3] Building the installer ...
set "ISCC="
for %%P in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe") do (
  if exist %%P set "ISCC=%%~P"
)
if not defined ISCC (
  echo.
  echo Inno Setup 6 was not found. Install it once with:
  echo     winget install --id JRSoftware.InnoSetup -e
  echo then run this file again.
  goto fail
)
"%ISCC%" /Q /DAppVersion=%VERSION% "%~dp0packaging\LienImport.iss" || goto fail

echo.
echo ==================================================================
echo   DONE:  dist\LienImport-Setup-%VERSION%.exe
echo   Send that one file to the user. They double-click it, click
echo   Install, and get a "Lien Import" icon on the desktop.
echo ==================================================================
echo.
pause
exit /b 0

:fail
echo.
echo BUILD FAILED - see the message above.
pause
exit /b 1
