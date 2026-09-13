@echo off
setlocal EnableExtensions DisableDelayedExpansion
if "%~4"=="" exit /b 64
if not defined II_SYSTEM set "II_SYSTEM=C:\Program Files\Ingres\ingresWD"
set "PATH=%II_SYSTEM%\ingres\bin;%II_SYSTEM%\ingres\utility;%PATH%"
set "LIB=%II_SYSTEM%\ingres\lib;%LIB%"
set "INCLUDE=%II_SYSTEM%\ingres\files;%INCLUDE%"
set "II_W4GLAPPS_SYS=%II_SYSTEM%\ingres\w4glapps\"
set "LOG=%~4.log"
w4gldev backupapp in "%~1" "%~2" "%~4" -nowindows -c%~3 -xml -nreplace -f -TALL,logonly -L"%LOG%"
set "GORAK_IMPORT_EXIT=%ERRORLEVEL%"
if exist "%LOG%" type "%LOG%"
if not "%GORAK_IMPORT_EXIT%"=="0" exit /b %GORAK_IMPORT_EXIT%
if not exist "%LOG%" exit /b 1
findstr /I /C:"ERROR:" /C:"failed" "%LOG%" >nul
if not errorlevel 1 exit /b 1
echo GORAK_IMPORT_OK
exit /b 0
