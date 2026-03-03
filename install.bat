@echo off
:: install.bat — NoEyes Windows installer (cmd.exe fallback)
:: Prefer install.ps1 if you have PowerShell.
:: Usage:  install.bat

echo.
echo   NoEyes -- Windows Installer
echo.

:: ── find Python ──────────────────────────────────────────────────────────────

set PYTHON=

for %%C in (python python3 py) do (
    %%C -c "import sys; exit(0 if sys.version_info>=(3,8) else 1)" 2>nul
    if !errorlevel! == 0 (
        set PYTHON=%%C
        goto :found_python
    )
)

:: Try the Windows Store python3 shim path
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\python3.exe" (
    "%LOCALAPPDATA%\Microsoft\WindowsApps\python3.exe" -c "import sys; exit(0 if sys.version_info>=(3,8) else 1)" 2>nul
    if !errorlevel! == 0 (
        set PYTHON=%LOCALAPPDATA%\Microsoft\WindowsApps\python3.exe
        goto :found_python
    )
)

echo   [!] Python 3.8+ not found.
echo.
echo   Please install Python from https://www.python.org/downloads/
echo   Check "Add Python to PATH" during installation.
echo   Then re-run this script.
echo.

:: Try winget as a courtesy
where winget >nul 2>&1
if %errorlevel% == 0 (
    echo   Attempting: winget install Python.Python.3.12
    winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    echo   If install succeeded, close this window and re-run install.bat
)
goto :end

:found_python
for /f "tokens=*" %%v in ('"%PYTHON%" -c "import sys; print(\"%%d.%%d.%%d\" %% sys.version_info[:3])"') do set PYVER=%%v
echo     Python %PYVER% found

:: ── hand off to install.py ────────────────────────────────────────────────────

set SCRIPT_DIR=%~dp0
set INSTALLER=%SCRIPT_DIR%install.py

if not exist "%INSTALLER%" (
    echo   [!] install.py not found in %SCRIPT_DIR%
    goto :end
)

echo     Launching install.py...
echo.
"%PYTHON%" "%INSTALLER%" %*

:end
pause
