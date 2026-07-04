"""In-memory PCM playback engine for the Player panel.

Plays a whole pre-decoded track from an in-memory PCM buffer through a
``sounddevice`` output stream. Because the entire file lives in RAM as a NumPy
array, seeking is just moving an integer frame offset — there is no decoder
flush, so ``seek_ms()`` applies instantly on every platform. This sidesteps
``QMediaPlayer.setPosition()``, whose seek is sluggish on Windows.

This is the play-through sibling of the slicer's :class:`LoopPlayer`: it shares
the same real-time audio-thread design (a ``threading.Lock`` guards the small
shared state; a ``QTimer`` on the GUI thread polls the position and emits
signals, so Qt widgets are never touched from the audio thread) and reuses its
:func:`output_stream_kwargs` for the low-latency WASAPI path on Windows.

By default it plays from the current position to the end of the buffer, then
emits ``finished`` so the playlist can auto-advance. It can also loop a
sub-range gaplessly: when loop mode is enabled the audio callback wraps the
read pointer back to the start frame at the end marker (the same technique as
``LoopPlayer``), so the slice section can preview an A-B region without a
second engine. Looping never emits ``finished``.
"""

from __future__ import annotations

import logging
import threading

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, QTimer, Signal

from .loop_player import _BLOCK, _POS_TIMER_MS, output_stream_kwargs

logger = logging.getLogger(__name__)


class PlayerEngine(QObject):
    """Plays an in-memory PCM buffer through to the end, with instant seeking."""

    positionChanged = Signal(int)  # current playback position, ms
    durationChanged = Signal(int)  # total track length, ms
    stateChanged = Signal(bool)    # True = playing, False = paused/stopped
    finished = Signal()            # playback reached the end of the track

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._pcm: np.ndarray | None = None  # (frames, channels) float32
        self._sr: int = 0
        self._channels: int = 2
        self._total_frames: int = 0
        self._pos: int = 0
        self._volume: float = 0.7
        self._stream: sd.OutputStream | None = None
        self._playing: bool = False
        # Set by the audio thread when it consumes the final frame; the GUI
        # position timer turns it into the (GUI-thread) `finished` signal so we
        # never emit Qt signals from the real-time callback.
        self._reached_end: bool = False
        self._state: str = "stopped"  # "stopped" | "playing" | "paused"
        # Optional A-B loop region (frames). When `_loop_enabled` is True the
        # callback plays only [_loop_start, _loop_end) and wraps at the end.
        # `_loop_end == 0` means "unset" (treated as the full track).
        self._loop_enabled: bool = False
        self._loop_start: int = 0
        self._loop_end: int = 0

        self._pos_timer = QTimer(self)
        self._pos_timer.setInterval(_POS_TIMER_MS)
        self._pos_timer.timeout.connect(self._tick)

    # ----------------------------------------------------------- buffer/config

    def load(self, pcm: np.ndarray, sr: int) -> None:
        """Install a decoded whole-track buffer and reset to the start.

        Reuses the open output stream when the new track's sample rate and
        channel count match the current one, so back-to-back tracks in a
        same-format library start without re-paying the stream-open latency.
        """
        pcm = np.ascontiguousarray(pcm, dtype=np.float32)
        if pcm.ndim == 1:
            pcm = pcm.reshape(-1, 1)
        if pcm.shape[1] == 1:
            # Upmix mono to stereo so the output stream is always 2-channel
            # (more reliable across output devices than mono).
            pcm = np.repeat(pcm, 2, axis=1)
        new_sr = int(sr)
        new_ch = pcm.shape[1]
        if self._stream is not None and (new_sr != self._sr or new_ch != self._channels):
            self._close_stream()
        with self._lock:
            self._playing = False
            self._reached_end = False
            self._pcm = pcm
            self._sr = new_sr
            self._channels = new_ch
            self._total_frames = pcm.shape[0]
            self._pos = 0
            # A fresh track must never inherit the previous track's loop.
            self._loop_enabled = False
            self._loop_start = 0
            self._loop_end = 0
        self._state = "stopped"
        self.durationChanged.emit(self.duration_ms())

    def unload(self) -> None:
        """Stop playback, release the audio device, and drop the buffer.

        Used when clearing/removing tracks so RAM is freed and any USB drive the
        file lived on can be ejected (the file handle is already gone — we decode
        to memory up front — but this releases the output device too).
        """
        self._close_stream()
        with self._lock:
            self._pcm = None
            self._sr = 0
            self._total_frames = 0
            self._pos = 0
            self._reached_end = False
            self._loop_enabled = False
            self._loop_start = 0
            self._loop_end = 0
        self._state = "stopped"

    def has_buffer(self) -> bool:
        return self._pcm is not None and self._sr > 0

    def is_playing(self) -> bool:
        return self._state == "playing"

    def is_paused(self) -> bool:
        return self._state == "paused"

    def set_volume(self, volume: float) -> None:
        with self._lock:
            self._volume = max(0.0, min(1.0, float(volume)))

    def sample_rate(self) -> int:
        with self._lock:
            return self._sr

    def recent_mono(self, n: int) -> np.ndarray | None:
        """The last *n* frames behind the playhead, mono-mixed (for visualizers).

        Returns None when no buffer is loaded. Zero-pads at the head near the
        start of a track so callers always get exactly *n* samples. The slice
        is copied out under the lock, so the audio callback can't swap the
        buffer mid-read.
        """
        with self._lock:
            pcm = self._pcm
            pos = self._pos
        if pcm is None or n <= 0:
            return None
        end = max(0, min(pos, pcm.shape[0]))
        start = max(0, end - n)
        mono = pcm[start:end].mean(axis=1).astype(np.float32, copy=False)
        if len(mono) < n:
            mono = np.concatenate([np.zeros(n - len(mono), dtype=np.float32), mono])
        return mono

    def duration_ms(self) -> int:
        with self._lock:
            if self._sr <= 0:
                return 0
            return int(round(self._total_frames * 1000 / self._sr))

    def current_ms(self) -> int:
        with self._lock:
            if self._sr <= 0:
                return 0
            return int(self._pos * 1000 / self._sr)

    def seek_ms(self, ms: int) -> None:
        """Move the play head. Instant — just clamps an integer frame offset."""
        with self._lock:
            if self._pcm is None or self._sr <= 0:
                return
            f = int(round(ms / 1000.0 * self._sr))
            self._pos = max(0, min(f, self._total_frames - 1))
            self._reached_end = False
            new_ms = int(self._pos * 1000 / self._sr)
        # Report the new position immediately. While playing the position timer
        # would emit this anyway, but while paused/stopped the timer is stopped,
        # so without this a scrub (e.g. the slice zoom view) would move the play
        # head silently and the UI playhead/waveform would never follow.
        self.positionChanged.emit(new_ms)

    # ----------------------------------------------------------------- A-B loop

    def _ms_to_frame(self, ms: int) -> int:
        """Convert ms to a frame index. Caller must hold ``self._lock``."""
        return int(round(ms / 1000.0 * self._sr))

    def set_loop_bounds(self, start_ms: int, end_ms: int) -> None:
        """Set the loop region (instant, gapless). Does not move the playhead,
        so free seeking still works; only the callback wraps within the bounds."""
        with self._lock:
            if self._pcm is None or self._sr <= 0:
                return
            n = self._total_frames
            s = max(0, min(self._ms_to_frame(start_ms), n - 1))
            e = max(s + 1, min(self._ms_to_frame(end_ms), n))
            self._loop_start = s
            self._loop_end = e

    def set_loop_enabled(self, enabled: bool) -> None:
        """Turn A-B looping on/off. On enable, if the playhead is outside the
        loop region it snaps to the start marker so playback enters cleanly."""
        with self._lock:
            self._loop_enabled = bool(enabled)
            if enabled and self._loop_end > self._loop_start:
                if self._pos < self._loop_start or self._pos >= self._loop_end:
                    self._pos = self._loop_start
                self._reached_end = False

    def loop_bounds_ms(self) -> tuple[int, int]:
        with self._lock:
            if self._sr <= 0:
                return 0, 0
            end = self._loop_end if self._loop_end > 0 else self._total_frames
            return (
                int(self._loop_start * 1000 / self._sr),
                int(end * 1000 / self._sr),
            )

    # ---------------------------------------------------------------- transport

    def play(self) -> bool:
        """Start or resume playback. Returns False if it can't start."""
        if not self.has_buffer():
            return False
        with self._lock:
            if self._pos >= self._total_frames:
                self._pos = 0
            self._reached_end = False
            sr = self._sr
            ch = self._channels
        if not self._ensure_stream(sr, ch):
            return False
        with self._lock:
            self._playing = True
        self._state = "playing"
        if not self._pos_timer.isActive():
            self._pos_timer.start()
        self.stateChanged.emit(True)
        return True

    def pause(self) -> None:
        """Pause but keep position and the primed stream for an instant resume."""
        with self._lock:
            self._playing = False
        self._state = "paused"
        if self._pos_timer.isActive():
            self._pos_timer.stop()
        self.stateChanged.emit(False)

    def stop(self) -> None:
        """Stop and rewind to the start (stream stays open and primed)."""
        with self._lock:
            self._playing = False
            self._pos = 0
            self._reached_end = False
        self._state = "stopped"
        if self._pos_timer.isActive():
            self._pos_timer.stop()
        self.stateChanged.emit(False)
        self.positionChanged.emit(0)

    def _ensure_stream(self, sr: int, ch: int) -> bool:
        """Open the output stream if needed. Returns False on failure.

        Tries the preferred (low-latency) device first, then PortAudio's default
        device, so a WASAPI quirk on some machine can never break playback.
        """
        if self._stream is not None:
            return True
        for extra in output_stream_kwargs():
            try:
                self._stream = sd.OutputStream(
                    samplerate=sr,
                    blocksize=_BLOCK,
                    channels=ch,
                    dtype="float32",
                    callback=self._callback,
                    **extra,
                )
                self._stream.start()
                return True
            except Exception as e:  # noqa: BLE001 — never let device probing break playback
                logger.warning("PlayerEngine stream open failed (%r): %s", extra, e)
                self._stream = None
        return False

    def _close_stream(self) -> None:
        with self._lock:
            self._playing = False
        if self._pos_timer.isActive():
            self._pos_timer.stop()
        if self._stream is not None:
            stream, self._stream = self._stream, None
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    # -------------------------------------------------------------- audio thread

    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ARG002
        with self._lock:
            playing = self._playing
            pcm = self._pcm
            total = self._total_frames
            pos = self._pos
            vol = self._volume
            loop = self._loop_enabled
            lstart = self._loop_start
            lend = self._loop_end if self._loop_end > 0 else total

        if not playing or pcm is None:
            outdata.fill(0.0)
            return

        if loop and lend > lstart:
            # Loop branch: play [lstart, lend), wrapping at the end marker. Never
            # sets `_reached_end` — looping never ends the track or auto-advances.
            if pos < lstart or pos >= lend:
                pos = lstart
            filled = 0
            while filled < frames:
                chunk = min(frames - filled, lend - pos)
                outdata[filled : filled + chunk] = pcm[pos : pos + chunk]
                filled += chunk
                pos += chunk
                if pos >= lend:
                    pos = lstart
            if vol != 1.0:
                outdata *= vol
            with self._lock:
                self._pos = pos
            return

        # Non-loop branch: play through to the end, then signal `finished`.
        if pos >= total:
            outdata.fill(0.0)
            return
        n = min(frames, total - pos)
        outdata[:n] = pcm[pos : pos + n]
        if n < frames:
            outdata[n:].fill(0.0)
        if vol != 1.0:
            outdata[:n] *= vol
        pos += n
        reached = pos >= total
        with self._lock:
            self._pos = pos
            if reached:
                self._playing = False
                self._reached_end = True

    # ---------------------------------------------------------------- GUI thread

    def _tick(self) -> None:
        with self._lock:
            reached = self._reached_end
        if reached:
            with self._lock:
                self._reached_end = False
            self._state = "stopped"
            self._pos_timer.stop()
            self.positionChanged.emit(self.duration_ms())
            self.stateChanged.emit(False)
            self.finished.emit()
            return
        self.positionChanged.emit(self.current_ms())
