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

from ..workers.waveform_worker import mono_mix
from .loop_player import _BLOCK, _POS_TIMER_MS, UnderrunLog, output_stream_kwargs
from .stream_clock import StreamClock

logger = logging.getLogger(__name__)


class PlayerEngine(QObject):
    """Plays an in-memory PCM buffer through to the end, with instant seeking."""

    positionChanged = Signal(int)  # current playback position, ms
    durationChanged = Signal(int)  # total track length, ms
    stateChanged = Signal(bool)    # True = playing, False = paused/stopped
    finished = Signal()            # playback reached the end of the track
    seeked = Signal()              # the play head was moved, not merely advanced

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
        # A jump the callback makes at an exact frame — see schedule_jump_ms.
        # (at_frame, to_frame, enable_loop) or None; `_jumped` tells the GUI
        # timer one fired, so it can emit `seeked` off the audio thread.
        self._jump: tuple[int, int, bool] | None = None
        self._jumped: bool = False
        self._underruns = UnderrunLog("Player stream")
        # When each played block reaches the speaker — see heard_ms_at. Reset
        # under the lock wherever _pos jumps, so an anchor never outlives the
        # position it was taken from.
        self._clock = StreamClock(44100)

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
            self._clock.sr = new_sr
            self._clock.reset()
            self._jump = None
            # A fresh track must never inherit the previous track's loop.
            self._loop_enabled = False
            self._loop_start = 0
            self._loop_end = 0
        self._state = "stopped"
        self.durationChanged.emit(self.duration_ms())

    def unload(self) -> None:
        """Stop playback, release the audio device, and drop the buffer.

        Removing or clearing tracks deliberately does NOT call this: the
        playing track plays on after its row goes. Nothing here holds the file
        or its drive anyway — we decode to memory up front — so there is no
        eject to unblock; this releases the output device and the buffer.
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
        mono = mono_mix(pcm[start:end])
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

    def heard_ms_at(self, when: float) -> float | None:
        """Track position (ms, fractional) heard at ``perf_counter`` moment
        *when*, or None when nothing is playing or no block has been played
        since the position last jumped.

        Unlike :meth:`current_ms`, which is what has been *rendered* and moves
        a block at a time, this is what the ear is on — see StreamClock. Past
        a loop's end marker it runs straight on rather than wrapping; the
        caller knows the loop bounds and wraps it.
        """
        with self._lock:
            if not self._playing or self._sr <= 0:
                return None
        sample = self._clock.sample_at(when)
        if sample is None:
            return None
        return sample * 1000.0 / self._clock.sr

    def render_lead_ms(self, when: float) -> float | None:
        """How far (ms) the rendered audio runs ahead of what is heard at
        ``perf_counter`` moment *when* — a jump scheduled any sooner than this
        is at a frame already handed to the device, too late to take."""
        lead = self._clock.lead_samples(when)
        return None if lead is None else lead * 1000.0 / self._clock.sr

    def schedule_jump_ms(self, at_ms: float, to_ms: int, enable_loop: bool = False) -> None:
        """Jump the play head to *to_ms* the moment playback reaches *at_ms*.

        Done inside the callback, at that exact frame, which is what lets the
        slicer's retrigger and loop start land on a metronome click: a seek
        from the GUI thread would be heard up to a block plus a timer tick
        late. *enable_loop* switches looping on at the same frame rather than
        now, since set_loop_enabled would snap the head to the loop start
        straight away. Replaces any jump already pending; a seek, pause,
        stop or new track cancels it. A frame playback never reaches (past
        the track's end) simply never fires.
        """
        with self._lock:
            if self._pcm is None or self._sr <= 0:
                return
            n = self._total_frames
            at = max(0, int(round(at_ms / 1000.0 * self._sr)))
            to = max(0, min(self._ms_to_frame(to_ms), n - 1))
            # A loop start already waiting is never downgraded: a retrigger
            # pressed before its click still has to switch the loop on.
            if self._jump is not None and self._jump[2]:
                enable_loop = True
            self._jump = (at, to, bool(enable_loop))

    def cancel_jump(self, loop_start_only: bool = False) -> None:
        """Drop the pending jump — or, with *loop_start_only*, only one that
        would switch looping on (Loop turned off before its click)."""
        with self._lock:
            if self._jump is not None and (not loop_start_only or self._jump[2]):
                self._jump = None

    def has_pending_jump(self) -> bool:
        with self._lock:
            return self._jump is not None

    @property
    def loop_enabled(self) -> bool:
        """Whether the engine is looping now — which, while a loop start is
        waiting on a click, the slicer's Loop switch already claims."""
        with self._lock:
            return self._loop_enabled

    def seek_ms(self, ms: int) -> None:
        """Move the play head. Instant — just clamps an integer frame offset."""
        with self._lock:
            if self._pcm is None or self._sr <= 0:
                return
            f = int(round(ms / 1000.0 * self._sr))
            self._pos = max(0, min(f, self._total_frames - 1))
            self._clock.reset()
            self._jump = None
            self._reached_end = False
            new_ms = int(self._pos * 1000 / self._sr)
        # Report the new position immediately. While playing the position timer
        # would emit this anyway, but while paused/stopped the timer is stopped,
        # so without this a scrub (e.g. the slice zoom view) would move the play
        # head silently and the UI playhead/waveform would never follow.
        self.positionChanged.emit(new_ms)
        # Separate from positionChanged, which also fires on ordinary playback:
        # the beat visualization has to throw away the evidence it accumulated
        # about where we *were*, and this is the one place every seek funnels
        # through (the transport slider and the slice section both call here).
        self.seeked.emit()

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
                    self._clock.reset()
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
            self._clock.reset()
            self._jump = None
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
            self._clock.reset()
            self._jump = None
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
                self._clock.set_latency(getattr(self._stream, "latency", 0.0))
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
        self._underruns.count(status)
        with self._lock:
            playing = self._playing
            pcm = self._pcm
            total = self._total_frames
            pos = self._pos
            vol = self._volume
            loop = self._loop_enabled
            lstart = self._loop_start
            lend = self._loop_end if self._loop_end > 0 else total
            jump = self._jump
            if playing and pcm is not None:
                # The walk below starts an out-of-range head at the loop's
                # start marker, so that is the sample this block opens on.
                heard = lstart if loop and lend > lstart and not lstart <= pos < lend else pos
                self._clock.mark(heard, time_info, frames)

        if not playing or pcm is None:
            outdata.fill(0.0)
            return

        # One walk for both modes: copy up to the next boundary — the loop's
        # end marker, the track's end, or a scheduled jump — and act on it.
        # Looping never sets `_reached_end`, so it never ends the track or
        # auto-advances.
        looping = loop and lend > lstart
        if looping and not lstart <= pos < lend:
            pos = lstart
        fired = False
        filled = 0
        while filled < frames:
            stop = lend if looping else total
            if jump is not None and not fired and pos <= jump[0] < stop:
                stop = jump[0]
            chunk = min(frames - filled, stop - pos)
            if chunk > 0:
                outdata[filled : filled + chunk] = pcm[pos : pos + chunk]
                filled += chunk
                pos += chunk
            if jump is not None and not fired and pos == jump[0]:
                fired = True
                pos = jump[1]
                if jump[2]:
                    loop = True
                    looping = lend > lstart
            elif looping and pos >= lend:
                pos = lstart
            elif not looping and pos >= total:
                break
        if filled < frames:
            outdata[filled:].fill(0.0)
        if vol != 1.0:
            outdata[:filled] *= vol
        reached = not looping and pos >= total
        with self._lock:
            self._pos = pos
            if fired and self._jump is jump:
                self._jump = None
                self._jumped = True
                if jump[2]:
                    self._loop_enabled = True
            if reached:
                self._playing = False
                self._reached_end = True

    # ---------------------------------------------------------------- GUI thread

    def _tick(self) -> None:
        self._underruns.report()
        with self._lock:
            reached = self._reached_end
            jumped, self._jumped = self._jumped, False
        if jumped:
            # A scheduled jump moved the head as surely as a seek does, and
            # the beat visual has to drop what it knew about where we were.
            self.seeked.emit()
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
