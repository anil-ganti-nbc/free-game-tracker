@echo off
REM Double-click this file to check for free games right now.
REM It runs the same thing as: uv run newsroom run

cd /d "%~dp0"

echo ============================================
echo   Newsroom - checking for free games...
echo ============================================
echo.

uv run newsroom run

echo.
if errorlevel 1 (
  echo Something went wrong above. If it says 'uv' is not recognized,
  echo uv isn't installed yet - see the README.
) else (
  echo Done.
)
echo.
echo Press any key to close this window.
pause >nul
