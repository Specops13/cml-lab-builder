@echo off
rem ENCOR Lab Builder launcher for Windows (double-click or run from cmd).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
set RC=%ERRORLEVEL%
if not "%RC%"=="0" (
  echo.
  echo run.bat: finished with error code %RC%.
  if "%~1"=="" pause
)
exit /b %RC%
