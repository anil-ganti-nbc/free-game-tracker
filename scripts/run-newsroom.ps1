# Wrapper that the scheduled task calls. Runs one detection cycle and logs it.
# Safe to run by hand too:  powershell -ExecutionPolicy Bypass -File scripts\run-newsroom.ps1
#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

# The project root is the parent of this script's folder.
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

# Keep a daily log next to the project so runs are auditable.
$LogDir = Join-Path $ProjectDir 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir ('run-{0}.log' -f (Get-Date -Format 'yyyyMMdd'))

# Find uv: on PATH, or the default per-user install location.
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe' }
if (-not (Test-Path $uv)) {
    throw "uv not found on PATH or at $uv. Install uv or edit this script's `$uv path."
}

"$(Get-Date -Format o)  starting newsroom run" | Add-Content -Path $LogFile
# Redirect all streams (output + errors) into the log.
& $uv run newsroom run *>> $LogFile
"$(Get-Date -Format o)  finished (exit $LASTEXITCODE)" | Add-Content -Path $LogFile
