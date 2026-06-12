#!/usr/bin/env python3
"""Main entry point for Mixed in P.

Usage:
    python -m src.main          # Run GUI
    python -m src.main --cli    # Run CLI
"""

import os
import sys

# --- PyInstaller + PySide6 QtMultimedia DLL search path fix (Windows) ---
# MUST run before any PySide6 / Qt import. In a frozen onedir build, PySide6
# core DLLs and the FFmpeg runtime DLLs live at _internal/PySide6/, but the
# Qt multimedia plugin lives two folders deeper at _internal/PySide6/plugins/
# multimedia/. Windows' DLL loader doesn't walk parent directories, so we
# register the PySide6 folder in both the modern DLL directory list and the
# legacy PATH so ffmpegmediaplugin.dll can find its dependencies.
if sys.platform == "win32" and getattr(sys, "frozen", False):
    _pyside_dir = os.path.join(sys._MEIPASS, "PySide6")
    if os.path.isdir(_pyside_dir):
        os.add_dll_directory(_pyside_dir)
        os.environ["PATH"] = _pyside_dir + os.pathsep + os.environ.get("PATH", "")
# ------------------------------------------------------------------------

# --- Silence harmless FFmpeg decoder chatter from QMediaPlayer ---
# Qt's FFmpeg multimedia backend routes libav decoder logs (e.g.
# "[mp3float @ ...] Could not update timestamps for skipped samples") through
# its qt.multimedia.ffmpeg logging categories — the global FFmpeg log level is
# ignored. These are cosmetic noise emitted while seeking/looping MP3s. Mute
# debug/info/warning for those categories but keep critical/fatal so genuine
# backend errors still surface. MUST be set before the QApplication is created.
_ffmpeg_quiet_rule = (
    "qt.multimedia.ffmpeg.debug=false;"
    "qt.multimedia.ffmpeg.info=false;"
    "qt.multimedia.ffmpeg.warning=false;"
    "qt.multimedia.ffmpeg.*.debug=false;"
    "qt.multimedia.ffmpeg.*.info=false;"
    "qt.multimedia.ffmpeg.*.warning=false"
)
_existing_rules = os.environ.get("QT_LOGGING_RULES", "")
# Append so our rules win (last match takes precedence) without clobbering any
# rules the user set in their environment.
os.environ["QT_LOGGING_RULES"] = (
    f"{_existing_rules};{_ffmpeg_quiet_rule}" if _existing_rules else _ffmpeg_quiet_rule
)
# ------------------------------------------------------------------------


def main():
    """Main entry point."""
    if "--cli" in sys.argv:
        # Run CLI mode
        from src.cli import main as cli_main
        sys.exit(cli_main())
    else:
        # Run GUI mode
        from src.gui import run_app
        sys.exit(run_app())


if __name__ == "__main__":
    main()
