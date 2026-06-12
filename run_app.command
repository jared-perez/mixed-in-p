#!/usr/bin/env bash
# Launch Mixed in P (macOS — double-clickable from Finder)
# Identical to run_app.sh; the .command extension makes Finder open Terminal automatically.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

python -m src.main
