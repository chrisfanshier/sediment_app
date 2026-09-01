#!/bin/bash
# Launcher for macOS / Linux. Lives inside the dredge_standalone folder;
# runs from the parent folder so "python -m dredge_standalone" resolves.
set -e
cd "$(dirname "$0")/.."

if [ ! -x venv/bin/python ]; then
    echo "First run: setting up Python environment..."
    python3 -m venv venv
    ./venv/bin/pip install -r dredge_standalone/requirements.txt
fi

exec ./venv/bin/python -m dredge_standalone
