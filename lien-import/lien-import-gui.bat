@echo off
setlocal
cd /d "%~dp0"

REM Prefer the private environment made by setup.bat; pythonw = no console window.
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m lien_import.gui
  exit /b 0
)
if exist ".venv\Scripts\python.exe" (
  start "" ".venv\Scripts\python.exe" -m lien_import.gui
  exit /b 0
)

where pythonw >nul 2>&1
if not errorlevel 1 (
  start "" pythonw -m lien_import.gui
  exit /b 0
)

where python >nul 2>&1
if errorlevel 1 (
  echo Python was not found. Please run  setup.bat  first.
  pause
  exit /b 1
)
python -m lien_import.gui
if errorlevel 1 pause
