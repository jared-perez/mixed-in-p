"""The audio files the OS hands us, and the order to show them in.

"Open with Mixed in P" reaches the app as command-line arguments: the OS
launches the executable with the chosen files appended to argv. This is the
argv half of that entry point, kept as a pure function so it can be tested
without a QApplication — and so it can run *before* one exists, which the
single-instance handshake needs (a secondary process parses its arguments,
hands them to the primary and exits without ever building a window).

``shell_sorted`` is the other half of the same question — not which files, but
in what order — and lives here because the answer is about what the file
manager showed the user, not about playlists.

Verified on Windows against a frozen windowed onedir build (2026-08-05): argv
carries real paths there, spaces stay a single argument, and non-ASCII names
survive intact, so no encoding workaround is needed. It hands back
**backslashes** while Qt's ``toLocalFile()`` hands back forward slashes, which
is exactly why everything here goes through ``normalize_track_path`` — see
``src/utils/paths.py`` for why two spellings of one file is a real bug.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
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

    Order is preserved exactly as given, and *not* sorted here. Measured on
    Windows 11 (2026-08-06): opening five files spawns **five processes with
    one path each**, 25–43 ms apart, so argv order carries no information at
    all about a multi-select — the order the user ends up seeing is decided by
    which handoff arrives first, which was different on every run. Sorting is
    therefore done once, on the assembled batch, by ``shell_sorted``; doing it
    here as well would only reorder lists of one.

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


_DIGITS = re.compile(r"(\d+)")


def _shell_key(path: str) -> tuple:
    """Sort key for one path: filename first, natural order, ties by full path.

    Digit runs compare as numbers so ``Track 2`` precedes ``Track 10`` — both
    Explorer and Finder sort that way, and matching them is the entire point.
    ``casefold`` because both are case-insensitive about it too.

    The ``(kind, value)`` pairs exist only to keep the tuple comparable: a
    chunk is either text or a number and Python will not compare the two.
    """
    chunks = _DIGITS.split(Path(path).name.casefold())
    natural = tuple(
        (1, int(chunk)) if chunk.isdigit() else (0, chunk) for chunk in chunks
    )
    # Two files of the same name in different folders would otherwise tie, and
    # a tie makes the result depend on arrival order again.
    return (natural, path)


def shell_sorted(paths: Iterable[str]) -> list[str]:
    """Put *paths* in the order the file manager showed them to the user.

    A multi-file "open" does not arrive as a list. Windows spawns one process
    per file and the primary receives them in whatever order they win a race —
    measured as different on all three runs of the same five files, matching
    neither the visual selection nor the alphabet. macOS sends one
    ``QFileOpenEvent`` per file. So *something* has to impose an order, and the
    only one that means anything to the person who clicked is the one they were
    looking at: by name, the way the shell lists it.

    Only the filename is compared, not the directory, because that is what the
    user was reading. The full path breaks ties.
    """
    return sorted(paths, key=_shell_key)
