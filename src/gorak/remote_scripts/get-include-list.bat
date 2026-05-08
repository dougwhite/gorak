@echo off
setlocal EnableExtensions DisableDelayedExpansion

if "%~3"=="" (
    >&2 echo Usage: %~nx0 VNODE DATABASE APPLICATION
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
set "APPLICATION=%~3"
set "DB_TARGET=%VNODE%::%DATABASE%"

set "TEMP_DIR=%GORAK_ROOT%/temp"
if not exist "%TEMP_DIR%\" mkdir "%TEMP_DIR%"
if errorlevel 1 (
    >&2 echo Failed to create temp dir: "%TEMP_DIR%"
    exit /b 1
)

set "SQL_FILE=%TEMP_DIR%\include-list-%RANDOM%.sql"

(
    echo select e.entity_name as application_name, i.incl_name, i.incl_filename, i.incl_sequence
    echo from ii_incl_apps i
    echo left join ii_entities e on i.app_id = e.entity_id
    echo where i.incl_name != 'core'
    echo and lower(e.entity_name^) = lower('%APPLICATION%'^)
    echo order by i.incl_sequence
    echo \p\g
) > "%SQL_FILE%"

sql "%DB_TARGET%" < "%SQL_FILE%"
set "SQL_EXIT=%ERRORLEVEL%"

if exist "%SQL_FILE%" del "%SQL_FILE%"

exit /b %SQL_EXIT%
