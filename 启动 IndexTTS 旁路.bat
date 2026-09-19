@echo off
setlocal EnableExtensions
cd /d "%~dp0" || exit /b 1

set "SIDECAR_DIR=%CD%\tools\indextts_sidecar"
if not exist "%SIDECAR_DIR%\server.py" (
    echo IndexTTS sidecar is missing: %SIDECAR_DIR%
    pause
    exit /b 1
)

if not defined ZLY_AI_VIDEO_STUDIO_INDEXTTS_ROOT (
    set "ZLY_AI_VIDEO_STUDIO_INDEXTTS_ROOT=%CD%\..\整合包及模型\index-tts"
)

set "INDEXTTS_PYTHON="
if defined ZLY_AI_VIDEO_STUDIO_INDEXTTS_PYTHON set "INDEXTTS_PYTHON=%ZLY_AI_VIDEO_STUDIO_INDEXTTS_PYTHON%"
if not defined INDEXTTS_PYTHON if exist "%ZLY_AI_VIDEO_STUDIO_INDEXTTS_ROOT%\.venv\Scripts\python.exe" set "INDEXTTS_PYTHON=%ZLY_AI_VIDEO_STUDIO_INDEXTTS_ROOT%\.venv\Scripts\python.exe"
if not defined INDEXTTS_PYTHON if exist "%ZLY_AI_VIDEO_STUDIO_INDEXTTS_ROOT%\venv\Scripts\python.exe" set "INDEXTTS_PYTHON=%ZLY_AI_VIDEO_STUDIO_INDEXTTS_ROOT%\venv\Scripts\python.exe"

if not defined INDEXTTS_PYTHON (
    echo Set ZLY_AI_VIDEO_STUDIO_INDEXTTS_PYTHON to the IndexTTS venv python.exe
    echo Do not use the workbench FastAPI interpreter. See tools\indextts_sidecar\README.md
    pause
    exit /b 1
)

set "PYTHONPATH=%CD%\tools;%PYTHONPATH%"
echo Starting IndexTTS-2.5 sidecar on http://127.0.0.1:7866
echo Checkpoints: %ZLY_AI_VIDEO_STUDIO_INDEXTTS_ROOT%
"%INDEXTTS_PYTHON%" -m indextts_sidecar.server
if errorlevel 1 pause
exit /b %ERRORLEVEL%
