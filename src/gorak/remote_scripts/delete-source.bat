@echo off
setlocal EnableExtensions DisableDelayedExpansion
if "%~4"=="" exit /b 64
if not defined II_SYSTEM set "II_SYSTEM=C:\Program Files\Ingres\ingresWD"
set "PATH=%II_SYSTEM%\ingres\bin;%II_SYSTEM%\ingres\utility;%PATH%"
set "LIB=%II_SYSTEM%\ingres\lib;%LIB%"
set "INCLUDE=%II_SYSTEM%\ingres\files;%INCLUDE%"
set "II_W4GLAPPS_SYS=%II_SYSTEM%\ingres\w4glapps\"
set "LOG=%~4"
set "COMPONENT=-c%~3"
if "%~3"=="-" set "COMPONENT="
call "%~dp0writer-command.bat" destroyapp "%~1" "%~2" %COMPONENT% -nowindows -TALL,logonly -L"%LOG%"
set "GORAK_DELETE_EXIT=%ERRORLEVEL%"
if exist "%LOG%" type "%LOG%"
if not "%GORAK_DELETE_EXIT%"=="0" exit /b %GORAK_DELETE_EXIT%
if not exist "%LOG%" exit /b 1
echo GORAK_DELETE_OK
exit /b 0
