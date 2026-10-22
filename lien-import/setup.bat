@echo off
setlocal
cd /d "%~dp0"
title Lien Import - One-time setup

echo ==================================================================
echo   LIEN IMPORT - ONE-TIME SETUP
echo ==================================================================
echo.

REM --- 1. check Python -------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
  echo [X] Python is not installed, or not on the PATH.
  echo.
  echo     1. Go to https://www.python.org/downloads/
  echo     2. Download Python 3.11 or newer.
  echo     3. IMPORTANT: on the first install screen, tick
  echo        "Add python.exe to PATH".
  echo     4. Finish the install, then run this setup.bat again.
  echo.
  pause
  exit /b 1
)
for /f "delims=" %%v in ('python --version') do echo [OK] Found %%v

REM --- 2. create an isolated environment ----------------------------
if not exist ".venv\Scripts\python.exe" (
  echo [..] Creating a private Python environment ^(.venv^) ...
  python -m venv .venv
  if errorlevel 1 (
    echo [X] Could not create the environment. Contact the developer.
    pause
    exit /b 1
  )
)
echo [OK] Private environment ready.

REM --- 3. install the tool's requirements -------------------------
echo [..] Installing the required package ^(needs internet the first time^) ...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet "PyMySQL>=1.0.2"
if errorlevel 1 (
  echo [X] Could not install PyMySQL. Check the internet connection and retry.
  echo     If this PC uses a company proxy, ask IT for the pip proxy settings.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import pymysql" 2>nul
if errorlevel 1 (
  echo [X] PyMySQL did not import after install. Contact the developer.
  pause
  exit /b 1
)
echo [OK] PyMySQL installed.

REM --- 4. create the settings file -------------------------------
if not exist "config.json" (
  copy /y "config.example.json" "config.json" >nul
  echo [OK] Created config.json from the template.
) else (
  echo [OK] config.json already exists - leaving it as-is.
)

echo.
echo ==================================================================
echo   ALMOST DONE - fill in the database details
echo ==================================================================
echo.
echo   Notepad will now open config.json.
echo   In the "database" section replace every REPLACE_ME with the
echo   real value the developer / DBA gave you:
echo.
echo       host      - the database server address
echo       name      - the database (schema) name
echo       user      - the login name
echo       password  - the login password
echo.
echo   Save the file and close Notepad when done.
echo.
pause
start "" notepad "config.json"

echo.
echo ==================================================================
echo   SETUP COMPLETE
echo ==================================================================
echo   From now on, just double-click:
echo       lien-import-gui.bat   - window with buttons (easiest)
echo       lien-import.bat       - numbered text menu (all tools)
echo.
pause
