"""Shared sounddevice output-stream helpers.

Originally the home of the slicer's gapless ``LoopPlayer``; that A-B looping now
lives in :class:`PlayerEngine` (which grew optional loop bounds) so the player
runs a single engine. What remains here are the stream constants and the
low-latency device-selection helper, imported by ``player_engine`` and
``keyboard_panel`` for their own ``sounddevice`` streams.
"""

from __future__ import annotations

import sys

import sounddevice as sd

# Audio thread block size. 2048 frames @ 44.1 kHz ≈ 46 ms — a deliberately
# roomy buffer so the Python output callback (which must take the GIL each
# block) can still meet its deadline when a track decode or a background
# analysis/waveform worker is briefly contending for the GIL. The extra latency
# vs. 1024 is imperceptible for start/stop/seek in a prep player, and it buys
# real headroom against dropouts. Used by PlayerEngine (keyboard_panel has its
# own smaller BLOCK_SIZE, since live key presses want lower note latency).
_BLOCK = 2048
# Position UI refresh interval (ms). ~30 fps for smooth playhead motion.
_POS_TIMER_MS = 33


def output_stream_kwargs() -> list[dict]:
    """Ordered ``OutputStream`` kwargs to try, lowest-latency first.

    On Windows the default PortAudio host API is MME, whose minimum output
    latency is ~190 ms — that's the quarter-second lag before audio starts.
    This prefers the WASAPI host API instead (~45 ms), with shared-mode
    ``auto_convert`` so a 44.1 kHz file still plays on a device whose mix
    format is 48 kHz (otherwise WASAPI shared mode raises "Invalid sample
    rate"). The list always ends with ``{}`` (PortAudio's default device,
    MME), so if WASAPI can't open for any reason playback still works.

    No-op off Windows: returns ``[{}]``, so CoreAudio/ALSA keep their
    already-low-latency defaults and Mac/Linux behaviour is unchanged.
    """
    if sys.platform != "win32":
        return [{}]
    candidates: list[dict] = []
    try:
        for api in sd.query_hostapis():
            if "wasapi" in api["name"].lower():
                dev = api.get("default_output_device", -1)
                if dev is not None and dev >= 0:
                    candidates.append(
                        {
                            "device": dev,
                            "latency": "low",
                            "extra_settings": sd.WasapiSettings(auto_convert=True),
                        }
                    )
                break
    except Exception:  # noqa: BLE001 — never let device probing break playback
        pass
    candidates.append({})  # PortAudio default (MME) — always openable
    return candidates

