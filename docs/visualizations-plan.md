# Audio Visualizations — Feature Plan

Branch: `feature/audio-visualizations`

## Goal

1. **Analyze / Convert panels**: a simple animated waveform (colored per the
   waveform color setting) that acts as an activity/progress indicator while
   work runs.
2. **Player panel**: real audio-reactive visuals. Default = dimmed waveform
   painted behind the playlist. Additional classic-style visuals (oscilloscope,
   spectrum bars, "fire" bars) selectable from a dropdown at the top of the
   player, shown as a popout window.
3. **Settings**: a master "Enable visualizations" option. When on, the visuals
   dropdown appears in the player header row.

## Why this is easy in our architecture (codebase findings)

- **We already have sample access during playback.** `PlayerEngine`
  (`src/gui/widgets/player_engine.py`) decodes whole tracks to RAM as float32
  numpy `(frames, channels)` arrays and plays via a sounddevice
  `OutputStream` callback, tracking the playhead as an integer frame index
  `_pos` polled by a GUI QTimer. So per vis frame we just slice
  `pcm[pos-2048 : pos]` — no ring buffer, no Qt Multimedia, sample-accurate.
  (Qt6 removed `QAudioProbe`; we sidestep that whole problem.)
- **Waveform peaks are already computed.** `WaveformWorker.downsample_waveform`
  (`src/gui/workers/waveform_worker.py:21`) produces min/max envelopes; reuse
  for the behind-playlist backdrop.
- **Color plumbing exists.** `config.waveform_color` (`src/utils/config.py:71`),
  theme token `WAVEFORM_DEFAULT` (`src/gui/styles/theme.py:191`), and
  `MainWindow._effective_waveform_color()` (`main_window.py:722`). Visuals
  should take their primary color from the same source.
- **Settings pattern**: push model — `settings_panel.settings_changed` →
  `MainWindow._on_settings_changed()` (`main_window.py:734`) calls `set_*()`
  on dependent panels. Add `visualizations_enabled: bool` (and
  `visualization_mode: str`) to `AppConfig` the same way.
- **Analyze/Convert progress**: workers emit per-file `progress` signals into
  `ProgressPanel` (`src/gui/widgets/progress_bar.py`). The animated waveform
  indicator slots in alongside/inside `ProgressPanel`.
- **Placement**: player title row (`player_panel.py:827-852`, Player label +
  album art + Edit Lock) has room for the visuals dropdown. Playlist is a
  `ReorderableTableWidget` (QTableWidget).

## Design

### A. Activity waveform for Analyze/Convert

Not audio-reactive (workers churn through files; we don't need real data) — a
stylized animated waveform that reads as "working":

- New widget `VisActivityWaveform(QWidget)`: QPainter draws a synthetic
  waveform (sum of a few sines with drifting phase + noise envelope), colored
  with the effective waveform color, animated by a QTimer (~30 fps) only while
  a job runs. Optionally sweep a brighter "playhead" band left→right scaled to
  `completed/total` so it doubles as a progress bar.
- Embed in `ProgressPanel` (shown when `start()`, frozen/hidden on
  `complete()`/`set_error()`), so both Analyze and Convert get it for free.
- Cheap: <1 ms/frame, GUI thread is fine.

### B. Player: default backdrop waveform behind the playlist

- Subclass/extend `ReorderableTableWidget.paintEvent`: paint on
  `self.viewport()` before `super().paintEvent(event)` so rows render on top.
- A **scrolling zoomed window** (CDJ-style moving waveform), not the full
  track: a ~12 s span of a time-indexed envelope (`timed_envelope`, ~200
  bins/s) with the playhead fixed at center — played half brighter, upcoming
  half dimmed, center playhead line. Repainted per position tick (~30 fps);
  nothing cached since the visible bin range changes every frame.
- **QSS gotcha**: the global stylesheet paints the table background *over*
  `paintEvent` drawing. The playlist (and item/alternate-row/selection
  backgrounds) need explicit `transparent`/`rgba(...)` entries in
  `app.qss.template` for this widget.
- Stationary backdrop (viewport coordinates), not scroll-anchored.

### C. Player: classic visuals (popout AND backdrop)

Rendering lives in `VisRenderer` (no widget): each frame drawn into a small
transparent-background `QImage`, upscaled without smoothing for the chunky
retro-pixel look. QPainter + QTimer at ~30 fps is plenty (no OpenGL for v1).
Two hosts share it:

- **Popout**: `VisualizerWindow` (own QTimer) hosting `VisCanvas`, which fills
  black behind the frame.
- **Backdrop**: the same visuals blitted dimmed (~0.40 opacity) behind
  the playlist rows via the table's image-backdrop path, driven by a
  PlayerPanel timer that runs while playing plus a ~2 s silence decay after
  pause so bars fall and fire burns down. Modes `backdrop_scope`,
  `backdrop_spectrum`, `backdrop_fire`, `backdrop_fractal`,
  `backdrop_wormhole`.

Data path per frame (GUI-thread QTimer, `Qt.PreciseTimer`, 16 ms):

```
pos = engine.position_frames()
frame = pcm_mono[pos-2048 : pos]          # read-only slice, no copy needed
spectrum = 20*log10(|rfft(hann*frame)|)   # numpy only, sub-ms
```

Modes (all reimplemented from scratch; constants informed by Webamp's MIT
reimplementation — never copy from the 2024 Winamp source dump, its license
is radioactive):

1. **Oscilloscope** — last ~576 samples, one column per x-pixel; dot / line /
   solid draw styles; vertical quantization for the retro look.
2. **Spectrum bars** — hybrid lin/log band mapping (~0.9 blend toward log,
   the classic look), dB floor ≈ -65, instant attack + linear falloff
   (~12 units/frame default), grey peak-hold caps with accelerating fall
   (counter 3.0, ×1.1/frame). Thin (75 bars) and wide (~19 bars) variants.
3. **Fire bars** — same bars, palette ramp black→red→orange→yellow→white over
   bar height; optional "flames" = previous-frame upshift + color decay
   (small feedback QImage).
4. **Fractal** — a spinning escape-time Julia set whose constant swings
   through the rich arc of the classic |c| = 0.7885 orbit; level drives
   spin/morph speed and brightness, the kick pulse punches the zoom.
   ~0.7 ms/frame.
5. **Wormhole** — a wireframe tunnel flown along a closed 3-D loop (a periodic
   cubic spline through 25 frozen waypoints: 15 turns, three straightaways,
   ~70 s per lap), with small cross-shaped stars streaming past. Level drives travel
   speed and brightness; the kick pulse ripples the near rings and lights the
   stars, which sit at a dim floor between beats and are released over ~0.5 s
   after each one (the fractal's fast-attack/slow-release shape — a bare pulse
   strobes, because the detector's value collapses a frame or two after the
   transient).

   The exception to the small-image rule above, in two ways. Its cost is
   **O(lines), not O(pixels)** — QPainter calls dominate — so four times the
   resolution costs nothing, and it renders antialiased at 608×256 for
   **1.6 ms/frame** (measured, against the fractal's 0.7) rather than as a
   staircase on the 152×64 grid. And because a wireframe stretched
   non-uniformly would draw *ellipses* for rings, it owns its image and
   matches the aspect to the host: `VisRenderer.set_target_size(w, h)` (a
   no-op for every other mode), called by both hosts before each frame, fixes
   the height at 256 and derives the width, reallocating only on a real
   resize. The path and scene live in `src/gui/widgets/vis_wormhole.py`;
   numpy + QPainter only, no OpenGL and no scipy (`scipy.interpolate` alone
   imports in 194 ms — the 25×25 dense solve that replaces it takes ~8 ms,
   lazily, on the first rendered frame).

6. **Tunnel Chase** — the wormhole's sibling, flown to the beat. Same
   wireframe tube and the same O(lines) cost, but the path is **generated
   ahead of the camera in beat-space** rather than precomputed: arc length is
   measured in beats (2.5 world units each), so a turn scheduled for beat 16
   is a bend at 16 × 2.5 units and the camera reaches it exactly when the
   music does. Speed is therefore the *tempo*; level only sets brightness. The
   schedule is the brief in two lines — a turn on the first beat of every bar,
   plus a gentler one on the third beat of every fourth bar — which is a
   four-bar phrase you can feel.

   **A turn is a lean and a straightaway is a long curve.** The bump's
   integral is the heading change, so its width and its sharpness trade off
   directly: the first version turned over 0.9 beats, which spiked to a 2.27 R
   radius and left **53% of the flight dead straight** — every turn was a
   departure from nothing, and it read as a series of elbows. At 1.6 beats the
   sharpest turn opens to 3.4 R and each beat still gets a distinct swing
   (past about 2.2 consecutive bumps overlap and the turns blur into one
   sweep). Under all of it sits a slow two-axis wander at about 20 R, at
   wavelengths that are neither equal nor a whole number of bars, so it never
   lines up with the schedule and never reads as part of it — dead-straight
   time drops to ~3%, and as a side effect the far end stops piling into a
   bright knot, because the tunnel is no longer pointing down its own axis.

   Stars are dots far out and four-point stars
   with a white core near, in three shades (grey and two washes of the
   wireframe colour toward white), with three shaded planets drifting past.
   Measured **3.4 ms/frame at 1216×512** and 4.5 at popout size.

   Two things it does that no other mode does. It renders from **device**
   pixels and asks the host to upscale *smoothly* (`VisRenderer
   .smooth_upscale()`), capped at 720 high for the popout and 512 for the
   backdrop — a Retina popout at 1400×800 renders 1260×720 rather than
   2800×1600, which would be ~10 ms. And it runs at **60 fps in the popout**
   (`VisRenderer.frame_ms()`), which is a correctness reason and not only a
   smoothness one: at 33 ms the kick flux is too coarse and the beat clock
   measurably fails to lock on two of six test tracks.

   The near plane needed two different treatments, found by rendering rather
   than reasoning. A ring passing beside the camera on a bend projects a
   correct but startling bright chord across the lens; clipping it away also
   drops the nearest ring's spokes, and those spokes — arriving from
   off-frame — are what put the viewer *inside* a tube rather than in front of
   a cone. So spokes are **clipped at** the plane by interpolation and rings
   are **faded out near** it. `src/gui/widgets/vis_tunnel_chase.py`.

### The beat clock

Tunnel Chase is the first visual that *counts beats*, which the kick pulse
below cannot do: measured over six real tracks it fires 1.2–3.5 times per
beat, because an off-beat bass line lifts the 50–120 Hz band as far as a kick
does. A phase-locked loop correcting on every one of those onsets is dragged
off the beat on four of the six.

So the two halves come from different places (`src/gui/widgets/beat_clock.py`,
no Qt, ~6 µs a frame):

- **The period is the tag.** The file's own BPM — the app analysed it — and a
  clock free-running at it drifts by nothing over a track. `_play_track`
  pushes it to both renderers; a popout opened mid-track is given it too.
- **The phase is accumulated evidence**, never a single onset: a decaying
  16-bin histogram of a *kick-flux* feature (the rectified rise in bass
  energy, **gated** by the broadband spectral flux — a kick has a click and a
  bass note does not) against the clock's own beat, with the clock gliding
  toward the mass. Measured on kick-led tracks: within 0.03–0.06 beat of
  librosa's grid, 99–100 % of beats inside 1/8, and zero phase jumps in two
  minutes.

The lock is **sticky**, and that is load-bearing: a rival phase must out-mass
the locked one by half again *and* hold it for two seconds. Without it one
test track shows 22 visible jumps in two minutes; with it, none. The period
additionally adapts by up to ±1 % to rescue a tag that is half a BPM out.

The bar slot (four decaying accumulators of on-beat energy) is **consistency,
not downbeat detection** — on one track the strongest slot is beat 4 — and it
is applied to the *schedule* of beats not yet generated rather than to the
camera's phase, so a slot flip changes which beats turn a few bars later
instead of jumping the camera down the tunnel.

An untagged file falls back to `TempoBank`: 91 candidate periods, each with
its own phase histogram, peakiest wins (3 µs/frame, hysteresis on switching).
Right on every track with a regular kick, wrong by a rational ratio (3:2, 4:3)
on the two without. Running librosa during playback would be the accurate
answer and is ruled out for the same GIL reason as everything else here — the
real fix for an untagged track is to analyse it, which is the product.

Beat pulses (drive flashes/accents): Milkdrop-style streaming detector —
instant bass-band energy vs. its smoothed average (`bass > ~1.2 * bass_att`),
a few numpy ops per frame inside VisCanvas. The originally-planned
precomputed librosa onset envelope was dropped: heavy DSP during playback
fights the audio callback for the GIL (the same reason the player suppresses
prefetch-decode while playing), and running it before playback would delay
track start by seconds.

### D. Settings + wiring

- `AppConfig`: `visualizations_enabled: bool = False`,
  `visualization_mode: str = "off"` (persist last dropdown choice).

  **Superseded 2026-08-23**: there is no master switch any more. `"off"` is one
  of the modes, the eye button is always in the Player header, and picking a
  visual is what starts it — so `visualizations_enabled`, the Settings section
  and `set_visualizations_enabled` are all gone, and nothing runs until the
  user chooses. What that leaves is a config carrying a mode *and* a switch
  that was **off by default**: reading the mode alone would start a visual for
  everyone who never asked for one, so `_folded_vis_mode` in `config.py` reads
  an explicitly-off switch as `"off"` whatever mode sits beside it. It needs no
  version field to stay one-time — it keys on the legacy key still being
  present, and the first save without it (`asdict` no longer has the field)
  removes it for good.
- Player eye-menu items, in order: the richest visuals lead each group
  (Backdrop fractal, Backdrop wormhole, Backdrop tunnel chase, then
  waveform/oscilloscope/spectrum/fire; then the popouts in the same order),
  with **Visuals off** at the foot —
  it is the way out, not the way in, and a menu that opens on its own "off" row
  buries what it offers.
- **Looking at it**: `python scripts/vis_sheet.py` runs a real track through
  the real `VisRenderer` offscreen and writes a **1:1** contact sheet of chosen
  frames, indexed by *beat* rather than by time (so "the frame at beat 16" is
  the same moment on a 120 and a 135 BPM track) and labelled with the clock's
  tempo and lock. It works for every mode, so it is a regression tool for all
  six. Two rules it exists to enforce: tiles are never downscaled — a resized
  still lies in both directions — and the frames it picks are the ones the
  turns were scheduled for.
- **i18n**: every new user-facing string wrapped with `self.tr()`, then
  `python scripts/build_translations.py` (per CLAUDE.md). Mode names in the
  dropdown are UI prose → translated; "BPM"-style tokens unaffected.

## Later / out of scope for v1

- **Milkdrop-style visuals**: the only real option is projectM v4 (actively
  maintained C++/OpenGL Milkdrop reimplementation with a C API built for
  bindings). Feasible via a ctypes wrapper inside a `QOpenGLWidget`; LGPL 2.1
  is fine for our distributed app if the lib ships as a separate dynamic
  library in the three artifacts — but it's real integration + packaging work
  per-OS. The existing Python bindings (`pym`) are dead. Alternative:
  Butterchurn (MIT, WebGL) via QWebEngineView, but that adds ~150 MB to
  bundles. Treat as its own future feature.
- AVS-style scriptable feedback effects (blur/trail buffers) — would want
  QOpenGLWidget; the fire-bars feedback trick is the v1 taste of this.
- Fullscreen visualizer mode.

## Implementation order

1. Config + settings checkbox + dropdown scaffolding (hidden behind setting).
2. Activity waveform in ProgressPanel (Analyze/Convert). Smallest, ships alone.
3. Backdrop waveform behind playlist (+ QSS transparency work).
4. VisCanvas: oscilloscope → spectrum bars → fire.
5. Onset-envelope precompute + beat accents.
6. Translations refresh + per-language pass.
