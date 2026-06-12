"""Background worker that decodes an audio file to full-resolution PCM.

Used by the Player panel to load a whole track into memory before handing it to
:class:`~src.gui.widgets.player_engine.PlayerEngine`. The decode (soundfile,
falling back to librosa for formats it can't read) reuses
:meth:`WaveformWorker._read_audio` so the format support lives in one place.
The decoded ``path`` is echoed back with the result so the panel can discard
stale decodes when the user switches tracks mid-load.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from .waveform_worker import WaveformWorker

logger = logging.getLogger(__name__)


class AudioDecodeWorker(QObject):
    """Decodes one file to float32 PCM ``(frames, channels)`` off the UI thread."""

    decoded = Signal(str, object, int)  # path, pcm, sample_rate
    error = Signal(str, str)            # path, message

    def __init__(self, file_path: str) -> None:
        super().__init__()
        self._file_path = file_path

    @Slot()
    def run(self) -> None:
        try:
            pcm, sr = WaveformWorker._read_audio(self._file_path)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Audio decode failed for {self._file_path}: {e}")
            self.error.emit(self._file_path, str(e))
            return
        if pcm.shape[0] == 0 or sr <= 0:
            self.error.emit(self._file_path, "Empty audio")
            return
        self.decoded.emit(self._file_path, pcm, int(sr))
