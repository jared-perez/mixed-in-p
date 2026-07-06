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
- **Backdrop**: the same three visuals blitted dimmed (~0.40 opacity) behind
  the playlist rows via the table's image-backdrop path, driven by a
  PlayerPanel timer that runs while playing plus a ~2 s silence decay after
  pause so bars fall and fire burns down. Modes `backdrop_scope`,
  `backdrop_spectrum`, `backdrop_fire`.

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

Beat pulses (drive flashes/accents): Milkdrop-style streaming detector —
instant bass-band energy vs. its smoothed average (`bass > ~1.2 * bass_att`),
a few numpy ops per frame inside VisCanvas. The originally-planned
precomputed librosa onset envelope was dropped: heavy DSP during playback
fights the audio callback for the GIL (the same reason the player suppresses
prefetch-decode while playing), and running it before playback would delay
track start by seconds.

### D. Settings + wiring

- `AppConfig`: `visualizations_enabled: bool = False`,
  `visualization_mode: str = "backdrop"` (persist last dropdown choice).
- Settings panel: checkbox in a new "Visualizations" section; emits
  `settings_changed` as usual; `MainWindow._on_settings_changed()` calls
  `player_panel.set_visualizations_enabled(...)` which shows/hides the
  dropdown (and tears down the popout when disabled).
- Player header dropdown items: Off / Backdrop waveform / Oscilloscope /
  Spectrum / Fire (last three open the popout).
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
