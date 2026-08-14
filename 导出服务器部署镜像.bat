@echo off
setlocal EnableExtensions

cd /d "%~dp0" || goto :path_error

set "ARCHIVE=%~dp0zly-ai-video-studio_latest.tar"
set "TEMP_ARCHIVE=%ARCHIVE%.tmp"

echo.
echo [1/2] Building zly-ai-video-studio:latest ...
docker compose --env-file .env.example build
if errorlevel 1 goto :build_error

echo.
echo [2/2] Exporting image archive ...
docker save --output "%TEMP_ARCHIVE%" zly-ai-video-studio:latest
if errorlevel 1 goto :export_error

move /y "%TEMP_ARCHIVE%" "%ARCHIVE%" >nul
if errorlevel 1 goto :replace_error

for %%I in ("%ARCHIVE%") do echo Done: %%~fI  ^(%%~zI bytes^)
echo Upload this file to the server packages directory, then run docker load -i.
pause
exit /b 0

:path_error
echo Cannot enter the script directory.
pause
exit /b 1

:build_error
echo Image build failed. The existing image archive was not changed.
pause
exit /b 1

:export_error
echo Image export failed. The existing image archive was not changed.
pause
exit /b 1

:replace_error
echo Image archive was built but could not replace the existing archive.
pause
exit /b 1
