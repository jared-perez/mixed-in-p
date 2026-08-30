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

Rendering lives in `VisRenderer` (no widget): each frame drawn into a
transparent-background `QImage`. The **retro** modes (spectrum, fire, fractal)
draw into a small 152×64 one and are upscaled without smoothing, which is the
chunky pixel look and is the point of them. The rest — both tunnels, the scope
and the stream — **own their image**, size it from *device* pixels under a cap
of their own, and ask the host to upscale smoothly
(`VisRenderer.smooth_upscale()`); see each entry for why and for what it cost.
QPainter + QTimer at ~30 fps is plenty for the retro modes (no OpenGL), but the
beat tunnel runs at 60 for a correctness reason — see its entry.
Two hosts share it:

- **Popout**: `VisualizerWindow` (own QTimer) hosting `VisCanvas`, which fills
  black behind the frame.
- **Backdrop**: the same visuals blitted dimmed (~0.40 opacity) behind
  the playlist rows via the table's image-backdrop path, driven by a
  PlayerPanel timer that runs while playing plus a ~2 s silence decay after
  pause so bars fall and fire burns down. Modes `backdrop_scope` (which draws
  the stream, not a scope — the row kept its id when its picture changed),
  `backdrop_oscilloscope`, `backdrop_spectrum`, `backdrop_fire`,
  `backdrop_fractal`, `backdrop_loop_tunnel`, `backdrop_beat_tunnel`.

Data path per frame (GUI-thread QTimer, `Qt.PreciseTimer`, 16 ms):

```
pos = engine.position_frames()
frame = pcm_mono[pos-2048 : pos]          # read-only slice, no copy needed
spectrum = 20*log10(|rfft(hann*frame)|)   # numpy only, sub-ms
```

Modes (all reimplemented from scratch; constants informed by Webamp's MIT
reimplementation — never copy from the 2024 Winamp source dump, its license
is radioactive):

1. **Oscilloscope** — an **analog CRT**: a green phosphor beam with glow and
   persistence, in *both* hosts. It shipped as the popout face only, opposite a
   chunky 152×64 retro grid in the backdrop (last ~576 samples, one column per
   x-pixel, vertically quantized); **that retro face is gone**, and
   `backdrop_oscilloscope` now reaches this same scene — which is why adding
   the backdrop row cost almost no code: the mode stopped having two faces.
   The `popout` flag on `set_target_size` therefore no longer picks a
   *picture*, only an area cap (`_POPOUT_CAP_PX` 900k, `_BACKDROP_CAP_PX`
   620k), because the two hosts have different budgets.

   It is **not a polyline**. Bright slow segments, a dim thread on the steep
   slopes, a soft halo and decaying ghosts all fall out of one float32
   *phosphor buffer* the size of the host: decay it (that is the persistence),
   stamp the beam path in additively, blur once for softness plus a
   4×-decimated blurred copy back for the halo, lay the graticule over the top
   *after* the blurs so it stays crisp and never blooms, then look the result
   up in a black → green → white ramp. Beam brightness needs no code of its
   own — the path is sampled at a fixed number of points per frame, so a point
   *is* a fixed slice of time and the scatter puts more of them per pixel where
   the beam moves slowly, which is the analog behaviour for free. The obvious
   alternative (the polyline drawn three or four times with wide antialiased
   round-cap pens under `CompositionMode_Plus`) was measured dead on arrival:
   25.8 ms at 1216×512 and 246 ms at 2400×1200, against a 16 ms frame — the
   wide AA pens are the cost, not the persistence.
   `src/gui/widgets/vis_analog_scope.py`.
2. **Spectrum bars** — hybrid lin/log band mapping (~0.9 blend toward log,
   the classic look), dB floor ≈ -65, instant attack + linear falloff
   (~12 units/frame default), grey peak-hold caps with accelerating fall
   (counter 3.0, ×1.1/frame). Thin (75 bars) and wide (~19 bars) variants.
3. **Fire bars** — same bars, palette ramp black→colour→white over bar height
   (derived from the waveform colour, so the classic red/orange is that ramp
   for pure red rather than a hardcoded palette); optional "flames" =
   previous-frame upshift + colour decay (small feedback QImage).
   **Backdrop-only**: retired from the menu's popout half, where it read as the
   whole window, and kept as a backdrop, where it reads as lit rows. So a mode
   may render and not be offered — never the other way round, which
   `POPOUT_MODES` derives from `_BACKDROP_ONLY` rather than writing out, so a
   new render mode cannot be silently unreachable.
4. **Fractal** — a spinning escape-time Julia set whose constant swings
   through the rich arc of the classic |c| = 0.7885 orbit; level drives
   spin/morph speed and brightness, the kick pulse punches the zoom.
   ~0.7 ms/frame.
5. **Tunnel Chase** (`loop_tunnel`) — a wireframe tunnel flown along a closed 3-D loop (a periodic
   cubic spline through 25 frozen waypoints: 15 turns, three straightaways,
   ~70 s per lap), with small cross-shaped stars streaming past. Level drives travel
   speed and brightness; the kick pulse ripples the near rings and lights the
   stars, which sit at a dim floor between beats and are released over ~0.5 s
   after each one (the fractal's fast-attack/slow-release shape — a bare pulse
   strobes, because the detector's value collapses a frame or two after the
   transient).

   The exception to the small-image rule above, in two ways. Its cost is
   **O(lines), not O(pixels)** — QPainter calls dominate — so resolution is
   cheap here in a way it is not for the per-pixel modes, and it renders
   antialiased rather than as a staircase on the 152×64 grid. And because a
   wireframe stretched non-uniformly would draw *ellipses* for rings, it owns
   its image and matches the aspect to the host:
   `VisRenderer.set_target_size(w, h, popout)` (a no-op for every other mode),
   called by both hosts before each frame, reallocating only on a real resize.

   It used to fix the height at **256** whatever was asking and let the host
   blow it up with nearest-neighbour, which on a Retina popout is 448×256
   stretched to 2800×1600 — one image pixel per 6.25 device pixels, and the
   wireframe read as a staircase. It now sizes from **device** pixels under
   caps of its own (1216×512 backdrop, 2400×1200 popout) and the host
   interpolates the remainder (`VisRenderer.smooth_upscale()`, true for both
   wireframe modes). Measured, one frame: 1.6 ms at the old 448×256, 3.1 at
   the backdrop's 896×512, **8.0 at the popout's 2100×1200**, 10.7 rendering
   a 2800×1600 host natively. The popout's cap is more than the beat tunnel's
   despite looking like the same decision, and the reason is the frame rate,
   not the picture: the tunnel runs at 60 fps and has 16 ms, this runs at 30
   and has 33. Native is sharper at 1:1 and was declined because it is a third
   of the frame here and unbounded on a larger display (5K would be ~20 ms).

   Two sizes had to become *reference* sizes for any of that to be safe — the
   pen width and the star cell, both scaled by `height / 256`. The image is
   drawn into a fixed logical rect, so scaling them keeps a line's and a
   star's **apparent** size constant while the resolution changes; left as
   constants, raising the resolution would have made the wireframe thinner and
   shrunk the pixel stars to hairlines, i.e. bought the tunnel its detail by
   deleting the sky. The focal length is derived from the image height for the
   same reason, and re-derived on every resize — frozen at construction, a
   resize would silently change the field of view. Before and after at 1:1
   device pixels: `evidence/wormhole/resolution_sheet.py`.

   The path and scene live in `src/gui/widgets/vis_loop_tunnel.py`;
   numpy + QPainter only, no OpenGL and no scipy (`scipy.interpolate` alone
   imports in 194 ms — the 25×25 dense solve that replaces it takes ~8 ms,
   lazily, on the first rendered frame).

6. **Wormhole** (`beat_tunnel`) — the loop tunnel's sibling, flown to the beat. Same tube
   geometry as the loop tunnel's, but the path is **generated
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
   sweep). Under all of it sits a slow two-axis wander at about 18 R, at
   wavelengths that are neither equal nor a whole number of bars, so it never
   lines up with the schedule and never reads as part of it — dead-straight
   time lands at **~7%** (over 40 bars), and as a side effect the far end
   largely stops piling into a bright knot, because the tunnel is rarely
   pointing down its own axis.

   That figure is tuned and was converged on from both sides: 53% before any
   wander, 3.3% at the first amplitude tried (too restless), 8.9% at the
   second (too straight), 6.8% now. Two warnings if you reach for it as a
   knob. It is **hypersensitive** exactly here — 1/50 R is roughly the
   amplitude itself, so what it counts is how often the two sinusoids cross
   zero together, while the wander's own median radius moves only 15 to 17 R
   across the whole useful range. And it **moves with how much path you
   sample**, because the two wavelengths do not come back into phase inside a
   short one: the same setting reads 8.9% over 40 bars and 10.1% over 60. So
   quote it with a length attached, judge the setting by rendering, and treat
   the number as a way to hold a judgement still rather than a way to make
   one. Its test is a band (half to double), not a ceiling, since a value
   converged on from both directions can regress in both.

   Stars are dots far out and four-point stars
   with a white core near, in three shades (grey and two washes of the
   accent colour toward white). How spiky and how big a star is comes off
   **one roll skewed toward the small end** (`_STAR_SIZE_BIAS`), and the two
   ride that same roll deliberately — "less spiky" and "more compact" are the
   same star, so a short-armed one never comes out as a fat plus. Past them
   drift three shaded planets and, far more rarely, a single galaxy.
   Measured **3.4 ms/frame at 1216×512** and 4.5 at popout size.

   A planet's tint and its rings are rolled **once, at spawn** — so it cannot
   change while it is on screen — and they are chances rather than counts,
   because with only three planets at a time a "small percentage" is a property
   of the stream. Measured over three minutes at 128 BPM, averaged across three
   seeds: **about thirty planets a minute**, of which roughly five are dusky,
   five wear the accent's own colour instead of the pale wash, three are a dull
   red and three a dull blue (fixed constants, not accent washes — there is no
   wash of a gold accent that comes out red), and seven carry one to three thin
   rings in a plane of their own.

   **That rate is a tuned setting, and it is the rest gap that sets it.** An
   emptied sky slot does not refill at once; it lies parked for a stretch of
   *path* first (`_PLANET_REST`, in world units so the 16 ms and 33 ms hosts
   agree and the rate scales with the tempo). The unthinned stream was
   fifty-five a minute, and two passes have taken it to thirty. The knob is
   **not linear** — the rate is lifetime plus rest, and the ~19 units of
   lifetime sit in the denominator and do not move, so the second pass's "25%
   fewer" needed the mean rest to go 4.8 → 12.7 rather than a 25% nudge — and
   it is **noisy**: three seeds of one build measured 30.3 / 30.3 / 28.3 a
   minute while a neighbouring setting measured 36.3 / 30.0 / 35.0, so a lone
   three-minute figure carries about ±3/min, which is most of the distance
   between two settings anyone would argue about. Quote a per-seed spread.

   The rings cost 0.02 ms a frame, and they are drawn in three passes — the arc
   behind the planet, the disc, then the arc in front — which is the Saturn
   silhouette for the price of a depth comparison per segment. They are drawn
   **brighter than the disc they circle** (1.4×, ceiling 0.7) and have to be:
   the disc spreads its alpha over thousands of pixels and the ring over a
   one-pixel line, so at the disc's own alpha the first cut of them was
   invisible in the app while passing every structural test. That was found by
   rendering a real flight — `planet_sheet.py --flight` in the evidence
   directory, which grabs the ringed planets as they actually pass rather than
   placing one by hand at an alpha nothing produces. The multiplier has since
   come *down* from 1.8: the double-painted segment joints were part of what
   1.8 was tuned against, and once that beading was gone it read as too bright
   in the running app. Both numbers are the user's judgement from the app, so
   treat them as settled rather than as headroom.

   **Galaxies are the sparse one**: a single slot, resting far longer than a
   planet's between visits (`_GALAXY_REST`), measured at about nine a minute —
   roughly 30% of the planet stream's rate, though that ratio was 22% before
   the second thinning pass and has drifted up as the planets thinned rather
   than being chosen: the galaxy's own rest gap has never moved.
   Bigger than any planet in world units and drawn as translucent haze — a
   tilted gradient disc, a round bulge and two spiral arms — so it reads as
   background rather than as an approaching object. An arm is a run of
   overlapping soft blobs rather than a stroke; the stroked version read as a
   curled wire in the running app, and cloud is clumps.

   Two things it does that no other mode does. It renders from **device**
   pixels and asks the host to upscale *smoothly* (`VisRenderer
   .smooth_upscale()`), capped at 720 high for the popout and 512 for the
   backdrop — a Retina popout at 1400×800 renders 1260×720 rather than
   2800×1600, which would be ~10 ms. And it runs at **60 fps in the popout**
   (`VisRenderer.frame_ms()`), which is a correctness reason and not only a
   smoothness one: at 33 ms the kick flux is too coarse and the beat clock
   measurably fails to lock on two of six test tracks.

   **The wall is a nebula, not a wireframe.** The mesh is still what the
   picture is built on, but what is drawn at its vertices is a wall of
   translucent cloud: pre-rendered additive sprites ("puffs"), scattered blue,
   violet, magenta, teal and green, that the stars and planets read straight
   through. Sprites won on more than cost — they inherit every hard-won piece
   of the existing geometry for free, because a puff is drawn *at* a mesh
   vertex, so the bends, the drift and the pulse ripple on the wall radius all
   come along without a line of new maths. Measured against the alternatives
   at the popout cap: filled quads per mesh cell cost +6.25 ms and read
   faceted; a low-res screen-space noise field is the cheapest of all (+0.6
   ms) and cannot follow a bent tube without the per-pixel ray/tube mapping
   that is the whole cost being avoided; and true raymarched volumetrics are
   shader-only, i.e. a new architecture for one mode.

   Three things the build is shaped by, all of them found by rendering.
   **Additive puffs stack where the tube converges** — the wireframe's bright
   knot squared — so the cloud gets an extra far fade over the mesh's own, a
   minimum-size cull, and half its puffs dropped on the far rings. **The bore
   fills in unless the puffs sit outside the wall**, so each is pushed
   radially outward (1.45 × the wall radius) — in *world* space, because the
   obvious screen-space version scales each vertex off the ring's projected
   centroid and the centroid of a partly-behind-camera ring is garbage, which
   the near rings always are on a bend. And **everything about a puff is
   hashed from its world arc length**, never from the ring slot, which
   re-seats every spacing: hashed from the slot the cloud rides along with the
   camera instead of streaming past it. There is no per-frame state anywhere
   in it — the wall is a pure function of arc length, like the path — so
   `set_frame_interval` has nothing to add and the 16 ms and 33 ms hosts
   render identical worlds.

   Cost: **4.7 ms/frame at 1600×720** and 3.5 at the backdrop's 1216×512,
   against a 16 ms budget. The per-puff work is vectorized over the whole
   (ring, segment) grid in numpy and reduced to one boolean mask, so the
   Python loop that remains blits ~260 survivors of 560 with every number
   already decided; the noise is baked into sixty sprites at init (four cloud
   shapes × five hues × three resolutions, ~1.7 MB) and never evaluated per
   frame. The proof-of-concept, before that pass, was 8.2 ms.

   The near plane needed two different treatments, found by rendering rather
   than reasoning. A ring passing beside the camera on a bend projects a
   correct but startling bright chord across the lens; clipping it away also
   drops the nearest ring's spokes, and those spokes — arriving from
   off-frame — are what put the viewer *inside* a tube rather than in front of
   a cone. So spokes are **clipped at** the plane by interpolation and rings
   are **faded out near** it. `src/gui/widgets/vis_beat_tunnel.py`.

7. **Stream** (`stream`) — a sheet of liquid metal wiggled at its source like
   a **garden hose**, and the mode that retired the chunky 152×64 retro trace
   that used to draw `backdrop_scope`. **Backdrop-only**, the way fire is: the
   popout's `oscilloscope` keeps its green CRT and is a separate mode id, so
   the menu row's id and its picture no longer match — deliberately, and
   documented at the row (see the intro above).

   The model in one line: the *source*'s vertical position moves, that
   displacement travels along the stream at a fixed flow speed, and what the
   wave carries is a **flat sheet shaded by its orientation** — not a tube.
   The source sits at the right edge (the newest audio) and the wave rolls
   left, crossing in `_WINDOW_SECONDS` (0.5). What moves the source is three
   weighted drivers: a **dance** on the beat grid (every 4th beat is a turning
   point, and the bigger the boundary — 8, 16, 32 — the further and *quicker*
   the swing, so the motion is lazy half-time inside a phrase and snaps at
   phrase edges), a **melody wobble** from the band-passed mid-highs
   (~570 Hz–7 kHz), and the original full-band loudness **wiggle** as texture.
   The first cut drove the source from overall loudness alone, which on
   bass-heavy music let the bass dictate everything and pinned a steady-loud
   track to mid-height.

   **That one decision is what buys the look cheaply**: the silhouette is
   smooth *by construction*, because it is the history of a smooth signal
   advected, so there is no per-edge turbulence machinery anywhere in it — an
   earlier round that had some produced spiky stalactites. Shade comes from a
   precomputed 1-D **chrome environment ramp** indexed by the normal, which is
   why layers of contrast cost nothing per frame; the beat is carried by
   brightening what is *leaving the nozzle* and letting the same advection
   push it down the stream, so a kick is a bright surge travelling down a
   dimmer resting stream rather than a whole-frame flicker.

   Cost **6.2 ms at the 1216×512 backdrop cap** (0.62 Mpx), a shade under the
   ~8 ms target; it scales linearly with pixels (2.5 ms at 0.24 Mpx, 10.7 at
   1.08). `src/gui/widgets/vis_stream.py`.

   Four traps it taught, each of which shipped wrong first and was found by
   rendering a still and *looking* at it — they generalize past this mode.
   **A hard clamp on a signal that drives a shape is a square-wave generator**:
   the nozzle was `clip(gain * (fast - slow), -1, 1)`, loud music sat on the
   clamp, and every downstream term amplified the corners (`tanh` instead —
   same limit, no corners). **A smoothing kernel written as a fraction of the
   width is a duration only at one flow speed**, hence `_CENTER_SMOOTH_SECONDS`
   in *seconds of signal*. **A bin rate in bins per second is not
   rate-independent on its own** unless you interpolate to the boundary, or a
   33 ms host and a 16 ms host disagree by more than the wiggle they are
   recording. And **a wave's amplitude is only meaningful as a ratio to the
   thing that carries it** — the ribbon looked motionless against a real track
   while the state under it moved exactly as designed, because an 11% swing
   inside a 42%-thick ribbon is not a wave; `_SWING_FRAC` and `_BASE_HALF_FRAC`
   are tuned as a **pair**, against decoded audio, never separately against
   synthetic band heights.

### The beat clock

The beat tunnel is the first visual that *counts beats*, which the kick pulse
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
