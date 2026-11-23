"""Start PDF Manager: ``uv run main.py`` (also the PyInstaller entry script)."""

import sys

from api.app import main

if __name__ == "__main__":
    sys.exit(main())
