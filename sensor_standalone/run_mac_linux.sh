#!/bin/bash
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ ! -x "$HERE/venv/bin/python" ]; then
    echo "First run: setting up Python environment..."
    python3 -m venv "$HERE/venv"
fi

if ! "$HERE/venv/bin/python" -c "import PySide6, pyqtgraph, pandas, numpy, scipy" 2>/dev/null; then
    echo "Installing requirements (one-time, may take a few minutes)..."
    "$HERE/venv/bin/pip" install -r "$HERE/requirements.txt"
fi

cd "$HERE/.."
exec "$HERE/venv/bin/python" -m sensor_standalone
