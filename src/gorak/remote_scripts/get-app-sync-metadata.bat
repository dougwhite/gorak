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

set "TEMP_DIR=%GORAK_ROOT%/temp"
if not exist "%TEMP_DIR%\" mkdir "%TEMP_DIR%"
if errorlevel 1 (
    >&2 echo Failed to create temp dir: "%TEMP_DIR%"
    exit /b 1
)

set "SQL_FILE=%TEMP_DIR%\app-sync-metadata-%RANDOM%.sql"

(
    echo select e.entity_name as application_name, a.entity_id, a.alter_date, a.alter_count
    echo from ii_applications a join ii_entities e on a.entity_id=e.entity_id
    echo order by e.entity_name
    echo \p\g
) > "%SQL_FILE%"

sql "%DB_TARGET%" < "%SQL_FILE%"
set "SQL_EXIT=%ERRORLEVEL%"

if exist "%SQL_FILE%" del "%SQL_FILE%"

exit /b %SQL_EXIT%
