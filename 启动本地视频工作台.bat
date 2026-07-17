@echo off
setlocal EnableExtensions

cd /d "%~dp0" || goto :path_error
for %%I in ("%CD%\..") do set "ROOT=%%~fI"

set "PYTHON_EXE="
for /d %%D in ("%ROOT%\*") do (
    if exist "%%~fD\comfyui-integrate-v1.3\comfyui-integrate\python310\python.exe" set "PYTHON_EXE=%%~fD\comfyui-integrate-v1.3\comfyui-integrate\python310\python.exe"
)

if not defined PYTHON_EXE goto :python_not_found

set "WEBUI_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":7865 .*LISTENING"') do set "WEBUI_PID=%%P"
if defined WEBUI_PID (
    start "" "http://127.0.0.1:7865/"
    echo Local Video Studio is already running on port 7865.
    exit /b 0
)

"%PYTHON_EXE%" "%~dp0local_video_studio.py"
if errorlevel 1 pause
exit /b %errorlevel%

:path_error
echo Cannot open the workspace directory.
pause
exit /b 1

:python_not_found
echo ComfyUI embedded Python was not found.
pause
exit /b 1
