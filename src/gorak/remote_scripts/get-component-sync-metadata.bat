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

set "SQL_FILE=%TEMP_DIR%\component-sync-metadata-%RANDOM%.sql"

(
    echo select case when app_current.entity_name is null
    echo             then app_folder.entity_name
    echo             else app_current.entity_name
    echo        end as application_name,
    echo        base.entity_name as component_name,
    echo        base.entity_type,
    echo        base.entity_id as base_entity_id,
    echo        ver.entity_id as version_entity_id,
    echo        ver.version_number,
    echo        c.alter_date,
    echo        c.alter_count,
    echo        c.last_altered_by,
    echo        c.current_make
    echo from ii_entities base
    echo left join ii_entities app_folder on base.folder_id = app_folder.entity_id
    echo left join ii_entities app_current on app_current.base_entity_id = app_folder.entity_id
    echo left join ii_applications a on a.entity_id = app_current.entity_id
    echo left join ii_entities ver on ver.base_entity_id = base.entity_id
    echo                          and ver.version_number = -1
    echo left join ii_components c on c.entity_id = ver.entity_id
    echo where base.base_entity_id = 0
    echo and base.folder_id != 0
    echo order by application_name, base.entity_name
    echo \p\g
) > "%SQL_FILE%"

sql "%DB_TARGET%" < "%SQL_FILE%"
set "SQL_EXIT=%ERRORLEVEL%"

if exist "%SQL_FILE%" del "%SQL_FILE%"

exit /b %SQL_EXIT%
