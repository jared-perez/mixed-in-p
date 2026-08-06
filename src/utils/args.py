"""The audio files a command line names.

"Open with Mixed in P" reaches the app as command-line arguments: the OS
launches the executable with the chosen files appended to argv. This is the
argv half of that entry point, kept as a pure function so it can be tested
without a QApplication — and so it can run *before* one exists, which the
single-instance handshake needs (a secondary process parses its arguments,
hands them to the primary and exits without ever building a window).

Verified on Windows against a frozen windowed onedir build (2026-08-05): argv
carries real paths there, spaces stay a single argument, and non-ASCII names
survive intact, so no encoding workaround is needed. It hands back
**backslashes** while Qt's ``toLocalFile()`` hands back forward slashes, which
is exactly why everything here goes through ``normalize_track_path`` — see
``src/utils/paths.py`` for why two spellings of one file is a real bug.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

# The canonical extension set, shared with the folder scanner rather than
# copied: a format added there must not silently become one the OS can hand us
# and we refuse. ``src.analysis.result`` is documented as dependency-free
# (no librosa/numpy), so importing it costs nothing at startup.
from src.analysis.result import SUPPORTED_EXTENSIONS
from .paths import normalize_track_path


def parse_audio_args(argv: Sequence[str]) -> list[str]:
    """The playable audio files named in *argv*, normalized and de-duplicated.

    ``argv[0]`` is the program itself and is always skipped. Of the rest, an
    argument is kept only if it is not a flag, carries a supported audio
    extension, and actually exists as a file:

    - **Flags are dropped** — anything starting with ``-``, so ``--cli`` is not
      mistaken for a filename. No audio file this app opens starts with a dash,
      and on Windows a path never can.
    - **Unsupported extensions are dropped** rather than passed through and
      failed later, so dragging a mixed selection onto the icon adds the audio
      and quietly ignores the artwork and the ``.txt`` next to it.
    - **Missing files are dropped.** The OS can hand us a path that has since
      been moved, and a file that cannot be read would otherwise become a dead
      library row that only the relocate flow can clear.

    Order is preserved exactly as given, and *not* sorted. Within one process
    the order is the order of the arguments (verified on Windows), but whether
    a multi-select in Explorer even produces one process is still unknown — so
    imposing a sort here would be inventing an ordering guarantee we cannot
    honour anyway. That decision belongs upstairs once the association exists.

    Duplicates within one command line collapse to the first occurrence. This
    is not the duplicate *policy* question — additions force
    ``allow_duplicates`` so a file already in the playlist lands again — it is
    only that one invocation naming the same file twice means it once.
    """
    seen: set[str] = set()
    files: list[str] = []

    for arg in argv[1:]:
        if not arg or arg.startswith("-"):
            continue
        if Path(arg).suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        path = normalize_track_path(arg)
        if path in seen:
            continue
        try:
            if not Path(path).is_file():
                continue
        except OSError:
            # A disconnected network path can fail the stat outright.
            continue
        seen.add(path)
        files.append(path)

    return files
