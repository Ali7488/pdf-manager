"""Entry script of the browser-mode build (PDF_MANAGER_BUILD=browser, see pdf-manager.spec).

Same as ``uv run main.py --browser``: PDF Manager in the user's own browser.
It never imports pywebview, Qt or pythonnet, which this build doesn't contain.
"""

import sys

from api.web.launch import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
