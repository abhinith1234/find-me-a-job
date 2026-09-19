$ErrorActionPreference = 'Stop'
$venvPython = Join-Path $PWD '.venv\Scripts\python.exe'

if (-not (Test-Path $venvPython)) {
    throw 'The project is not set up yet. Run .\setup.ps1 first.'
}

& $venvPython -m findmeajob serve --host 127.0.0.1 --port 5000
