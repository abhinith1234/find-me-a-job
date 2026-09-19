#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-install}"
TIME="${2:-09:00}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$PROJECT_ROOT/run_daily.sh"
MARKER="# findmeajob-daily-email"

if [[ ! -x "$RUNNER" ]]; then
  chmod +x "$RUNNER"
fi

case "$ACTION" in
  install)
    HOUR="${TIME%:*}"
    MINUTE="${TIME#*:}"
    CRON_LINE="$MINUTE $HOUR * * * $RUNNER $MARKER"
    (crontab -l 2>/dev/null | grep -v "$MARKER" || true; echo "$CRON_LINE") | crontab -
    echo "Installed daily email at $TIME local time."
    ;;
  remove)
    (crontab -l 2>/dev/null | grep -v "$MARKER" || true) | crontab -
    echo "Removed the Find Me A Job daily email schedule."
    ;;
  run-now)
    "$RUNNER"
    ;;
  list)
    crontab -l 2>/dev/null | grep "$MARKER" || echo "No Find Me A Job schedule installed."
    ;;
  *)
    echo "Usage: $0 {install|remove|run-now|list} [HH:MM]" >&2
    exit 2
    ;;
esac
