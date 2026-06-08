# Install Bentlyk as an always-on resident on Windows.
#
# Registers a hidden Scheduled Task that runs the worker at every logon, restarts
# it if it ever stops, and keeps running with no console window. Credentials are
# read from a .env file in the repo (so nothing lives in the task definition).
#
# Usage (PowerShell, from the repo folder, after `pip install -e ".[device]"`):
#   1) create a .env file here (see .env.example) with your keys + BENTLYK_ALLOW_CODE=1
#   2) .\scripts\install_windows.ps1
#
# Manage later:
#   Start-ScheduledTask -TaskName Bentlyk   |   Stop-ScheduledTask -TaskName Bentlyk
#   Unregister-ScheduledTask -TaskName Bentlyk -Confirm:$false   # uninstall

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonw = Join-Path $repo ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $pythonw)) {
    Write-Error "venv not found at $pythonw. Run: python -m venv .venv ; .\.venv\Scripts\python.exe -m pip install -e `".[device]`""
}
if (-not (Test-Path (Join-Path $repo ".env"))) {
    Write-Warning "No .env in $repo — create it (keys + BENTLYK_ALLOW_CODE=1) or the worker won't have its credentials."
}

$action  = New-ScheduledTaskAction -Execute $pythonw -Argument "-m bentlyk worker --interval 120" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -Hidden `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName "Bentlyk" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Bentlyk — autonomous resident" -Force | Out-Null

Start-ScheduledTask -TaskName "Bentlyk"
Write-Host "Bentlyk is now a resident: running in the background, autostarts at logon, restarts on failure."
Write-Host "Watch it live on the dashboard. Stop with: Stop-ScheduledTask -TaskName Bentlyk"
