"""One spelling for a track's path.

Path identity in the library is **exact-string**: ``Library.add_track`` keys on
``SELECT id FROM tracks WHERE path=?`` and ``duplicate_policy.filter_new``
compares literal strings. So every route a file can arrive by — an OS file
drop, the file dialog, a folder scan, a drag from another panel, and argv or a
``QFileOpenEvent`` once "Open with Mixed in P" exists — has to spell the same
file the same way. Two spellings mean two library rows for one file, and a
duplicate check that cannot see the collision.

The trap that made this concrete is Windows-only: ``QUrl.toLocalFile()`` and
``QFileDialog`` both return forward slashes there (``C:/music/a.mp3``) while a
folder scan and argv return backslashes (``C:\\music\\a.mp3``). Same file, two
strings, and the first drop onto a playlist quietly created a second row.

Normalize at the point a path enters from the OS or the user, never on paths
read back out of the database — a stored path is the identity, and rewriting
it on load would break row lookup, the playing-track marker and relocate.
"""

from __future__ import annotations

from pathlib import Path


def normalize_track_path(path: str | Path) -> str:
    """The canonical string for *path*: absolute, resolved, native separators.

    ``resolve()`` rather than plain ``Path()`` because that is what every
    existing file-drop handler already does (``str(path.resolve())``), so this
    is the spelling most rows in the wild are already stored under. It also
    collapses symlinks and, on Windows, the case the user happened to type.

    A missing file is fine — ``resolve()`` is non-strict and just makes the
    path absolute, which keeps a drag of an already-moved track comparable to
    the row that is about to be relocated.
    """
    p = Path(path)
    try:
        return str(p.resolve())
    except OSError:
        # A disconnected network drive can make resolution fail outright.
        # Absolute-but-unresolved still beats handing the caller a raw string.
        return str(p.absolute())
