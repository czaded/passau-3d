#!/bin/bash
# Startet den lokalen Webserver und öffnet das Modell im Browser.
# Doppelklick im Finder oder: ./start.command [port]
cd "$(dirname "$0")"
PORT="${1:-8791}"
while lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; do PORT=$((PORT + 1)); done
(sleep 1; open "http://127.0.0.1:$PORT/") &
exec python3 serve.py "$PORT"
