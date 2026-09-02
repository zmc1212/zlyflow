@echo off
setlocal EnableExtensions

cd /d "%~dp0" || goto :path_error
for %%I in ("%CD%\..") do set "ROOT=%%~fI"
set "PYTHON_EXE="
for /d %%D in ("%ROOT%\*") do (
    if exist "%%~fD\comfyui-integrate-v1.3\comfyui-integrate\python310\python.exe" set "PYTHON_EXE=%%~fD\comfyui-integrate-v1.3\comfyui-integrate\python310\python.exe"
)
if not defined PYTHON_EXE goto :python_not_found

"%PYTHON_EXE%" -c "import ctypes; k=ctypes.windll.kernel32; h=k.GetStdHandle(-10); m=ctypes.c_uint(); k.GetConsoleMode(h, ctypes.byref(m)); k.SetConsoleMode(h, (m.value|0x80)&~0x40)"

"%PYTHON_EXE%" -c "import qiniu" >nul 2>nul
if errorlevel 1 (
    echo Installing the Qiniu SDK required for cloud media storage...
    "%PYTHON_EXE%" -m pip install qiniu==7.16.0
    if errorlevel 1 goto :qiniu_install_error
)

"%PYTHON_EXE%" -c "import watchfiles" >nul 2>nul
if errorlevel 1 (
    echo Installing watchfiles for local backend reload...
    "%PYTHON_EXE%" -m pip install "watchfiles>=0.21,<2"
)

"%PYTHON_EXE%" -c "import pymysql" >nul 2>nul
if errorlevel 1 (
    echo Installing backend dependencies required for MySQL...
    "%PYTHON_EXE%" -m pip install -r "%CD%\backend\requirements.txt"
    if errorlevel 1 goto :requirements_install_error
)

if not defined ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY (
    "%PYTHON_EXE%" "%CD%\backend\app\local_credential_key.py" "%CD%\data\credential.key" >nul
    if errorlevel 1 goto :credential_key_error
    set /p "ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY=" < "%CD%\data\credential.key"
)
if not defined ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY goto :credential_key_error

set "WEBUI_SCHEME=http"
set "SSL_ARGS="
if defined ZLY_AI_VIDEO_STUDIO_SSL_CERTFILE (
    if not defined ZLY_AI_VIDEO_STUDIO_SSL_KEYFILE goto :ssl_config_error
    set "WEBUI_SCHEME=https"
    set "ZLY_AI_VIDEO_STUDIO_SECURE_COOKIES=true"
    set SSL_ARGS=--ssl-certfile "%ZLY_AI_VIDEO_STUDIO_SSL_CERTFILE%" --ssl-keyfile "%ZLY_AI_VIDEO_STUDIO_SSL_KEYFILE%"
)

where pnpm >nul 2>nul || goto :pnpm_not_found

set "WEBUI_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":7865 .*LISTENING"') do set "WEBUI_PID=%%P"
if defined WEBUI_PID (
    powershell -NoProfile -Command "$process = Get-CimInstance Win32_Process -Filter 'ProcessId=%WEBUI_PID%'; if ($process.CommandLine -match '(?i)(backend\.app\.main:app|backend\.dev_reloader)') { exit 0 }; exit 1"
    if not errorlevel 1 (
        powershell -NoProfile -Command "try { $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 '%WEBUI_SCHEME%://127.0.0.1:7865/api/health'; if ($response.StatusCode -eq 200) { exit 0 } } catch {}; exit 1"
        if not errorlevel 1 (
            set "BACKEND_ALREADY_RUNNING=1"
            goto :ensure_vite
        )
        echo Existing workbench on port 7865 is not responding. Restarting it.
        taskkill /F /T /PID %WEBUI_PID% >nul 2>nul
        timeout /t 1 /nobreak >nul
        set "WEBUI_PID="
        goto :port_cleared
    )
    powershell -NoProfile -Command "$process = Get-CimInstance Win32_Process -Filter 'ProcessId=%WEBUI_PID%'; if ($process.CommandLine -match '(?i)local_video_studio\.py') { Stop-Process -Id %WEBUI_PID% -Force; exit 0 }; exit 1"
    if not errorlevel 1 (
        echo Closed the legacy Gradio service on port 7865.
        timeout /t 1 /nobreak >nul
        set "WEBUI_PID="
    ) else (
        echo Port 7865 is already in use by another application. Close it, then start ZLY AI Video Studio again.
        pause
        exit /b 1
    )
)
:port_cleared

:ensure_vite
powershell -NoProfile -Command "$conn = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if (-not $conn) { exit 2 }; $process = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $conn.OwningProcess); if ($process.CommandLine -match '(?i)(vite|pnpm|node)') { exit 0 }; exit 1"
if errorlevel 2 goto :start_vite
if errorlevel 1 goto :vite_port_in_use
goto :open_browser

:start_vite
start "ZLY AI Video Studio Vite" /d "%CD%\frontend" cmd.exe /d /k "pnpm dev -- --host 127.0.0.1 --port 5173 --strictPort"

powershell -NoProfile -Command "$deadline = [DateTime]::UtcNow.AddSeconds(10); do { if (Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1) { exit 0 }; Start-Sleep -Milliseconds 250 } while ([DateTime]::UtcNow -lt $deadline); exit 1"
if errorlevel 1 goto :vite_start_failed
for /f %%P in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort 5173 -State Listen | Select-Object -First 1 -ExpandProperty OwningProcess)"') do set "VITE_LISTENING_PID=%%P"

:open_browser
start "" "%WEBUI_SCHEME%://127.0.0.1:5173/"
if defined BACKEND_ALREADY_RUNNING (
    echo FastAPI is already running on port 7865. Opened the Vite workbench at 5173.
    exit /b 0
)

:vite_ready
title ZLY AI Video Studio
set "PYTHONUNBUFFERED=1"
"%PYTHON_EXE%" "%CD%\backend\dev_reloader.py" --host 0.0.0.0 --port 7865 %SSL_ARGS%
set "WEBUI_EXIT_CODE=%errorlevel%"
if defined VITE_LISTENING_PID taskkill /pid %VITE_LISTENING_PID% /t /f >nul 2>nul

if not "%WEBUI_EXIT_CODE%"=="0" pause
exit /b %WEBUI_EXIT_CODE%

:path_error
echo Cannot open the workspace directory.
pause
exit /b 1

:python_not_found
echo ComfyUI embedded Python was not found.
pause
exit /b 1

:pnpm_not_found
echo pnpm was not found. Install Node.js and pnpm, then run: pnpm --dir frontend install
pause
exit /b 1

:vite_port_in_use
echo Port 5173 is already in use by another application. Close it, then start ZLY AI Video Studio again.
pause
exit /b 1

:vite_start_failed
echo Vite did not start on port 5173. Check the terminal output, then run: pnpm --dir frontend install
pause
exit /b 1

:ssl_config_error
echo ZLY_AI_VIDEO_STUDIO_SSL_CERTFILE is set but ZLY_AI_VIDEO_STUDIO_SSL_KEYFILE is missing.
pause
exit /b 1

:credential_key_error
echo The local credential key could not be loaded or created.
pause
exit /b 1

:qiniu_install_error
echo Qiniu SDK installation failed. Check the network or install qiniu==7.16.0 with the embedded Python, then retry.
pause
exit /b 1

:requirements_install_error
echo Backend dependency installation failed. Check the network or run: pip install -r backend\requirements.txt
pause
exit /b 1
