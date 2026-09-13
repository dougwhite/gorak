@echo off
setlocal EnableExtensions DisableDelayedExpansion
if "%~4"=="" exit /b 64
if not defined II_SYSTEM set "II_SYSTEM=C:\Program Files\Ingres\ingresWD"
set "PATH=%II_SYSTEM%\ingres\bin;%II_SYSTEM%\ingres\utility;%PATH%"
set "LIB=%II_SYSTEM%\ingres\lib;%LIB%"
set "INCLUDE=%II_SYSTEM%\ingres\files;%INCLUDE%"
set "II_W4GLAPPS_SYS=%II_SYSTEM%\ingres\w4glapps\"
set "LOG=%~4.log"
set "CONFLICT=-nabort"
if "%~5"=="create" set "CONFLICT=-nabort"
set "COMPILE=-f"
if "%~5"=="create-empty" set "CONFLICT=-nabort"
if "%~5"=="create-empty" set "COMPILE="
set "COMPONENT=-c%~3"
if "%~3"=="-" set "COMPONENT="
if "%~3"=="-" set "COMPILE="
w4gldev backupapp in "%~1" "%~2" "%~4" -nowindows %COMPONENT% -xml %CONFLICT% %COMPILE% -TALL,logonly -L"%LOG%"
set "GORAK_IMPORT_EXIT=%ERRORLEVEL%"
if exist "%LOG%" type "%LOG%"
if not "%GORAK_IMPORT_EXIT%"=="0" exit /b %GORAK_IMPORT_EXIT%
if not exist "%LOG%" exit /b 1
findstr /I /C:"ERROR:" /C:" failed" "%LOG%" >nul
if not errorlevel 1 exit /b 1
if not "%~3"=="-" goto success
if "%~5"=="create-empty" goto success
set "LOG=%~4.compile.log"
w4gldev compileapp "%~1" "%~2" -nowindows -e -TALL,logonly -L"%LOG%"
set "GORAK_COMPILE_EXIT=%ERRORLEVEL%"
if exist "%LOG%" type "%LOG%"
if not "%GORAK_COMPILE_EXIT%"=="0" exit /b %GORAK_COMPILE_EXIT%
if not exist "%LOG%" exit /b 1
findstr /I /C:"ERROR:" /C:" failed" "%LOG%" >nul
if not errorlevel 1 exit /b 1
:success
echo GORAK_IMPORT_OK
exit /b 0
