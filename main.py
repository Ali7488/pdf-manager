"""Start PDF Manager (also the PyInstaller entry script).

    uv run main.py                 the desktop window (pywebview)
    uv run main.py --browser       browser mode: the app in your default browser
    uv run main.py --browser --no-browser
                                   browser mode's server only (prints the link)

Browser mode never imports pywebview, Qt or pythonnet, so it also runs from
the browser-only dependency set (see docs/BROWSER_MODE.md).
"""

import sys


def run(argv: list[str]) -> int:
    """Start the mode the arguments ask for."""
    if "--browser" in argv:
        from api.web.launch import main as browser_main

        return browser_main(argv)
    from api.app import main as desktop_main

    return desktop_main()


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
