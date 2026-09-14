@echo off
setlocal EnableExtensions DisableDelayedExpansion
if not defined GORAK_WRITER_DATABASE goto ordinary
if not defined GORAK_WRITER_ENCODING exit /b 64
python "%~dp0gorak-writer.pyz" --database "%GORAK_WRITER_DATABASE%" --encoding "%GORAK_WRITER_ENCODING%" -- %*
exit /b %ERRORLEVEL%
:ordinary
w4gldev %*
exit /b %ERRORLEVEL%
