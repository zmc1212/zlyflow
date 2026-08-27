@echo off
setlocal EnableExtensions
title Close ZLY AI Video Studio
cd /d "%~dp0" || goto :path_error

echo Closing ZLY AI Video Studio frontend (5173) and backend (7865).
echo ComfyUI on 8188 will not be stopped.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$lines = Get-Content -LiteralPath '%~f0'; $i = ($lines | Select-String -Pattern '^___PS1___$' | Select-Object -First 1).LineNumber; if (-not $i) { throw 'embedded PowerShell marker missing' }; Invoke-Expression (($lines | Select-Object -Skip $i) -join [Environment]::NewLine)"
set "STOP_EXIT=%ERRORLEVEL%"

echo.
if "%STOP_EXIT%"=="0" (
    echo ZLY AI Video Studio frontend and backend ports are closed.
) else (
    echo Some workbench ports are still in use. See the messages above.
)
echo.
pause
exit /b %STOP_EXIT%

:path_error
echo Cannot open the workspace directory.
pause
exit /b 1

___PS1___
$ErrorActionPreference = "Continue"

function Get-ListenPids([int]$Port) {
    $ids = New-Object System.Collections.Generic.List[int]
    try {
        foreach ($connection in (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
            if ($connection.OwningProcess -gt 4) {
                $ids.Add([int]$connection.OwningProcess)
            }
        }
    } catch {}
    if ($ids.Count -eq 0) {
        foreach ($line in (netstat -ano | Select-String -Pattern (":{0}\s+\S+\s+LISTENING\s+\d+$" -f $Port))) {
            if ($line.Line -match "(\d+)\s*$") {
                $pidValue = [int]$Matches[1]
                if ($pidValue -gt 4) {
                    $ids.Add($pidValue)
                }
            }
        }
    }
    return @($ids | Select-Object -Unique)
}

function Get-CommandLine([int]$ProcessId) {
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $ProcessId) -ErrorAction SilentlyContinue
    if ($process) {
        return [string]$process.CommandLine
    }
    return ""
}

function Stop-Tree([int]$ProcessId, [string]$Reason) {
    if ($ProcessId -le 4) {
        return $false
    }
    Write-Host ("  stopping PID {0} ({1})" -f $ProcessId, $Reason)
    & taskkill.exe /F /T /PID $ProcessId 2>$null | Out-Null
    return $true
}

$frontendPattern = "(?i)(vite|pnpm|node\.exe)"
$backendPattern = "(?i)(backend\.app\.main:app|backend[\\/ ]dev_reloader|uvicorn|local_video_studio\.py)"
$skipped = New-Object System.Collections.Generic.List[string]
$closed = 0

Write-Host "Frontend 5173:"
$vitePids = Get-ListenPids 5173
if (-not $vitePids) {
    Write-Host "  already free."
} else {
    foreach ($pidValue in $vitePids) {
        $commandLine = Get-CommandLine $pidValue
        if ($commandLine -match $frontendPattern -or -not $commandLine) {
            $detail = "Vite / frontend"
            if ($commandLine) {
                $detail = "{0}: {1}" -f $detail, $commandLine
            }
            if (Stop-Tree $pidValue $detail) {
                $closed++
            }
        } else {
            $message = "port 5173 PID {0} is not a Vite process: {1}" -f $pidValue, $commandLine
            Write-Host ("  skipped: " + $message)
            $skipped.Add($message)
        }
    }
}

Write-Host "Backend 7865:"
$apiPids = Get-ListenPids 7865
if (-not $apiPids) {
    Write-Host "  already free."
} else {
    foreach ($pidValue in $apiPids) {
        $commandLine = Get-CommandLine $pidValue
        if ($commandLine -match $backendPattern -or -not $commandLine) {
            $detail = "FastAPI / reloader"
            if ($commandLine) {
                $detail = "{0}: {1}" -f $detail, $commandLine
            }
            if (Stop-Tree $pidValue $detail) {
                $closed++
            }
        } else {
            $message = "port 7865 PID {0} is not the workbench: {1}" -f $pidValue, $commandLine
            Write-Host ("  skipped: " + $message)
            $skipped.Add($message)
        }
    }
}

Write-Host "Leftover supervisor / console windows:"
$leftover = 0
foreach ($process in (Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
    if ([string]$process.CommandLine -match "(?i)backend[\\/ ]dev_reloader\.py") {
        if (Stop-Tree ([int]$process.ProcessId) "dev_reloader.py") {
            $closed++
            $leftover++
        }
    }
}
& taskkill.exe /F /T /FI "WINDOWTITLE eq ZLY AI Video Studio Vite" 2>$null | Out-Null
& taskkill.exe /F /FI "WINDOWTITLE eq ZLY AI Video Studio" 2>$null | Out-Null
if ($leftover -eq 0) {
    Write-Host "  no leftover supervisor process."
}

Start-Sleep -Seconds 1
$viteLeft = Get-ListenPids 5173
$apiLeft = Get-ListenPids 7865
Write-Host ""
if ($viteLeft) {
    Write-Host ("Frontend 5173 still listening: PID " + ($viteLeft -join ", "))
} else {
    Write-Host "Frontend 5173 is free."
}
if ($apiLeft) {
    Write-Host ("Backend 7865 still listening: PID " + ($apiLeft -join ", "))
} else {
    Write-Host "Backend 7865 is free."
}

if ($skipped.Count -gt 0 -or $viteLeft -or $apiLeft) {
    if ($skipped.Count -gt 0) {
        Write-Host "Unrelated processes were left running. Close them manually if you need the ports."
    }
    exit 1
}
exit 0
