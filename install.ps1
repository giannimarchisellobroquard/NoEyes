# install.ps1 — NoEyes Windows installer bootstrap
# Run in PowerShell:  .\install.ps1
# If blocked by execution policy:
#   powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"

function Write-Ok($msg)   { Write-Host "  " -NoNewline; Write-Host ([char]0x2714) -ForegroundColor Green -NoNewline; Write-Host "  $msg" }
function Write-Err($msg)  { Write-Host "  " -NoNewline; Write-Host ([char]0x2718) -ForegroundColor Red -NoNewline; Write-Host "  $msg" }
function Write-Warn($msg) { Write-Host "  ! $msg" -ForegroundColor Yellow }
function Write-Info($msg) { Write-Host "  . $msg" -ForegroundColor Cyan }

Write-Host ""
Write-Host "  NoEyes — Windows Installer" -ForegroundColor Cyan
Write-Host ""

# ── find Python ───────────────────────────────────────────────────────────────

$Python = $null

foreach ($candidate in @("python", "python3", "py")) {
    try {
        $ver = & $candidate -c "import sys; print('%d%d' % sys.version_info[:2])" 2>$null
        if ($ver -and ([int]$ver -ge 38)) {
            $Python = $candidate
            $verStr = & $candidate -c "import sys; print('%d.%d.%d' % sys.version_info[:3])"
            Write-Ok "Python $verStr found"
            break
        }
    } catch { }
}

if (-not $Python) {
    Write-Warn "Python 3.8+ not found — attempting to install..."

    # Try winget first (Windows 11 / modern Windows 10)
    $hasWinget = Get-Command winget -ErrorAction SilentlyContinue
    if ($hasWinget) {
        Write-Info "Installing Python 3.12 via winget..."
        winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    }
    # Try Chocolatey
    elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        Write-Info "Installing Python via Chocolatey..."
        choco install python3 -y
    }
    # Try Scoop
    elseif (Get-Command scoop -ErrorAction SilentlyContinue) {
        Write-Info "Installing Python via Scoop..."
        scoop install python
    }
    else {
        Write-Err "No package manager found (winget/choco/scoop)."
        Write-Host ""
        Write-Host "  Please install Python manually:" -ForegroundColor Yellow
        Write-Host "    https://www.python.org/downloads/" -ForegroundColor DarkGray
        Write-Host ""
        Write-Host "  Then re-run this script." -ForegroundColor Yellow
        exit 1
    }

    # Refresh PATH and try again
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")

    foreach ($candidate in @("python", "python3", "py")) {
        try {
            $ver = & $candidate -c "import sys; print('%d%d' % sys.version_info[:2])" 2>$null
            if ($ver -and ([int]$ver -ge 38)) {
                $Python = $candidate
                $verStr = & $candidate -c "import sys; print('%d.%d.%d' % sys.version_info[:3])"
                Write-Ok "Python $verStr installed"
                break
            }
        } catch { }
    }

    if (-not $Python) {
        Write-Err "Python installed but not found in PATH."
        Write-Host "  Open a new PowerShell window and re-run: .\install.ps1" -ForegroundColor Yellow
        exit 1
    }
}

# ── hand off to install.py ────────────────────────────────────────────────────

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Installer = Join-Path $ScriptDir "install.py"

if (-not (Test-Path $Installer)) {
    Write-Err "install.py not found in $ScriptDir"
    exit 1
}

Write-Info "Launching install.py..."
Write-Host ""

& $Python $Installer @args
