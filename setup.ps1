$ErrorActionPreference = 'Stop'

$python = Get-Command py -ErrorAction SilentlyContinue
if ($null -eq $python) {
    $python = Get-Command python -ErrorAction SilentlyContinue
}
if ($null -eq $python) {
    throw 'Python 3 was not found. Install Python 3.11+ from https://www.python.org/downloads/ and run this again.'
}

& $python.Source -3 -m venv .venv 2>$null
if ($LASTEXITCODE -ne 0) {
    & $python.Source -m venv .venv
}
$venvPython = Join-Path $PWD '.venv\Scripts\python.exe'
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt

Write-Host ''
Write-Host 'Setup complete.'
Write-Host 'Run the UI with: .\run.ps1'
Write-Host 'Run an offline test with: .\.venv\Scripts\python.exe -m findmeajob run --mock --scorer keyword'
Write-Host 'For local AI, install Ollama separately from https://ollama.com/download'
