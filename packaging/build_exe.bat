@echo off
rem Build the Windows bundle once: dist\ENCORLab-<version>-windows-x64.zip
rem Needs Python 3.12 or 3.13 from python.org. Double-click, or run from a Command Prompt:
rem     packaging\build_exe.bat
rem     set PYTHON=C:\Path\To\python.exe ^&^& packaging\build_exe.bat      (use a specific Python)
setlocal
cd /d "%~dp0.."
set "PY="
if defined PYTHON set "PY="%PYTHON%""
if not defined PY for %%V in (3.13 3.12) do (
  if not defined PY ( py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V" )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if (3,12) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo ERROR: Python 3.12 or 3.13 not found. Install it from https://www.python.org/downloads/windows/ and run this again.
  goto :fail
)
echo Using: %PY%
set "VENV=build\windows\venv"
if exist "%VENV%" rmdir /s /q "%VENV%"
%PY% -m venv "%VENV%" || goto :fail
"%VENV%\Scripts\python.exe" -m pip install -q --disable-pip-version-check --upgrade pip || goto :fail
"%VENV%\Scripts\python.exe" -m pip install -q --disable-pip-version-check . "pyinstaller>=6.22,<7" || goto :fail
"%VENV%\Scripts\python.exe" packaging\build.py --work build\windows --out dist %* || goto :fail
echo.
echo Done. Unzip the file in the dist folder anywhere and double-click ENCORLab.exe
if "%~1"=="" pause
exit /b 0
:fail
echo.
echo BUILD FAILED
if "%~1"=="" pause
exit /b 1
