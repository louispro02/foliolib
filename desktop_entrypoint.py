"""Entry point of the executables for Windows, macOS and Linux (built by PyInstaller, see .github/workflows/release-binaries.yml).

Double-click the program: it serves FolioLib on this computer only, opens the browser, and keeps the data in ~/.foliolib.
Docker does not use this file.
"""
import os
import sys
from pathlib import Path

os.environ["FOLIOLIB_DESKTOP"] = "1"                                   # localhost only, browser opens, the account is created in the page
os.environ.setdefault("FOLIOLIB_DATA", str(Path.home() / ".foliolib"))
if not getattr(sys, "frozen", False):                                   # run from the sources: python desktop_entrypoint.py
    sys.path.insert(0, str(Path(__file__).resolve().parent / "app"))

import main  # noqa: E402

if __name__ == "__main__":
    main.serve()
