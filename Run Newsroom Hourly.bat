@echo off
REM Runs one Newsroom detection cycle and appends the output to logs\hourly.log.
REM This is what "Install-HourlyTask.ps1" registers with Windows Task
REM Scheduler to run automatically every hour. You can also double-click
REM this file any time to run a cycle by hand without opening a console.

cd /d "%~dp0"
if not exist logs mkdir logs

echo [%date% %time%] Starting hourly run >> logs\hourly.log
uv run newsroom run >> logs\hourly.log 2>&1
echo [%date% %time%] Finished with exit code %errorlevel% >> logs\hourly.log
echo. >> logs\hourly.log
