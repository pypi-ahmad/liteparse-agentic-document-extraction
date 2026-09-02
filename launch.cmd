@echo off
setlocal

set "LITEPARSE_APP_PORT=9578"
cd /d "%~dp0"

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%LITEPARSE_APP_PORT% .*LISTENING"') do (
    echo Stopping process %%P on port %LITEPARSE_APP_PORT%...
    taskkill /PID %%P /F >nul 2>&1
)

echo Starting LiteParse app at http://127.0.0.1:%LITEPARSE_APP_PORT% ...
uv run python asgi_app.py

endlocal
