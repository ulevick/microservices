#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
pkill -f "$PWD/.venv/bin/uvicorn main:app" 2>/dev/null
rm -f logs/*.pid
sleep 1
if lsof -iTCP:8000-8003 -sTCP:LISTEN -P -n >/dev/null 2>&1; then
  echo "Dalis portu vis dar uzimti:"
  lsof -iTCP:8000-8003 -sTCP:LISTEN -P -n | tail -n +2
else
  echo "Visi servisai sustabdyti."
fi
