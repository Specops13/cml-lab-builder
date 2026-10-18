"""PyInstaller entry script (kept outside the package so relative imports work)."""
import multiprocessing
import sys

from encorlab.launcher import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
