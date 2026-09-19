$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$logDir = Join-Path $projectRoot 'out\scheduled'
$logFile = Join-Path $logDir (Get-Date -Format 'yyyy-MM-dd')

if (-not (Test-Path $venvPython)) {
    throw "Project is not set up yet: $venvPython"
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Set-Location $projectRoot
& $venvPython -m findmeajob run --send --old-ones old_ones.json *>> "$logFile.log"
exit $LASTEXITCODE
