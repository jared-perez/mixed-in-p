"""Analog oscilloscope: a green phosphor beam with glow and persistence.

The **popout** face of the ``oscilloscope`` mode. The backdrop keeps the chunky
152x64 retro grid that :class:`~.vis_canvas.VisRenderer._render_scope` draws;
this is the same mode id wearing a different picture in the other host, the
mirror image of what fire does (one mode, backdrop only). Nothing about the
menu, the mode id or the config set changes for it.

It is not a polyline. The whole look — bright slow segments, a dim thread on
the steep slopes, a soft halo, decaying ghosts of the last few frames — falls
out of one float32 *phosphor buffer* the size of the host:

1. multiply the buffer by a decay (that is the persistence),
2. stamp the beam path into it additively, spread between each point's two
   vertical neighbours,
3. blur it once for the line's softness and add a 4x-decimated, blurred,
   re-upsampled copy back for the wide halo,
4. look the result up in a black -> green -> white ramp.

The obvious alternative — drawing the polyline three or four times with wide
antialiased round-cap pens under ``CompositionMode_Plus`` — was measured and is
dead on arrival: 25.8 ms for 480 points at 1216x512 and 246 ms at 2400x1200,
against a 16 ms frame. The wide AA pens are the cost, not the persistence.
Numbers for this pipeline are in :data:`_POPOUT_CAP_PX` below.

Beam brightness needs no code of its own: the path is sampled at a fixed number
of points per frame, so a point *is* a fixed slice of time, and scattering them
into the buffer puts more of them per pixel where the beam moves slowly. That
is the analog behaviour, for free. :data:`_BEAM_K` only sharpens the contrast
the scatter already produces.

No audio analysis lives here — :meth:`AnalogScopeScene.render` takes a block of
mono samples and the sample rate, and :class:`~.vis_canvas.VisRenderer` decides
when to call it.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QColor, QImage

# Render size. Cost is linear in pixels and the cap is a frame budget, exactly
# as it is for the two tunnels. Measured on the M-series Mac against the
# shipped pipeline, median of 30 frames, for the two kinds of content that
# cost differently: a bass line, where nearly every beam segment stays inside
# one pixel and the span fill is skipped altogether, and a bright, noisy mix,
# where it runs over the whole frame (see _stamp).
#
#                        bass    bright
#   912x384   (0.35 Mpx)  2.3 ms   3.1 ms
#   1216x512  (0.62 Mpx)  4.0 ms   5.6 ms   <- default popout, Retina, native
#   1250x720  (0.90 Mpx)  5.8 ms   7.7 ms   <- the cap: half a 16 ms frame
#   1600x672  (1.08 Mpx)  7.0 ms   9.2 ms
#   2400x1200 (2.88 Mpx) 18.4 ms  24.4 ms   <- would drop frames at 60 fps
#
# The popout runs at 60 fps (see VisRenderer.frame_ms), so the ceiling is half
# of 16 ms *for the expensive kind of music*, not for the cheap kind — which
# lands at ~0.9 Mpx. The default popout window renders native and the cap only
# bites once the window grows; a soft glow field upscales beautifully under
# SmoothPixmapTransform, unlike the tunnels' wireframe, which is what made
# theirs grow. The area is capped rather than a width and a height because cost
# follows pixels, not shape.
#
# The backdrop never reaches this scene today (VisRenderer routes here only
# when the host asked as the popout), but it gets a cap anyway so the split is
# stated rather than implied: its budget is the *host* — repainting the
# playlist rows behind the frame is ~11 ms on its own.
_POPOUT_CAP_PX = 900_000
_BACKDROP_CAP_PX = 620_000
_MIN_W, _MIN_H = 64, 32
# For a host that never calls set_target_size at all — scripts/vis_sheet.py
# does call it, but a bare AnalogScopeScene() must still render.
_DEFAULT_SIZE = (1216, 512)

# How much of the block is on screen. 1024 samples is ~23 ms at 44.1 kHz, so a
# 100 Hz tone shows a couple of cycles and a bass line reads as a wave rather
# than as a wall. The rest of the 2048-sample block is the trigger's search
# margin (see find_trigger).
_WINDOW = 1024
# Path points per horizontal pixel. The proof of concept stamped 4x and one
# pixel per point, and a steep transient out-ran it and dotted the line; 8x
# plus the vertical split below closes that, and the extra stamp cost is noise
# next to the blurs.
_OVERSAMPLE = 8

# Persistence, as a *time* constant. A bare per-frame factor is only right at
# one frame rate: the popout's 16 ms and anything vis_sheet drives would be
# different visuals wearing the same number. set_frame_interval converts it.
_PERSIST_MS = 50.0
# How hard the fast slopes dim, from 1.0 (exactly energy-conserving: a row's
# brightness is 1/S of a stationary beam's, where S is the rows that column's
# beam crosses) down to 0.0 (no speed contrast at all). Pure conservation is
# what the physics says and it is too much: a 3 kHz tone crosses ~150 rows a
# column, which puts its trace at 0.7% of a flat top — a real scope's phosphor
# and a real eye both compress that, and without the compression a bright track
# renders as an empty screen. Measured by eye against a treble-heavy signal.
_BEAM_GAMMA = 0.5
# What a *stationary* trace settles at, not what one frame deposits. Each frame
# adds S and keeps a fraction d of what was there, so a still beam converges on
# S / (1 - d): left alone, lengthening the persistence would brighten the whole
# trace to white as a side effect, and 33 ms frames would run 1.75x dimmer than
# 16 ms ones for the same second of audio. Scaling the stamp by (1 - d) takes
# both couplings out, which is what makes _PERSIST_MS a pure trail-length knob
# and what makes the two hosts render the same picture.
_BEAM_GAIN = 0.51
# Where overlapping passes stop getting brighter. Without a ceiling a held
# note's flat top accumulates without bound and the LUT pins to white across
# the whole trace; with one it saturates to a white core and stays there.
_CEILING = 1.6
# The halo, built at 1/_BLOOM_DECIMATE scale and put back (see _add_bloom).
_BLOOM_DECIMATE = 4
_BLOOM_WEIGHT = 3.0  # how much of the glow is the wide field, not the line
_BLOOM_BLURS = 6  # at a quarter scale, so ~24 px of radius for 1/16th the work
# Full-resolution blur passes over the frame — the line's own softness. One of
# them runs *after* the halo has been added, which is what dissolves the blocks
# the upsample leaves behind; see render().
_LINE_BLURS = 2
# Buffer intensity -> LUT index. The ramp below starts heading for white at
# _LUT_CORE, so this decides how much of a pass reads as core and how much as
# halo. 1.0 puts a saturated flat trace at the top of the ramp — measured, not
# assumed: the buffer's own ceiling and the blurs together land its peak at
# ~1.1 before this is applied.
_DISPLAY_GAIN = 1.0

# Phosphor green, fixed rather than following the waveform-colour setting: this
# is the one visual whose whole subject is a green CRT, and "analog scope" *is*
# green phosphor. set_color therefore exists and is deliberately ignored; if
# that ever grates, deriving the ramp from the colour is the three lines
# _fire_palette already spells out in vis_canvas.
_PHOSPHOR = (51, 255, 102)
_LUT_CORE = 0.78  # index fraction at which the ramp starts heading for white
_LUT_RISE = 0.45  # index fraction over which it reaches full phosphor
_ALPHA_GAIN = 2.5  # so the faintest halo is faint rather than a grey wash


def build_lut(color: tuple[int, int, int] = _PHOSPHOR) -> np.ndarray:
    """256 BGRA rows: black -> *color* -> white, alpha following intensity.

    Straight (non-premultiplied) alpha, like the fire renderer's, so the
    popout's black fill and the playlist grey both composite correctly.
    """
    t = np.linspace(0.0, 1.0, 256)
    up = np.clip(t / _LUT_RISE, 0.0, 1.0)[:, None]
    core = np.clip((t - _LUT_CORE) / (1.0 - _LUT_CORE), 0.0, 1.0)[:, None]
    base = np.array(color, dtype=np.float64)
    rgb = base * up
    rgb = rgb + (255.0 - rgb) * core
    lut = np.empty((256, 4), dtype=np.uint8)
    lut[:, 0] = rgb[:, 2].astype(np.uint8)  # B
    lut[:, 1] = rgb[:, 1].astype(np.uint8)  # G
    lut[:, 2] = rgb[:, 0].astype(np.uint8)  # R
    lut[:, 3] = (np.clip(t * _ALPHA_GAIN, 0.0, 1.0) * 255).astype(np.uint8)
    return lut


def find_trigger(samples: np.ndarray, target: int, window: int = _WINDOW) -> int:
    """Where the trace should start: a rising zero crossing near *target*.

    This is what makes it read as an *oscilloscope* — a wave standing still —
    rather than as noise scrolling past. Only crossings early enough to leave
    *window* samples behind them are eligible, which is the search margin the
    block carries over what it displays.

    *target* is where the previous frame's trigger has drifted to by now (its
    index, less one frame of samples), so the choice is "the same moment in the
    wave, one frame on". Snapping to the *nearest* crossing rather than to the
    first is what keeps a waveform with several rising crossings per cycle from
    swapping which one it stands on, frame to frame.

    Silence or a DC block has no rising crossing at all: the clamped target
    comes back, and the caller draws a flat line — which is what a real scope
    shows, and brightly, since the beam is not moving.
    """
    limit = len(samples) - window
    if limit <= 0:
        return 0
    target = int(np.clip(target, 0, limit))
    seg = samples[: limit + 1]
    rising = np.flatnonzero((seg[:-1] <= 0.0) & (seg[1:] > 0.0))
    if rising.size == 0:
        return target
    return int(rising[np.abs(rising - target).argmin()])


def _blur121(buf: np.ndarray, passes: int) -> np.ndarray:
    """Separable 1-2-1 blur, *passes* times in each direction.

    Edges keep their own value rather than being darkened toward an implicit
    black border, which would draw a dark frame around a full-width trace.
    """
    out = buf
    for _ in range(passes):
        blurred = out.copy()
        blurred[:, 1:-1] = 0.25 * out[:, :-2] + 0.5 * out[:, 1:-1] + 0.25 * out[:, 2:]
        out = blurred
        blurred = out.copy()
        blurred[1:-1, :] = 0.25 * out[:-2, :] + 0.5 * out[1:-1, :] + 0.25 * out[2:, :]
        out = blurred
    return out


class AnalogScopeScene:
    """The phosphor buffer, its image, and the beam that writes into it."""

    def __init__(self) -> None:
        self._lut = build_lut()
        # The same table packed one pixel to a word. Indexing a (256, 4) uint8
        # table with an (H, W) index gathers four separate bytes per pixel and
        # measures **5.0 ms** at 1600x672; the (256,) uint32 view of it gathers
        # one word and measures **0.8 ms** for a byte-identical result. That is
        # the difference between fitting a 60 fps frame and not.
        self._lut32 = self._lut.view(np.uint32).reshape(256)
        self._decay = 0.0
        self._stamp_scale = 1.0
        self._frame_ms = 1000.0 / 60.0
        self.set_frame_interval(self._frame_ms)
        width, height = _DEFAULT_SIZE
        self._buf = np.zeros((height, width), dtype=np.float32)
        # One row taller: a span's "one past the end" marker can name row H.
        self._fill = np.zeros((height + 1, width), dtype=np.float32)
        self._image = QImage(width, height, QImage.Format.Format_ARGB32)
        self._trigger = 0
        self.reset()

    # ── Public API ─────────────────────────────────────────────────────────

    def image(self) -> QImage:
        return self._image

    def set_color(self, color: QColor | str) -> None:
        """Ignored on purpose — see :data:`_PHOSPHOR`. Present so the renderer
        can forward the setting to every scene without asking which ones care.
        """

    def set_frame_interval(self, frame_ms: float) -> None:
        """Re-derive the persistence decay from the host's tick rate.

        Rate state only: :meth:`reset` must not touch it, because vis_sheet
        sets the interval *before* the mode (which is what calls reset).
        """
        if frame_ms <= 0:
            return
        self._frame_ms = float(frame_ms)
        self._decay = float(np.exp(-frame_ms / _PERSIST_MS))
        self._stamp_scale = 1.0 - self._decay

    def reset(self) -> None:
        """Forget the picture — the trails and where the beam was triggering."""
        self._buf[:] = 0.0
        self._trigger = 0
        self._image = QImage(
            self._buf.shape[1], self._buf.shape[0], QImage.Format.Format_ARGB32
        )
        self._image.fill(0)

    def set_target_size(self, width: int, height: int, popout: bool = False) -> None:
        """Match the buffer to the host's shape and size, capped by frame cost.

        *width* and *height* are **device** pixels, read from the widget that
        paints rather than from the primary screen — the popout can be dragged
        onto a display with a different ratio mid-session, and VisCanvas.feed
        re-reads it every frame.

        The aspect is held exactly and the buffer is never made larger than the
        host asked for: there is nothing to gain from rendering a glow field
        the host then shrinks. Reallocating drops the trails, which is fine —
        both tunnels lose their stars on a resize too.
        """
        if width <= 0 or height <= 0:
            return
        cap = _POPOUT_CAP_PX if popout else _BACKDROP_CAP_PX
        scale = min(1.0, float(np.sqrt(cap / float(width * height))))
        target_w = max(_MIN_W, int(round(width * scale)))
        target_h = max(_MIN_H, int(round(height * scale)))
        if (target_w, target_h) == (self._buf.shape[1], self._buf.shape[0]):
            return
        self._buf = np.zeros((target_h, target_w), dtype=np.float32)
        self._fill = np.zeros((target_h + 1, target_w), dtype=np.float32)
        self._image = QImage(target_w, target_h, QImage.Format.Format_ARGB32)
        self._image.fill(0)

    def render(self, samples: np.ndarray | None, sr: int = 44100) -> QImage:
        """Advance one frame of phosphor and paint it.

        *samples* is a mono block; ``None`` (which is what the popout feeds
        while paused) means silence, and a scope shows silence as a bright flat
        line, not as a frozen frame — the decay keeps running either way.
        """
        buf = self._buf
        buf *= self._decay
        self._stamp(samples, sr)
        np.clip(buf, 0.0, _CEILING, out=buf)
        # One blur pass, then the halo, then the rest — rather than all the
        # passes and then the halo. The halo comes back up from a quarter-scale
        # image, so it arrives carrying the seams of that upsample; spending
        # the last full-resolution pass *on the sum* is what finishes them off,
        # and it costs nothing, because the line wanted that pass anyway.
        glow = _blur121(buf, 1)
        self._add_bloom(glow, buf)
        glow = _blur121(glow, _LINE_BLURS - 1)
        self._paint(glow)
        return self._image

    # ── Internals ──────────────────────────────────────────────────────────

    def _stamp(self, samples: np.ndarray | None, sr: int) -> None:
        """Lay one frame's beam path into the phosphor buffer.

        The path is drawn as *segments*, not as points, and that is not a
        refinement — it is the difference between a square wave having vertical
        edges and not having them. Points are sampled at a fixed rate in time,
        so a step the audio takes in one sample is a jump of hundreds of rows
        between two neighbouring points: at 8x oversample they land ~70 rows
        apart, which no amount of splatting between a point's two vertical
        neighbours can join. A hard-clipped synth stab rendered as three
        disconnected horizontal bars.

        A segment spends its energy over every row it crosses, so the brightness
        is exactly inversely proportional to the beam's speed — the CRT's own
        behaviour, now arithmetic rather than a side effect of where the points
        happened to land, and with no second speed term needed on top.
        """
        height, width = self._buf.shape
        if samples is None or len(samples) == 0:
            samples = np.zeros(_WINDOW, dtype=np.float32)
        window = min(_WINDOW, len(samples))
        # Where last frame's trigger has drifted to in this block. The block is
        # the last N samples up to the play position, so it has advanced by one
        # frame of audio since we last looked.
        hop = max(sr, 1) * self._frame_ms / 1000.0
        self._trigger = find_trigger(samples, int(round(self._trigger - hop)), window)
        trace = samples[self._trigger : self._trigger + window]

        n_pts = _OVERSAMPLE * width
        src = np.linspace(0.0, len(trace) - 1.0, n_pts)
        values = np.interp(src, np.arange(len(trace), dtype=np.float64), trace)
        # +1 at the top, -1 at the bottom, held a hair inside the frame so a
        # clipping track draws a line rather than indexing off the end.
        ys = (height - 1) * 0.5 * (1.0 - np.clip(values, -1.0, 1.0))
        np.clip(ys, 0.0, height - 1.0001, out=ys)
        cols = np.minimum(np.arange(1, n_pts) // _OVERSAMPLE, width - 1)

        low = np.minimum(ys[:-1], ys[1:])
        high = np.maximum(ys[:-1], ys[1:])
        span = high - low
        # Every segment is the same slice of time, so every segment carries the
        # same energy; see _BEAM_GAIN for why the frame rate scales it.
        energy = _BEAM_GAIN * self._stamp_scale

        # Segments that stay inside a pixel: split between the two rows they sit
        # between, so a slowly drifting line glides instead of stepping.
        flat = span < 1.0
        if flat.any():
            mid = 0.5 * (ys[:-1] + ys[1:])[flat]
            flat_cols = cols[flat]
            row = mid.astype(np.intp)
            frac = (mid - row).astype(np.float32)
            # np.add.at, not buf[idx] += v: fancy-index assignment keeps only
            # one of the duplicate hits, and a dense path is nothing but
            # duplicates.
            np.add.at(self._buf, (row, flat_cols), energy * (1.0 - frac))
            np.add.at(self._buf, (np.minimum(row + 1, height - 1), flat_cols),
                      energy * frac)

        # Segments that cross rows: fill every row between the two ends. Done
        # as a difference array plus one cumulative sum down the columns rather
        # than a loop — the spans overlap and vary in length, and there can be
        # ten thousand of them in a frame. It costs ~2.3 ms at the cap size,
        # which is most of what the segments are worth paying.
        steep = ~flat
        if steep.any():
            fill = self._ensure_fill(height, width)
            fill[:] = 0.0
            first = np.ceil(low[steep]).astype(np.intp)
            past = np.floor(high[steep]).astype(np.intp) + 1
            # What a stationary beam puts into the single row it sits on: the
            # reference every other brightness in the frame is a fraction of.
            flat_row = _OVERSAMPLE * energy
            density = flat_row * np.power(
                _OVERSAMPLE * span[steep], -_BEAM_GAMMA, dtype=np.float32
            )
            np.minimum(density, flat_row, out=density)
            steep_cols = cols[steep]
            np.add.at(fill, (first, steep_cols), density)
            np.add.at(fill, (past, steep_cols), -density)
            np.cumsum(fill, axis=0, out=fill)
            self._buf += fill[:height]

    def _ensure_fill(self, height: int, width: int) -> np.ndarray:
        """The span accumulator, matched to the buffer.

        Allocated beside ``_buf`` and re-checked here because the two must
        agree and the buffer can be replaced between frames — a resize, or a
        harness driving the scene at a size the cap would not have chosen.
        """
        if self._fill.shape != (height + 1, width):
            self._fill = np.zeros((height + 1, width), dtype=np.float32)
        return self._fill

    def _add_bloom(self, glow: np.ndarray, source: np.ndarray) -> None:
        """Add the wide halo into *glow* in place: decimate, blur, put back.

        Two scales rather than one big blur because a radius wide enough to be
        a halo costs its radius per pixel at full resolution; at a quarter of
        the size the same apparent radius is a sixteenth of the work.

        The edge rows and columns that do not fill a whole decimation cell are
        left out rather than padded — at most three pixels of the frame, which
        is the least visible place a halo could be missing from.
        """
        height, width = glow.shape
        cell = _BLOOM_DECIMATE
        bh, bw = height // cell, width // cell
        if bh < 2 or bw < 2:
            return
        small = source[: bh * cell, : bw * cell].reshape(
            bh, cell, bw, cell
        ).mean(axis=(1, 3))
        small = _blur121(small, _BLOOM_BLURS)
        # Back up in two steps with a blur in between, rather than one np.repeat
        # of the whole factor. A single repeat lands the halo as cell-sized
        # blocks, and the one remaining full-resolution pass cannot dissolve a
        # 4 px step — the staircase was plainly visible on the diagonals. The
        # intermediate pass costs a quarter of a full-resolution blur.
        mid = np.repeat(np.repeat(small, 2, axis=0), 2, axis=1)
        mid = _blur121(mid, 1)
        glow[: bh * cell, : bw * cell] += _BLOOM_WEIGHT * np.repeat(
            np.repeat(mid, cell // 2, axis=0), cell // 2, axis=1
        )

    def _paint(self, glow: np.ndarray) -> None:
        height, width = glow.shape
        idx = (np.clip(glow * _DISPLAY_GAIN, 0.0, 1.0) * 255).astype(np.uint8)
        words = self._lut32[idx]
        # QImage does not own the buffer it is handed, so .copy() — otherwise
        # the rows are freed the moment `words` goes out of scope.
        self._image = QImage(
            words.tobytes(), width, height, width * 4, QImage.Format.Format_ARGB32
        ).copy()
