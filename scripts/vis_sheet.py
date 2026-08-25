"""Render a real track through the real visualizer, offscreen, and look at it.

The visuals are judged by eye, and every earlier round of that judging was done
by launching the app — which is slow, needs a mounted drive and a pair of ears
for something that is a question about pixels. This runs the *actual*
:class:`~src.gui.widgets.vis_canvas.VisRenderer` over a decoded file, frame by
frame, feeding it exactly the block the hosts feed it
(``engine.recent_mono(FFT_SIZE)`` — the last 2048 samples up to the play
position), and writes the chosen frames out as a contact sheet.

Two rules it exists to enforce, both learned the hard way (see CLAUDE.md and
the loop tunnel's handoff):

* **Tiles are drawn 1:1.** A resized still lies in both directions: a
  half-scale sheet invented a "pale white line" that turned out to be an
  ordinary axis-aligned spoke, and a device-pixel/logical mix-up once reported
  a fully clipped column as fine. The sheet grows instead of the tiles
  shrinking.
* **Frames are chosen by *beat*, not by time.** "The frame at beat 16.0" then
  means the same thing on a 120 BPM track and a 135 BPM one, which is the only
  way two tracks can be compared on a turn that is supposed to land on the
  bar. For ``beat_tunnel`` the beat comes from the renderer's own clock; for
  the modes with no clock it is the nominal grid at the given tempo.

Examples::

    python scripts/vis_sheet.py --mode loop_tunnel --track a.aiff --seconds 8
    python scripts/vis_sheet.py --mode beat_tunnel --track a.aiff --bpm 128 \\
        --from-beat 15 --to-beat 19 --every 0.25
    python scripts/vis_sheet.py --mode beat_tunnel --track a.aiff --no-tag \\
        --at 16.0,16.25,18.0 --size 1400x800 --dpr 2

It prints one summary line per run — frames, median/p95 render ms, the tempo
the clock settled on, and the number of phase jumps over 0.2 beat — the same
metrics ``evidence/tunnel-chase/beat_clock_v4.py`` reports, so the measured
table in the handoff is reproducible against the shipped code rather than only
against the prototype.

Like ``visual_pass.py`` it redirects its own app data at import: it must not
read or write the user's real config, and a documented manual precaution is
one you will forget.
"""

from __future__ import annotations

import argparse
import atexit
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, REPO)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Redirect app data before anything can call get_app_data_dir() — the same
# reason and the same trick as visual_pass.py.
_VS_HOME = os.environ.get("VIS_SHEET_HOME")
if not _VS_HOME:
    _VS_HOME = tempfile.mkdtemp(prefix="vis-sheet-")
    os.environ["VIS_SHEET_HOME"] = _VS_HOME
    atexit.register(shutil.rmtree, _VS_HOME, ignore_errors=True)
if sys.platform == "win32":
    os.environ["APPDATA"] = _VS_HOME
else:
    os.environ["HOME"] = _VS_HOME

import numpy as np  # noqa: E402
from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402

from src.gui.widgets.vis_canvas import FFT_SIZE, RENDER_MODES, VisRenderer  # noqa: E402

DEFAULT_BPM = 128.0
LABEL_H = 20  # px of caption above each tile
PAD = 10


# ── Audio ──────────────────────────────────────────────────────────────────


def read_mono(path: str, seconds: float | None) -> tuple[np.ndarray, int]:
    """Decode *path* to mono float32. soundfile first, librosa as the fallback.

    The app's own decode path, reused rather than reimplemented so a file the
    app can play is a file this can render.
    """
    from src.gui.workers.waveform_worker import WaveformWorker

    pcm, sr = WaveformWorker._read_audio(path)
    mono = pcm.mean(axis=1).astype(np.float32)
    if seconds is not None:
        mono = mono[: int(seconds * sr)]
    return mono, int(sr)


def block_at(mono: np.ndarray, sr: int, t: float) -> np.ndarray:
    """The FFT_SIZE-sample block ending at time *t* — what the hosts feed.

    Front-padded near the start, so frame 0 is silence rather than a short
    block the renderer would replace with silence anyway.
    """
    end = int(t * sr)
    start = max(0, end - FFT_SIZE)
    blk = mono[start:end]
    if len(blk) < FFT_SIZE:
        blk = np.concatenate([np.zeros(FFT_SIZE - len(blk), np.float32), blk])
    return blk.astype(np.float32)


# ── Frame selection ────────────────────────────────────────────────────────


def wanted_beats(args) -> list[float] | None:
    """The beats to capture, or None for "every frame up to --seconds"."""
    if args.at:
        return [float(v) for v in args.at.split(",") if v.strip()]
    if args.from_beat is not None or args.to_beat is not None:
        lo = args.from_beat if args.from_beat is not None else 0.0
        hi = args.to_beat if args.to_beat is not None else lo + 4.0
        step = args.every
        n = int(round((hi - lo) / step)) + 1
        return [lo + i * step for i in range(n)]
    return None


def tag_bpm(path: str) -> float | None:
    """The file's own BPM tag, so a run without --bpm still knows the tempo."""
    try:
        from src.metadata.tags import read_metadata

        raw = read_metadata(path).bpm
    except Exception:  # noqa: BLE001 — a tagless file is an ordinary case
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# ── The run ────────────────────────────────────────────────────────────────


class Run:
    """One offscreen pass: feed frames in, keep the ones asked for."""

    def __init__(self, args) -> None:
        self.args = args
        self.mono, self.sr = read_mono(args.track, args.seconds)
        self.fps = args.fps
        self.width, self.height = args.size
        bpm = None if args.no_tag else (args.bpm or tag_bpm(args.track))
        self.bpm = bpm
        self.nominal_bpm = bpm or DEFAULT_BPM
        self.renderer = VisRenderer()
        self.renderer.set_color(args.color)
        self.renderer.set_frame_interval(1000.0 / self.fps)
        self.renderer.set_mode(args.mode)
        self.renderer.set_track_tempo(bpm)
        # The host passes device pixels; --dpr models a Retina popout.
        self.renderer.set_target_size(
            int(self.width * args.dpr), int(self.height * args.dpr), popout=args.popout
        )
        self.frames: list[tuple[float, QImage, str]] = []
        self.render_ms: list[float] = []
        self.phase_log: list[float] = []

    # The beat a frame sits on: the renderer's clock when it has one (so the
    # frame really is "the one the turn was scheduled for"), else the nominal
    # grid at the tempo we were given.
    def _phase(self, frame: int) -> float:
        state = self.renderer.beat_state()
        if state is not None:
            return float(state["phase"])
        return frame / self.fps * self.nominal_bpm / 60.0

    def _label(self, phase: float) -> str:
        info = self.renderer.beat_state()
        ms = self.render_ms[-1] if self.render_ms else 0.0
        if info is None:
            return f"beat {phase:.2f}  {self.nominal_bpm:.1f} bpm  {ms:.1f} ms"
        return (
            f"beat {phase:.2f}  in-bar {info['beat_in_bar'] + 1}/4  "
            f"{info['tempo_bpm']:.2f} bpm  "
            f"{'locked' if info['locked'] else 'searching'}  {ms:.1f} ms"
        )

    def go(self) -> None:
        want = wanted_beats(self.args)
        taken: set[int] = set()
        total = int(len(self.mono) / self.sr * self.fps)
        if want:
            # Stop once the last wanted beat is behind us; a beat-selected run
            # should not decode three more minutes to reach nothing.
            limit = max(want) + 1.0
        else:
            limit = None
        for frame in range(total):
            t = frame / self.fps
            start = time.perf_counter()
            image = self.renderer.render(block_at(self.mono, self.sr, t), self.sr)
            self.render_ms.append((time.perf_counter() - start) * 1000.0)
            phase = self._phase(frame)
            self.phase_log.append(phase)
            if want is None:
                if frame % max(1, int(self.fps / 4)) == 0:
                    self.frames.append((phase, image.copy(), self._label(phase)))
            else:
                # One frame's worth of beats either side, so a wanted beat
                # cannot fall between two frames and be missed.
                tol = self.nominal_bpm / 60.0 / self.fps
                for i, beat in enumerate(want):
                    if i in taken or abs(phase - beat) > tol:
                        continue
                    taken.add(i)
                    self.frames.append((beat, image.copy(), self._label(phase)))
                if limit is not None and phase > limit:
                    break
            if self.args.frames_dir:
                out = Path(self.args.frames_dir)
                out.mkdir(parents=True, exist_ok=True)
                image.save(str(out / f"frame_{frame:06d}.png"))

    # ── Reporting ──────────────────────────────────────────────────────────

    def jumps(self) -> int:
        """Seconds in which the beat phase moved more than 0.2 beat.

        The clock free-runs at the period, so a jump is the *correction*
        overshooting — the metric beat_clock_v4.evaluate reports, and the one
        that corresponds to a turn visibly out of step.
        """
        if len(self.phase_log) < self.fps * 2:
            return 0
        expected = self.nominal_bpm / 60.0 / self.fps
        d = np.diff(np.asarray(self.phase_log))
        return int((np.abs(d - expected) > 0.2).sum())

    def summary(self) -> str:
        ms = np.asarray(self.render_ms[5:]) if len(self.render_ms) > 5 else np.zeros(1)
        info = self.renderer.beat_state()
        tempo = f"{info['tempo_bpm']:.2f}" if info else f"{self.nominal_bpm:.2f} (nominal)"
        return (
            f"{self.args.mode}: {len(self.render_ms)} frames at {self.fps} fps, "
            f"{self.width}x{self.height} dpr {self.args.dpr} -> image "
            f"{self.renderer.image().width()}x{self.renderer.image().height()}; "
            f"render median {np.median(ms):.2f} ms p95 {np.percentile(ms, 95):.2f} ms; "
            f"tempo {tempo}; phase jumps {self.jumps()}; captured {len(self.frames)}"
        )


# ── The sheet ──────────────────────────────────────────────────────────────


def contact_sheet(frames, columns: int) -> QImage:
    """Tiles at 1:1 with a caption above each. Never downscaled — see module docs."""
    if not frames:
        raise SystemExit("no frames captured — check --at/--from-beat against the track")
    tile_w = max(img.width() for _b, img, _l in frames)
    tile_h = max(img.height() for _b, img, _l in frames)
    cols = max(1, min(columns, len(frames)))
    rows = (len(frames) + cols - 1) // cols
    sheet = QImage(
        PAD + cols * (tile_w + PAD),
        PAD + rows * (tile_h + LABEL_H + PAD),
        QImage.Format.Format_ARGB32,
    )
    sheet.fill(QColor("#0a0a0a"))
    painter = QPainter(sheet)
    font = QFont()
    font.setPointSize(10)
    painter.setFont(font)
    for i, (_beat, image, label) in enumerate(frames):
        row, col = divmod(i, cols)
        x = PAD + col * (tile_w + PAD)
        y = PAD + row * (tile_h + LABEL_H + PAD)
        painter.setPen(QColor("#dddddd"))
        painter.drawText(x + 2, y + LABEL_H - 6, label)
        # The frames are transparent (the backdrop host composites over grey);
        # fill black first so a tile looks like the popout, not like a hole.
        painter.fillRect(QRectF(x, y + LABEL_H, tile_w, tile_h), QColor("#0a0a0a"))
        painter.drawImage(x, y + LABEL_H, image)
    painter.end()
    return sheet


def parse_size(text: str) -> tuple[int, int]:
    w, _, h = text.lower().partition("x")
    return int(w), int(h)


def build_parser() -> argparse.ArgumentParser:
    """Separate from main() so the smoke test can build an args object."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", default="beat_tunnel", choices=sorted(RENDER_MODES))
    parser.add_argument("--track", required=True, help="audio file to render")
    parser.add_argument("--bpm", type=float, default=None, help="override the tag BPM")
    parser.add_argument(
        "--no-tag", action="store_true", help="hide the tempo (test the estimator)"
    )
    parser.add_argument("--from-beat", type=float, default=None)
    parser.add_argument("--to-beat", type=float, default=None)
    parser.add_argument("--every", type=float, default=0.25, help="beat step for a strip")
    parser.add_argument("--at", default="", help="comma-separated exact beats")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--size", type=parse_size, default=(1216, 512), help="WxH logical")
    parser.add_argument("--dpr", type=float, default=1.0, help="device pixel ratio")
    parser.add_argument(
        "--popout", action="store_true",
        help="use the popout's larger render cap rather than the backdrop's",
    )
    parser.add_argument("--seconds", type=float, default=None, help="decode limit")
    parser.add_argument("--columns", type=int, default=2)
    parser.add_argument("--out", default="")
    parser.add_argument("--frames-dir", default="")
    parser.add_argument("--color", default="#f5c518")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    QGuiApplication.instance() or QGuiApplication([])
    run = Run(args)
    run.go()
    print(run.summary())
    out = args.out or str(
        Path(REPO) / "spitball" / "mip-pip" / "evidence" / "tunnel-chase"
        / f"sheet-{args.mode}.png"
    )
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    contact_sheet(run.frames, args.columns).save(out)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
