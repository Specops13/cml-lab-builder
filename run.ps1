# CML Lab Builder launcher for Windows 11 (PowerShell).
#   .\run.ps1               -> start the web UI on http://127.0.0.1:8765
#   .\run.ps1 list          -> run a CLI command
# If scripts are blocked: powershell -ExecutionPolicy Bypass -File .\run.ps1
# Supported Python: 3.10 - 3.13 (newer versions lack prebuilt wheels for some dependencies).
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$Supported = @("3.13", "3.12", "3.11", "3.10")
$venvDir = Join-Path $PSScriptRoot ".venv"
$venvPy = Join-Path $venvDir "Scripts\python.exe"
$venvCfg = Join-Path $venvDir "pyvenv.cfg"

function Fail([string]$msg) {
    Write-Host ""
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

function Get-VenvVersion {
    if (-not (Test-Path $venvCfg) -or -not (Test-Path $venvPy)) { return $null }
    foreach ($line in Get-Content $venvCfg) {
        if ($line -match '^\s*(version|version_info)\s*=\s*(\d+)\.(\d+)') { return "$($Matches[2]).$($Matches[3])" }
    }
    return $null
}

function Find-Python {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) { return $null }
    # Windows PowerShell 5.1 turns redirected native stderr into errors; don't let that stop us.
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        foreach ($v in $Supported) {
            try {
                & py "-$v" -c "import sys" 2>$null | Out-Null
                if ($LASTEXITCODE -eq 0) { return $v }
            } catch { }
        }
    } finally { $ErrorActionPreference = $old }
    return $null
}

$venvVer = Get-VenvVersion
if ($venvVer -and ($Supported -notcontains $venvVer)) {
    Write-Host "Existing .venv uses Python $venvVer (unsupported). Recreating it..."
    Remove-Item -Recurse -Force $venvDir
    $venvVer = $null
} elseif ((Test-Path $venvDir) -and -not $venvVer) {
    Write-Host "Existing .venv is incomplete. Recreating it..."
    Remove-Item -Recurse -Force $venvDir
}

if (-not $venvVer) {
    $ver = Find-Python
    if (-not $ver) {
        Fail ("No supported Python (3.10-3.13) found via the 'py' launcher.`n" +
              "Install Python 3.13 (64-bit) from https://www.python.org/downloads/windows/ and keep the`n" +
              "'py launcher' option checked, then run this script again. (Python 3.14+ is not supported yet.)")
    }
    Write-Host "Creating .venv with Python $ver ..."
    & py "-$ver" -m venv $venvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) { Fail "Could not create the virtual environment." }
    & $venvPy -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { Remove-Item -Recurse -Force $venvDir; Fail "pip upgrade failed (see output above)." }
    & $venvPy -m pip install --prefer-binary -e .
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -Recurse -Force $venvDir
        Fail "Installing dependencies failed (see output above). The .venv was removed; fix the problem and run again."
    }
}

if (Test-Path ".env") {
    Get-Content ".env" | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
        $k, $v = $_ -split '=', 2
        [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), "Process")
    }
}
if ($args.Count -eq 0) { & $venvPy -m encorlab web } else { & $venvPy -m encorlab @args }
exit $LASTEXITCODE
