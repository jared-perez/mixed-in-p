"""Windowed decode for the Compatible Tracks audition.

The Player decodes whole tracks (instant seeking, one buffer in RAM); an
audition cannot afford that. It has to start the moment a row is clicked,
it may never be listened to for more than a few seconds, and the PCM cache
holds three ~100 MB buffers that a browse through a match list would thrash
in seconds. So this reads a *window* — about half a minute from an offset —
and nothing else.

That shape also makes the +30 s skip trivial: it is just the next window,
so memory stays at one window no matter how long the file is.

Reading a range is `soundfile`'s `start=`/`frames=`; the librosa fallback
(for formats an older libsndfile cannot open) takes `offset=`/`duration=`.
A window that starts past the end of the file comes back empty, which is
how the caller learns it has run out of track — no separate duration probe,
and no decision made from a duration the tags claim rather than the file.
"""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

logger = logging.getLogger(__name__)

# How much audio one audition window holds. Long enough that a listen is a
# real listen rather than a stab, short enough to decode in well under the
# time it takes to move the mouse.
WINDOW_MS = 35_000


class AuditionWindowWorker(QObject):
    """Decodes one window of one file to float32 PCM, off the UI thread."""

    #: path, offset_ms, pcm, sample_rate — the offset rides along so a
    #: result that arrives after the user has skipped on can be discarded.
    ready = Signal(str, int, object, int)
    #: path, offset_ms — the window held no audio (past the end of the file).
    empty = Signal(str, int)
    error = Signal(str, str)

    def __init__(self, file_path: str, offset_ms: int, window_ms: int = WINDOW_MS) -> None:
        super().__init__()
        self._path = file_path
        self._offset_ms = max(0, int(offset_ms))
        self._window_ms = int(window_ms)

    @Slot()
    def run(self) -> None:
        try:
            pcm, sr = read_window(self._path, self._offset_ms, self._window_ms)
        except Exception as e:  # noqa: BLE001 — a bad file must not kill the thread
            logger.warning("Audition decode failed for %s: %s", self._path, e)
            self.error.emit(self._path, str(e))
            return
        if pcm is None or pcm.shape[0] == 0 or sr <= 0:
            self.empty.emit(self._path, self._offset_ms)
            return
        self.ready.emit(self._path, self._offset_ms, pcm, int(sr))


def read_window(path: str, offset_ms: int, window_ms: int) -> tuple[np.ndarray, int]:
    """`(pcm (frames, channels) float32, sample rate)` for one window.

    An offset past the end of the file returns an empty array rather than
    raising — that is a normal outcome of skipping forward, not an error.
    """
    try:
        import soundfile as sf
    except ImportError:
        sf = None
    else:
        try:
            with sf.SoundFile(path) as f:
                sr = int(f.samplerate)
                start = int(offset_ms / 1000.0 * sr)
                if start >= len(f):
                    return np.zeros((0, max(1, f.channels)), dtype=np.float32), sr
                f.seek(start)
                frames = int(window_ms / 1000.0 * sr)
                data = f.read(frames, dtype="float32", always_2d=True)
                return np.ascontiguousarray(data, dtype=np.float32), sr
        except Exception:  # noqa: BLE001 — fall through to librosa
            pass

    import librosa

    y, sr = librosa.load(
        path,
        sr=None,
        mono=False,
        offset=offset_ms / 1000.0,
        duration=window_ms / 1000.0,
    )
    if y.ndim == 1:
        y = y.reshape(1, -1)
    return np.ascontiguousarray(y.T, dtype=np.float32), int(sr)
