"""Platform-aware application data directories."""

import sys
from pathlib import Path


def get_app_data_dir() -> Path:
    """Return the platform-appropriate application data directory.

    - Windows: %APPDATA%/MixedInP/
    - macOS: ~/Library/Application Support/MixedInP/
    - Linux: ~/.local/share/MixedInP/
    """
    if sys.platform == "win32":
        import os
        appdata = os.environ.get("APPDATA")
        if appdata:
            base = Path(appdata) / "MixedInP"
        else:
            base = Path.home() / "AppData" / "Roaming" / "MixedInP"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "MixedInP"
    else:
        base = Path.home() / ".local" / "share" / "MixedInP"

    base.mkdir(parents=True, exist_ok=True)
    return base
