# Registers a Windows scheduled task that runs newsroom every hour.
# Run once, from the project folder:
#   powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1
# Re-running is safe (-Force replaces the existing task).
#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

$TaskName   = 'Newsroom Free Game Tracker'
$ProjectDir = Split-Path -Parent $PSScriptRoot
$Wrapper    = Join-Path $PSScriptRoot 'run-newsroom.ps1'

# Launch the wrapper via PowerShell, bypassing execution policy for this call only.
$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Wrapper`"" `
    -WorkingDirectory $ProjectDir

# Fire once now, then repeat every hour indefinitely.
# A bare -Once trigger has no Repetition object on some PowerShell versions
# (setting .Repetition.Interval throws), so we copy a Repetition built by a
# trigger that was created with one. ~10 years stands in for "indefinitely".
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date)
$withRepetition = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$trigger.Repetition = $withRepetition.Repetition

# Be forgiving about sleep/battery so a laptop still catches up when it wakes.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description 'Detects newly free PC games (Epic, Steam, GOG) every hour.' `
    -Force | Out-Null

Write-Host "Registered '$TaskName' - runs every hour." -ForegroundColor Green
Write-Host "Test it now:   Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Check status:  Get-ScheduledTaskInfo -TaskName '$TaskName'"
Write-Host "Remove it:     Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
Write-Host "Logs:          $($ProjectDir)\logs\run-<date>.log"
