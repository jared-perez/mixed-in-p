"""Which sample of an output stream is reaching the speaker right now.

A stream's own position counter says what has been *rendered*, and it moves
in whole blocks: at the 2048-frame block the player and metronome use, it
jumps 46 ms at a time, and whatever it reads is already one device latency
ahead of the ear. That is fine for a playhead drawn at 30 fps and wrong for
anything that has to line two streams up — "Mark on beat" puts a marker
where the track will be when the metronome's next click is heard, so both
answers have to be about the *speaker*, and to the millisecond.

So the callback records one fact per block: the stream sample that starts
this block, and the ``perf_counter`` moment that sample will be heard
(PortAudio's ``outputBufferDacTime``, carried onto ``perf_counter`` through
the callback's own ``currentTime``). Everything between blocks is then a
straight line at the sample rate. ``perf_counter`` is the common clock
because two streams' PortAudio clocks are not promised to be the same one.

Some host APIs report no DAC time (it arrives as 0); the stream's advertised
latency, set by the owner once it opens, stands in for it there.
"""

from __future__ import annotations

import time


class StreamClock:
    """Maps a ``perf_counter`` moment to the stream sample heard at it.

    :meth:`mark` runs on the audio thread and only rebinds one tuple, which is
    atomic under the GIL — no lock, no allocation worth the name. Everything
    else runs on the GUI thread.
    """

    def __init__(self, sr: int) -> None:
        self.sr = sr
        # Fallback latency (seconds) for a host API that reports no DAC time.
        self._latency = 0.0
        # (first sample of the latest block, perf_counter when it is heard,
        # frames in that block), or None until a block has been rendered
        # since the last reset.
        self._anchor: tuple[float, float, int] | None = None

    def set_latency(self, seconds) -> None:
        """The stream's advertised output latency, for when there is no DAC
        time. Anything that is not a number (a test double) counts as 0."""
        try:
            self._latency = max(0.0, float(seconds))
        except (TypeError, ValueError):
            self._latency = 0.0

    def reset(self) -> None:
        """Forget the anchor — the stream stopped, or its position jumped."""
        self._anchor = None

    def mark(self, block_start_sample: float, time_info, frames: int = 0) -> None:
        """Audio thread: the *frames*-long block starting at
        *block_start_sample* is being rendered now."""
        now = time.perf_counter()
        latency = self._latency
        try:
            dac = time_info.outputBufferDacTime
            current = time_info.currentTime
            if dac > 0.0 and current > 0.0 and dac >= current:
                latency = dac - current
        except AttributeError:
            pass
        self._anchor = (float(block_start_sample), now + latency, int(frames))

    def sample_at(self, when: float) -> float | None:
        """The stream sample heard at ``perf_counter`` moment *when*, or None
        before the first block."""
        anchor = self._anchor
        if anchor is None:
            return None
        sample, heard_at, _ = anchor
        return sample + (when - heard_at) * self.sr

    def lead_samples(self, when: float) -> float | None:
        """How many samples past the one heard at *when* have already been
        rendered — the device buffer, which nothing can change any more."""
        anchor = self._anchor
        if anchor is None:
            return None
        sample, heard_at, frames = anchor
        return sample + frames - (sample + (when - heard_at) * self.sr)
