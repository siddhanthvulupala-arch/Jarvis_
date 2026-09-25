[CmdletBinding()]
param([switch]$Text, [switch]$Background)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$python311 = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
$venv = Join-Path $root '.venv'

if (-not (Test-Path $python)) {
    if (Test-Path $python311) {
        & $python311 -m venv $venv
    } else {
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        if (-not $launcher) {
            throw 'Python 3.11 is required. Install Python 3.11 and run this launcher again.'
        }
        & py -3.11 -m venv $venv
    }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python 3.11 virtual environment.' }
}

$version = & $python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
if ($LASTEXITCODE -ne 0 -or $version -ne '3.11') {
    throw "The project environment must use Python 3.11.x; found $version."
}

$requirements = Join-Path $root 'requirements.txt'
$stamp = Join-Path $venv '.requirements.sha256'
$hash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
if (-not (Test-Path $stamp) -or (Get-Content -LiteralPath $stamp -Raw).Trim() -ne $hash) {
    if ($Background) {
        throw 'Dependencies need installation. Run Start-Friday.ps1 once without -Background, then use -Background for startup.'
    }
    & $python -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    Set-Content -LiteralPath $stamp -Value $hash -NoNewline
}

$entry = Join-Path $root 'jarvis.py'
if ($Background) {
    $assistant = Start-Process -FilePath $python -ArgumentList ('"{0}"' -f $entry) -WorkingDirectory $root -WindowStyle Hidden -PassThru
    Write-Output "Started FRIDAY/JARVIS in the background (PID $($assistant.Id))."
    exit 0
}
if ($Text) { & $python $entry --text } else { & $python $entry }
