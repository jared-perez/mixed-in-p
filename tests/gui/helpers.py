"""Helpers shared by the Player-facing GUI tests."""

from pathlib import Path


def unlink_when_released(panel, path) -> None:
    """Delete a file the Player may still have open.

    ``add_tracks`` ends by warming the track most likely to be played next —
    the selection, else row 0 — on a background decode thread. A test that
    deletes that file on the very next line is racing it.

    On POSIX the unlink wins regardless: an open handle does not block it. On
    Windows it raises ``PermissionError`` (WinError 32) for as long as the
    decode is in flight, which is why this only ever failed there, and only in
    a *full* suite run — the CPU contention from the other tests' decodes is
    what widens the window. In isolation the decode of a tiny fixture file
    finishes first almost every time.

    The tell, if this ever comes back: the tests that flaked were exactly the
    ones deleting the **first** file: a test that adds two and deletes the
    second was never affected, because only one track is ever prefetched.
    """
    panel.wait_for_readers()
    Path(path).unlink()
