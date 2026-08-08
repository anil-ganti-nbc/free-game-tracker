<#
.SYNOPSIS
    Registers a Windows Task Scheduler task that runs the Newsroom detection
    cycle every hour, using "Run Newsroom Hourly.bat" in this same folder.

.DESCRIPTION
    No admin rights are required — the task is created for your own user
    account and only runs while you're logged on. Output from each run is
    appended to logs\hourly.log.

.EXAMPLE
    Right-click this file -> "Run with PowerShell", or from a PowerShell
    prompt in this folder:  .\Install-HourlyTask.ps1

.NOTES
    To remove the task later:
        Unregister-ScheduledTask -TaskName "Newsroom Hourly Check" -Confirm:$false
#>

$ErrorActionPreference = "Stop"

$taskName = "Newsroom Hourly Check"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$batPath = Join-Path $scriptDir "Run Newsroom Hourly.bat"

if (-not (Test-Path $batPath)) {
    throw "Could not find '$batPath'. Keep this script in the same folder as 'Run Newsroom Hourly.bat'."
}

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Write-Host "Task '$taskName' already exists - removing it first so this run replaces it cleanly."
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute $batPath -WorkingDirectory $scriptDir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration ([TimeSpan]::MaxValue)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Runs the Free Game Tracker's hourly free-game/deal check." | Out-Null

Write-Host ""
Write-Host "Scheduled task '$taskName' installed - it will run every hour from now on."
Write-Host "Logs: $scriptDir\logs\hourly.log"
Write-Host ""
Write-Host "To check on it:      Get-ScheduledTask -TaskName '$taskName' | Get-ScheduledTaskInfo"
Write-Host "To run it right now: Start-ScheduledTask -TaskName '$taskName'"
Write-Host "To remove it:        Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
