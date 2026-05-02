@echo off
setlocal EnableExtensions DisableDelayedExpansion

if "%~2"=="" (
    >&2 echo Usage: %~nx0 VNODE DATABASE
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

set "VNODE=%~1"
set "DATABASE=%~2"
set "DB_TARGET=%VNODE%::%DATABASE%"
set "SQL_FILE=%GORAK_ROOT%\applist.sql"

if not exist "%SQL_FILE%" (
    >&2 echo Missing SQL file: "%SQL_FILE%"
    exit /b 1
)

sql "%DB_TARGET%" < "%SQL_FILE%"
exit /b %ERRORLEVEL%
