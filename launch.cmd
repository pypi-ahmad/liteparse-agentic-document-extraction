@echo off
REM Frees the fixed app port (see scripts\stop-port-process.ps1 for exactly
REM which process that can kill), then runs the app without re-syncing
REM dependencies (--no-sync) so a double-click launch stays fast; run
REM `uv sync` yourself after changing dependencies.
setlocal

set "LITEPARSE_APP_PORT=9578"
set "PYTHONUNBUFFERED=1"
set "STREAMLIT_LOGGER_LEVEL=info"
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-port-process.ps1" -Port %LITEPARSE_APP_PORT% -ProjectRoot "%~dp0"
if errorlevel 1 (
    echo Could not release port %LITEPARSE_APP_PORT%.
    pause
    endlocal & exit /b 1
)

echo Starting LiteParse app at http://127.0.0.1:%LITEPARSE_APP_PORT% ...
echo Live logs appear below. Press Ctrl+C to stop the app.
uv run --no-sync liteparse-ade
set "LITEPARSE_EXIT_CODE=%ERRORLEVEL%"

echo.
echo LiteParse app exited with code %LITEPARSE_EXIT_CODE%.
pause

endlocal & exit /b %LITEPARSE_EXIT_CODE%
