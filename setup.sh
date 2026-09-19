#!/usr/bin/env sh
set -eu

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  printf '%s\n' "Python 3 was not found. Install Python 3.11+ and run this again."
  exit 1
fi

"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

printf '\nSetup complete.\n'
printf '%s\n' 'Run the UI with: ./run.sh'
printf '%s\n' 'Run an offline test with: .venv/bin/python -m findmeajob run --mock --scorer keyword'
printf '%s\n' 'For local AI, install Ollama separately from https://ollama.com/download'
