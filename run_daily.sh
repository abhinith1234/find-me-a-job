#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
LOG_DIR="$PROJECT_ROOT/out/scheduled"
LOG_FILE="$LOG_DIR/$(date +%F).log"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Project is not set up yet: $VENV_PYTHON" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"
cd "$PROJECT_ROOT"
"$VENV_PYTHON" -m findmeajob run --send --old-ones old_ones.json >> "$LOG_FILE" 2>&1
