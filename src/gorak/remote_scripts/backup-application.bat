@echo off
setlocal EnableExtensions DisableDelayedExpansion

if "%~2"=="" (
    >&2 echo Usage: %~nx0 EXPORT_DB EXPORT_APP
    exit /b 64
)

if not defined GORAK_ROOT (
    for %%I in ("%~dp0.") do set "GORAK_ROOT=%%~fI"
)

if not defined II_SYSTEM (
    set "II_SYSTEM=C:\Program Files\Ingres\ingresWD"
)

set "PATH=%II_SYSTEM%\ingres\bin;%II_SYSTEM%\ingres\utility;%PATH%"
set "LIB=%II_SYSTEM%\ingres\lib;%LIB%"
set "INCLUDE=%II_SYSTEM%\ingres\files;%INCLUDE%"
set "II_W4GLAPPS_SYS=%II_SYSTEM%\ingres\w4glapps\"

set "EXPORT_DB=%~1"
set "EXPORT_APP=%~2"

set "EXPORT_DIR=%GORAK_ROOT%\repos\%EXPORT_DB%\%EXPORT_APP%"
set "EXPORT_DIR=%EXPORT_DIR:::=\%"
set "EXPORT_DEST=%EXPORT_DIR%\%EXPORT_APP%.xml"

set "TEMP_DIR=%GORAK_ROOT%/temp"
if not exist "%TEMP_DIR%\" mkdir "%TEMP_DIR%"
if errorlevel 1 (
    >&2 echo Failed to create temp dir: "%TEMP_DIR%"
    exit /b 1
)

set "LOG=%TEMP_DIR%\gorak-export-%EXPORT_APP%-%RANDOM%.log"
set "FLAGS=-nowindows -xml -TALL,logonly -L%LOG%"

if not exist "%EXPORT_DIR%\" mkdir "%EXPORT_DIR%"
if errorlevel 1 (
    >&2 echo Failed to create export dir: "%EXPORT_DIR%"
    exit /b 1
)

w4gldev backupapp out "%EXPORT_DB%" "%EXPORT_APP%" "%EXPORT_DEST%" %FLAGS%
set "W4GL_EXIT=%ERRORLEVEL%"

if exist "%LOG%" (
    findstr /C:"ERROR:" "%LOG%"
)

if not "%W4GL_EXIT%"=="0" (
    >&2 echo w4gldev failed with exit code %W4GL_EXIT%
    >&2 echo Log: "%LOG%"
    exit /b %W4GL_EXIT%
)

if not exist "%EXPORT_DEST%" (
    >&2 echo Export did not create expected file: "%EXPORT_DEST%"
    >&2 echo Log: "%LOG%"
    exit /b 1
)

echo %EXPORT_DEST%
exit /b 0
