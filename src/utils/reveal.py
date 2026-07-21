"""Reveal a file in the OS file manager, with the file itself selected.

Unlike merely opening the containing folder, this highlights the target file
(Finder on macOS, File Explorer on Windows). Kept free of Qt so it can be unit
tested and reused from any layer.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def reveal_in_file_manager(file_path: str) -> bool:
    """Open the OS file manager showing ``file_path`` with the file selected.

    Returns True if the file exists and a reveal was launched; False if the
    file is missing (so the caller can tell the user it moved) or the launch
    failed. Never raises for the expected cases.

    Platform behaviour:
      * macOS  — ``open -R`` reveals and selects the file in Finder.
      * Windows — ``explorer /select,`` selects the file in File Explorer.
        (explorer exits non-zero even on success, so its result is ignored.)
      * Other  — no portable "select"; opens the containing folder instead.
    """
    path = Path(file_path)
    try:
        if not file_path or not path.exists():
            return False
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=False)
        elif sys.platform == "win32":
            # explorer wants a native, backslash path and returns 1 on success.
            subprocess.run(["explorer", "/select,", os.path.normpath(str(path))])
        else:
            subprocess.run(["xdg-open", str(path.parent)], check=False)
        return True
    except OSError:
        return False
