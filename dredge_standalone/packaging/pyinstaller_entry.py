"""PyInstaller entry point for Dragognosificator.

Not used when running from source (use ``python -m dredge_standalone``).
"""
import os
import sys

# When run from source, make the folder containing the package importable.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from dredge_standalone.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
