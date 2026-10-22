@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Lien Import

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

if not exist "config.json" (
  echo config.json not found. Please run  setup.bat  first.
  echo.
  pause
  exit /b 1
)

:menu
cls
echo ==================================================================
echo   LIEN IMPORT
echo ==================================================================
echo.
echo   AUTOMATIC  ^(recommended - many files at once^)
echo     F  Open the INBOX folder   ^(drop files / whole folders / zips there^)
echo     A  Import EVERYTHING in the inbox
echo          - finds the source of each file by itself
echo          - never imports the same file or the same lien twice
echo          - moves finished files to  lien-data\processed
echo.
echo   ONE FILE AT A TIME
echo     1  Look at a data file            ^(list its columns^)
echo     2  Check a file BEFORE importing  ^(counts + report, no changes^)
echo     3  Import a file into the database
echo     4  Verify import counts
echo     5  Full statistics report
echo.
echo   FREE AMERICA TAX
echo     6  See how many liens match the FAT rules
echo     7  Create a FAT pull
echo     8  Show FAT pull history
echo.
echo     9  Test the database connection  ^(do this first if unsure^)
echo     L  Create a LOCAL practice database  ^(127.0.0.1 only^)
echo     0  Exit
echo.
set "CHOICE="
set /p "CHOICE=Type a number and press Enter: "

if /I "!CHOICE!"=="F" goto openinbox
if /I "!CHOICE!"=="A" goto autoimport
if /I "!CHOICE!"=="1" goto discover
if /I "!CHOICE!"=="2" goto preview
if /I "!CHOICE!"=="3" goto import
if /I "!CHOICE!"=="4" goto verify
if /I "!CHOICE!"=="5" goto analyze
if /I "!CHOICE!"=="6" goto fatanalyze
if /I "!CHOICE!"=="7" goto fatpull
if /I "!CHOICE!"=="8" goto fatstatus
if /I "!CHOICE!"=="9" goto dbcheck
if /I "!CHOICE!"=="L" goto setuplocal
if /I "!CHOICE!"=="0" exit /b 0
goto menu

REM ================================================================
:askfile
set "FILE="
echo.
echo Drag the data file ^(or its folder, or a .zip^) onto this window,
echo or type/paste the full path, then press Enter.
set /p "FILE=File: "
if defined FILE set "FILE=!FILE:"=!"
if not defined FILE (
  echo No file given.
  pause
  goto menu
)
if not exist "!FILE!" (
  echo Not found: !FILE!
  pause
  goto menu
)
goto :eof

:asksource
set "SRC="
echo.
echo Which SOURCE is this file from? ^(not Federal vs State - the tool
echo works that out for each lien on its own.^)
echo.
echo    1  ATT / ESS
echo         - the ATT-ESS archive / its CSV files
echo.
echo    2  TNU
echo         - Combined-Federal   AND   Combined-State   AND
echo           "TNU Starter Full List"  ^(all three are TNU^)
echo.
set /p "S=Type 1 or 2: "
if "!S!"=="1" set "SRC=ES"
if "!S!"=="2" set "SRC=TN"
if not defined SRC (
  echo Please type 1 or 2.
  goto asksource
)
goto :eof

REM ================================================================
:openinbox
echo.
"!PY!" -m lien_import auto-import --open-inbox
echo.
echo Copy the data files ^(or whole folders, or .zip files^) into that folder,
echo then choose  A  from the menu.
echo.
pause
goto menu

:autoimport
echo.
echo Allow duplicates?  Y = a lien that repeats in several files is kept as
echo separate rows.  Just press Enter for the normal way ^(each lien once^).
set "D="
set "DUPFLAG="
set /p "D=Allow duplicates? (Y / Enter = No): "
if /I "!D!"=="Y" set "DUPFLAG=--allow-duplicates"
echo.
echo STEP 1 of 2 - checking every file in the inbox ^(no changes yet^) ...
echo.
"!PY!" -m lien_import auto-import !DUPFLAG!
if errorlevel 3 (
  echo.
  echo Nothing to do. Use option  F  to open the inbox folder.
  pause
  goto menu
)
if errorlevel 1 (
  echo.
  echo The check failed - nothing was written. See the message above.
  pause
  goto menu
)
echo.
echo ------------------------------------------------------------------
echo Look at "would insert" for each source above.
echo   unrecognised     = the tool could not tell the source; that file
echo                      is NOT imported and goes to lien-data\failed
echo   already_imported = this exact file was imported before; skipped
echo If that looks right, type   IMPORT   to import every file.
echo Anything else cancels.
echo ------------------------------------------------------------------
set "OK="
set /p "OK=Type IMPORT to proceed: "
if /I not "!OK!"=="IMPORT" (
  echo Cancelled - nothing was written.
  pause
  goto menu
)
echo.
echo STEP 2 of 2 - importing file by file ...
echo.
"!PY!" -m lien_import auto-import --commit !DUPFLAG!
if errorlevel 1 (
  echo.
  echo ================================================================
  echo   SOME FILES FAILED - see the list above. Files that worked were
  echo   imported and moved to lien-data\processed. Failed files are in
  echo   lien-data\failed with a .reason.txt next to each one.
  echo   Fix the problem, put them back in the inbox, and run A again.
  echo ================================================================
) else (
  echo.
  echo All done. Finished files were moved to  lien-data\processed .
  echo Use option 4 ^(Verify^) to confirm the counts.
)
echo.
pause
goto menu

REM ================================================================
:discover
call :askfile
call :asksource
echo.
"!PY!" -m lien_import discover --input "!FILE!" --source !SRC!
echo.
pause
goto menu

:preview
call :askfile
call :asksource
echo.
echo Checking the file ^(no changes are made^) ...
echo.
"!PY!" -m lien_import preview --input "!FILE!" --source !SRC!
echo.
echo ^>^> A full report was saved in the  output  folder ^(newest sub-folder^).
echo ^>^> Review it before importing.
echo.
pause
goto menu

:import
call :askfile
call :asksource
echo.
echo STEP 1 of 2 - checking the file first ^(no changes yet^) ...
echo.
"!PY!" -m lien_import preview --input "!FILE!" --source !SRC!
echo.
echo ------------------------------------------------------------------
echo Look at "records that WOULD be inserted" above.
echo If that looks right, type   IMPORT   to write them to the database.
echo Anything else cancels.
echo ------------------------------------------------------------------
set "OK="
set /p "OK=Type IMPORT to proceed: "
if /I not "!OK!"=="IMPORT" (
  echo Cancelled - nothing was written.
  pause
  goto menu
)
echo.
echo STEP 2 of 2 - importing ...
echo.
"!PY!" -m lien_import import --input "!FILE!" --source !SRC! --commit
if errorlevel 1 (
  echo.
  echo ================================================================
  echo   IMPORT FAILED - nothing was written to the database.
  echo   Read the message just above for what to fix, then try again.
  echo   Tip: use option 9 first to test the database connection.
  echo ================================================================
) else (
  echo.
  echo Import finished. Use option 4 ^(Verify^) to confirm the counts.
)
echo.
pause
goto menu

:verify
call :asksource
echo.
"!PY!" -m lien_import verify --source !SRC!
echo.
pause
goto menu

:analyze
echo.
echo    1  Analyse a FILE   ^(before import^)
echo    2  Analyse the DATABASE  ^(everything already imported^)
set "A="
set /p "A=Type 1 or 2: "
if "!A!"=="1" (
  call :askfile
  call :asksource
  "!PY!" -m lien_import analyze --input "!FILE!" --source !SRC!
) else (
  "!PY!" -m lien_import analyze --db
)
echo.
pause
goto menu

REM ================================================================
:fatanalyze
echo.
"!PY!" -m lien_import fat-analyze
echo.
pause
goto menu

:fatpull
set "JOB="
echo.
set /p "JOB=Name this pull (e.g. FAT-2026-09): "
if not defined JOB (
  echo No name given.
  pause
  goto menu
)
set "COUNT="
set /p "COUNT=How many liens to pull (past pulls were 10000 to 14000): "
if not defined COUNT (
  echo No number given.
  pause
  goto menu
)
echo !COUNT!| findstr /r "^[1-9][0-9]*$" >nul
if errorlevel 1 (
  echo Please type digits only, e.g. 10000 - cancelled, nothing was written.
  pause
  goto menu
)
set "COUNTNUM=!COUNT!"
echo.
echo STEP 1 of 2 - preview ^(no changes^) ...
echo.
"!PY!" -m lien_import fat-pull --job "!JOB!" --limit !COUNTNUM!
echo.
echo ------------------------------------------------------------------
echo Each pulled lien gets a FREEAMTAX Case ID. These come from Logics -
echo type the FIRST Case ID Logics gave you for this pull. The tool will
echo refuse if any of the range is already used.
echo ------------------------------------------------------------------
set "CASEID="
set /p "CASEID=First Case ID from Logics: "
if not defined CASEID (
  echo No Case ID given - cancelled, nothing was written.
  pause
  goto menu
)
echo !CASEID!| findstr /r "^[1-9][0-9]*$" >nul
if errorlevel 1 (
  echo A Case ID is digits only, e.g. 98731 - cancelled, nothing was written.
  pause
  goto menu
)
set "CASENUM=!CASEID!"
echo.
echo If the numbers look right, type  PULL  to record the assignment
echo and create the CSV. Anything else cancels.
set "OK="
set /p "OK=Type PULL to proceed: "
if /I not "!OK!"=="PULL" (
  echo Cancelled - nothing was written.
  pause
  goto menu
)
echo.
"!PY!" -m lien_import fat-pull --job "!JOB!" --limit !COUNTNUM! --start-case-id !CASENUM! --commit
if errorlevel 1 (
  echo.
  echo FAT PULL FAILED - nothing was written. See the message above.
) else (
  echo.
  echo Done. The pull CSV is in the  output  folder ^(newest sub-folder^).
)
echo.
pause
goto menu

:fatstatus
echo.
"!PY!" -m lien_import fat-status
echo.
pause
goto menu

:dbcheck
echo.
"!PY!" -m lien_import db-check
echo.
pause
goto menu

:setuplocal
echo.
echo This creates a PRACTICE database on your own PC (127.0.0.1) using the
echo name in config.json, so you can try the tool without the real server.
echo It will NOT run against a remote / production server.
echo.
"!PY!" -m lien_import setup-local-db
echo.
pause
goto menu
