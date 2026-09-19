#!/usr/bin/env sh
set -eu

if [ ! -x .venv/bin/python ]; then
  printf '%s\n' 'The project is not set up yet. Run ./setup.sh first.'
  exit 1
fi

exec .venv/bin/python -m findmeajob serve --host 127.0.0.1 --port 5000
