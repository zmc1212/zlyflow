@echo off
setlocal
REM Copy beside the existing launcher on the REMOTE ComfyUI computer.
REM Stop the existing ComfyUI console after its queue is empty before running.
set "ROOT=%~dp0"
set "PYTHON_EXE=%ROOT%python310\python.exe"
set "LAUNCHER=%ROOT%bootstrap\launch_comfyui.py"
set "MANAGER_REQUIREMENTS=%ROOT%Comfyui\manager_requirements.txt"

if not exist "%PYTHON_EXE%" (
    echo Put this file beside the ORIGINAL ComfyUI launcher, next to python310 and bootstrap.
    pause
    exit /b 1
)
if not exist "%LAUNCHER%" (
    echo Missing bootstrap\launch_comfyui.py. No changes were made.
    pause
    exit /b 1
)
if not exist "%MANAGER_REQUIREMENTS%" (
    echo Missing Comfyui\manager_requirements.txt. No changes were made.
    echo Report this message instead of installing into another Python environment.
    pause
    exit /b 1
)

REM Do not install or launch while the existing server is listening.
"%PYTHON_EXE%" -s -c "import socket,sys; s=socket.socket(); s.settimeout(2); status=s.connect_ex(('127.0.0.1',8188)); s.close(); sys.exit(1 if status == 0 else 0)"
if errorlevel 1 (
    echo ComfyUI is still listening on port 8188.
    echo Wait for its queue to finish, close its original console, then run this file again.
    pause
    exit /b 1
)

echo Installing Manager requirements into the existing portable Python...
"%PYTHON_EXE%" -s -m pip install -r "%MANAGER_REQUIREMENTS%"
if errorlevel 1 (
    echo Manager dependency installation failed. Keep the error above for diagnosis.
    pause
    exit /b 1
)

echo Starting the EXISTING ComfyUI with Manager enabled...
"%PYTHON_EXE%" -s "%LAUNCHER%" --listen 0.0.0.0 --enable-manager %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" pause
exit /b %RESULT%
