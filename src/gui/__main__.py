"""Entry point for running the GUI as a module."""

import sys

from .app import run_app

if __name__ == "__main__":
    sys.exit(run_app())
