#!/bin/bash
# macOS: double-click in Finder. The first run sets things up (1-2 min).
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First-time setup..."
  python3 -m venv .venv || { echo "Python 3 not found. Install it from https://www.python.org/downloads/"; read; exit 1; }
  ./.venv/bin/pip install --upgrade pip -q
  ./.venv/bin/pip install -r requirements.txt -q || { echo "Setup failed."; read; exit 1; }
fi
./.venv/bin/python run.py
