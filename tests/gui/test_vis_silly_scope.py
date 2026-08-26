"""The Silly Scope — the backdrop's liquid-gold sheet, and the hose that moves it.

What is worth pinning here is the *mechanism*, not the picture. The look is
judged by rendering stills (``scripts/vis_sheet.py --mode silly_scope``), as it
is for every visual: the suite runs offscreen and styleless and cannot tell
liquid gold from mustard, and both pixel-diff traps in CLAUDE.md apply. So the
assertions are on state — where the wave is, how wide the sheet is, what the
alpha does at the frame's corners — and on sizes, never on a pixel being a
particular colour in a particular place.

The one property that really *is* the feature gets its own test: a spike fed to
the nozzle turns up at the source column first and further along the stream
later. That is the hose, and everything else about the visual is downstream of
it.
"""

import numpy as np
import pytest
from PySide6.QtGui import QColor

from src.gui.widgets import vis_silly_scope
from src.gui.widgets.vis_silly_scope import (
    _BACKDROP_CAP_PX,
    _POPOUT_CAP_PX,
    _WINDOW_SECONDS,
    _GOLD_BASE_HSV,
    SillyScopeScene,
    build_color_lut,
    build_env_ramp,
)
from src.gui.widgets.vis_canvas import (
    FRAME_MS,
    POPOUT_MODES,
    RENDER_MODES,
    VisRenderer,
)
from src.gui.widgets.player_panel import _BACKDROP_VIS_MAP
from src.utils.config import _VALID_VIS_MODES

FRAMES_PER_SECOND = 1000.0 / FRAME_MS


@pytest.fixture
def scene():
    made = SillyScopeScene()
    made.set_frame_interval(FRAME_MS)
    made.set_target_size(912, 384)
    return made


def _loud(rng=None, level=0.85):
    """A band-height vector at roughly *level*."""
    if rng is None:
        return np.full(19, level)
    return np.clip(level * (0.6 + 0.6 * rng.random(19)), 0.0, 1.0)


def _run(scene, seconds, heights=None, pulse=0.0, frame_ms=FRAME_MS):
    frames = int(round(seconds * 1000.0 / frame_ms))
    for _ in range(frames):
        scene.render(_loud() if heights is None else heights, pulse)
    return frames


# ── The hose ───────────────────────────────────────────────────────────────


def test_a_spike_enters_at_the_source_and_travels_to_the_far_end(scene):
    """The whole feature in one assertion: displacement propagates.

    The source is the right edge, where the newest audio is, so a burst shows
    up there first and is found further left as the flow carries it. Half the
    crossing time later it should be somewhere in the middle, and it must not
    have reached the far edge before its time.
    """
    width, height = scene._size
    # Long enough for the *slow* follower to catch the fast one, and then for
    # the tail of that to leave the window: music starting at all is a real
    # event and the hose is right to answer it, so this has to outlast the
    # onset before the spike that follows means anything.
    _run(scene, 30.0, heights=np.full(19, 0.2))
    quiet = scene._centerline(width, height)
    assert np.ptp(quiet) < 0.02 * height  # nothing in flight yet

    # The probe times ride the window: they were 0.6 s and 0.4 s at the
    # original 10 s crossing, and a fixed wait against a 3x faster flow would
    # find the burst a third of the way across before the first look.
    _run(scene, 0.06 * _WINDOW_SECONDS, heights=np.full(19, 1.0))  # the burst
    _run(scene, 0.04 * _WINDOW_SECONDS, heights=np.full(19, 0.2))
    entering = scene._centerline(width, height)
    moved = np.abs(entering - height / 2.0)
    assert moved[-1] > moved[0]  # it is at the source, not at the far end
    assert np.argmax(moved) > 0.8 * width

    _run(scene, _WINDOW_SECONDS / 2.0, heights=np.full(19, 0.2))
    midway = np.abs(scene._centerline(width, height) - height / 2.0)
    peak = int(np.argmax(midway))
    assert 0.25 * width < peak < 0.75 * width


def test_the_wave_takes_the_crossing_time_to_leave(scene):
    width, height = scene._size
    # Settled followers first, and a burst that rides the window: a fixed
    # 1 s burst no longer fits inside a ~1.1 s crossing, so the "entry"
    # measurement would see nothing but the burst's own plateau.
    _run(scene, 30.0, heights=np.full(19, 0.2))
    _run(scene, 0.06 * _WINDOW_SECONDS, heights=np.full(19, 1.0))
    _run(scene, 0.04 * _WINDOW_SECONDS, heights=np.full(19, 0.2))
    swing_at_entry = np.ptp(scene._centerline(width, height))
    _run(scene, _WINDOW_SECONDS + 1.0, heights=np.full(19, 0.2))
    assert np.ptp(scene._centerline(width, height)) < 0.25 * swing_at_entry


def test_a_steady_loud_passage_does_not_wiggle_the_hose(scene):
    """The nozzle is a *band-passed* loudness: dynamics move it, volume does not.

    A track that is simply loud all the way through is a flat sheet, and that
    is the design — the two followers converge and their difference goes to
    zero.
    """
    width, height = scene._size
    _run(scene, 25.0, heights=np.full(19, 0.9))
    assert np.ptp(scene._centerline(width, height)) < 0.03 * height


def test_quiet_music_barely_moves_it_and_leaves_a_thinner_sheet(scene):
    width, height = scene._size
    _run(scene, 20.0, heights=np.full(19, 0.9))
    loud_rows = _sheet_rows(scene)
    scene.reset()
    _run(scene, 20.0, heights=np.full(19, 0.06))
    assert _sheet_rows(scene) < loud_rows


def _sheet_rows(scene):
    """How many rows of the rendered frame carry any gold at all."""
    image = scene.render(np.zeros(19), 0.0)
    alpha = _alpha_of(image)
    return int((alpha.max(axis=1) > 0).sum())


def _alpha_of(image):
    width, height = image.width(), image.height()
    buffer = np.frombuffer(image.constBits(), dtype=np.uint8)
    return buffer.reshape(height, image.bytesPerLine() // 4, 4)[:, :width, 3]


# ── The frame rate law ─────────────────────────────────────────────────────


def test_the_same_second_of_audio_looks_the_same_at_either_rate():
    """Every constant in here is a time, so 16 ms and 33 ms must agree.

    The history is fed in bins per *second* and each bin takes the value the
    nozzle had at its own boundary, interpolated, so the same second of music
    lands in the same place however often the scene is ticked. The comparison
    is on the **centerline** rather than on the raw bins: the two rates end a
    fixed run part-way through different bins, so their arrays are up to one
    bin out of phase with each other while the curve they describe is not, and
    the curve is what gets drawn.
    """
    states = []
    for frame_ms in (16.0, FRAME_MS):
        scene = SillyScopeScene()
        scene.set_frame_interval(frame_ms)
        scene.set_target_size(912, 384)
        scene.reset()
        elapsed = 0.0
        while elapsed < 6.0:
            # A deterministic function of *time*, not a random draw: the two
            # rates would otherwise be fed different music and the test would
            # be measuring that instead.
            level = 0.5 + 0.4 * np.sin(elapsed * 2.0)
            # The dance is driven in beat space, so it must agree too: hand
            # both rates the same beats-per-elapsed-time.
            scene.render(_loud(level=level), 0.0, beat=elapsed * 2.133)
            elapsed += frame_ms / 1000.0
        width, height = scene._size
        states.append((
            scene._centerline(width, height),
            scene._scroll,
            scene._twist_phase,
            scene._presence,
            scene._glow,
            scene._dance_pos,
            scene._melody_fast,
        ))

    fast, slow = states
    assert np.abs(fast[0] - slow[0]).max() < 0.006 * 384  # a couple of pixels
    assert fast[1] == pytest.approx(slow[1], rel=0.01)
    assert fast[2] == pytest.approx(slow[2], rel=0.01)
    assert fast[3] == pytest.approx(slow[3], abs=0.02)
    assert fast[4] == pytest.approx(slow[4], abs=0.02)
    assert fast[5] == pytest.approx(slow[5], abs=0.02)
    assert fast[6] == pytest.approx(slow[6], abs=0.02)


def test_setting_the_rate_is_not_undone_by_a_reset(scene):
    """vis_sheet sets the interval before the mode, and the mode calls reset."""
    scene.set_frame_interval(16.0)
    before = scene._dt
    scene.reset()
    assert scene._dt == before


# ── Size, cost and the image contract ──────────────────────────────────────


def test_a_big_host_is_capped_by_area_with_its_aspect_held(scene):
    scene.set_target_size(2400, 1000)
    width, height = scene._size
    assert width * height <= _BACKDROP_CAP_PX * 1.01
    assert width * height > _BACKDROP_CAP_PX * 0.95  # capped, not shrunk to a floor
    assert width / height == pytest.approx(2400 / 1000, rel=0.01)
    assert (scene.image().width(), scene.image().height()) == (width, height)


def test_a_host_under_the_cap_renders_native(scene):
    scene.set_target_size(760, 320)
    assert scene._size == (760, 320)


def test_the_popouts_cap_is_the_larger_one(scene):
    """Backdrop only today; the split is stated rather than implied.

    If the scope is ever offered in the popout the budget there is bigger —
    one drawImage instead of a playlist repaint — so the number lives here
    rather than being worked out later.
    """
    assert _POPOUT_CAP_PX > _BACKDROP_CAP_PX
    scene.set_target_size(2400, 1000, popout=True)
    width, height = scene._size
    assert width * height > _BACKDROP_CAP_PX


def test_a_host_that_is_not_on_screen_yet_keeps_the_previous_size(scene):
    before = scene._size
    scene.set_target_size(0, 0)
    scene.set_target_size(-4, 120)
    assert scene._size == before


def test_the_frame_is_transparent_where_the_stream_is_not(scene):
    """The backdrop composites over the playlist grey: an opaque frame would
    paint the rows out entirely.

    Checked on the *settled* sheet: at the doubled swing a full-scale onset
    crest legitimately brushes the frame edge at the source (and is clipped
    there, like the stream running off the sides), so the corners are only
    guaranteed clear once the followers have converged and the onset has
    left the window.
    """
    _run(scene, 20.0)
    image = scene.render(_loud(), 0.0)
    alpha = _alpha_of(image)
    assert alpha[0, 0] == 0
    assert alpha[0, -1] == 0
    assert alpha[-1, 0] == 0
    assert alpha[-1, -1] == 0
    assert alpha.max() == 255  # and the stream itself is solid


def test_the_image_is_its_own_copy_not_a_view_of_a_numpy_buffer(scene):
    """QImage does not own the memory it is handed; two frames must differ."""
    first = scene.render(_loud(), 0.0)
    kept = first.copy()
    _run(scene, 1.0)
    second = scene.render(_loud(), 0.0)
    assert first is not second
    assert kept == first


# ── Reset ──────────────────────────────────────────────────────────────────


def test_reset_forgets_the_stream(scene):
    _run(scene, 6.0, pulse=1.0)
    scene.reset()
    assert np.all(scene._history == 0.0)
    assert scene._scroll == 0.0
    assert np.ptp(scene._centerline(*scene._size)) == 0.0


# ── The beat, stamped at the source ────────────────────────────────────────


def _twin_scenes_final_frames(pulse_pair):
    """Two scenes fed identical music; only the final frame's pulse differs.

    The scene is deterministic (no rng anywhere since the droplets left), so
    any difference between the frames is the pulse's doing alone.
    """
    frames = []
    for pulse in pulse_pair:
        scene = SillyScopeScene()
        scene.set_frame_interval(FRAME_MS)
        scene.set_target_size(912, 384)
        _run(scene, 4.0)
        frames.append(scene.render(_loud(), pulse))
    return frames


def _lit_mean_rgb(image):
    """Mean RGB over the pixels the stream actually covers."""
    width, height = image.width(), image.height()
    buffer = np.frombuffer(image.constBits(), dtype=np.uint8)
    bgra = buffer.reshape(height, image.bytesPerLine() // 4, 4)[:, :width]
    return float(bgra[..., :3][bgra[..., 3] > 0].mean())


def _bgra_of(image):
    width, height = image.width(), image.height()
    buffer = np.frombuffer(image.constBits(), dtype=np.uint8).copy()
    return buffer.reshape(height, image.bytesPerLine() // 4, 4)[:, :width]


def test_between_beats_the_stream_rests_dim_and_a_kick_lights_it():
    """The floor/peak pair: a pulse-free stream sits well below a kicked
    one, which is what makes a surge readable at all."""
    frames = []
    for pulse in (0.0, 1.0):
        made = SillyScopeScene()
        made.set_frame_interval(FRAME_MS)
        made.set_target_size(912, 384)
        _run(made, 4.0, pulse=pulse)
        frames.append(made.render(_loud(), pulse))
    calm, hot = frames
    assert _lit_mean_rgb(hot) > _lit_mean_rgb(calm) * 1.3


def test_a_kick_is_stamped_at_the_source_and_travels_with_the_stream():
    """The beat is *in the stream*: one kick brightens what is leaving the
    nozzle, and that bright surge is found further along later — the hose
    property, again, for brightness. Twin scenes fed identical music isolate
    it: the per-column difference between them is exactly the surge."""
    scenes = []
    for _ in range(2):
        made = SillyScopeScene()
        made.set_frame_interval(FRAME_MS)
        made.set_target_size(912, 384)
        _run(made, 4.0)
        scenes.append(made)
    with_kick, without = scenes
    with_kick.render(_loud(), 1.0)
    without.render(_loud(), 0.0)
    width = with_kick._size[0]

    def surge_column(delay_seconds):
        for _ in range(int(round(delay_seconds * FRAMES_PER_SECOND))):
            with_kick.render(_loud(), 0.0)
            without.render(_loud(), 0.0)
        kicked = _bgra_of(with_kick.render(_loud(), 0.0))
        plain = _bgra_of(without.render(_loud(), 0.0))
        diff = np.abs(
            kicked[..., :3].astype(int) - plain[..., :3].astype(int)
        ).sum(axis=(0, 2))
        return int(np.argmax(diff))

    # No extra delay for the first look: the kick frame and the measuring
    # frame are already ~0.07 s of travel, which at a ~0.5 s crossing is an
    # eighth of the window on their own.
    assert surge_column(0.0) > 0.75 * width
    assert 0.25 * width < surge_column(0.4 * _WINDOW_SECONDS) < 0.75 * width


def test_the_beat_is_brightness_only_and_never_moves_the_silhouette():
    """Alpha comes from the sheet coordinate and the silence fade, never
    from the beat, so a kick must not fatten, shrink or displace the
    stream."""
    calm, kicked = _twin_scenes_final_frames((0.0, 1.0))
    assert np.array_equal(_alpha_of(calm), _alpha_of(kicked))


def test_no_sound_dims_the_whole_sheet_to_nothing(scene):
    """The fractal's fade, on the sheet: silence releases the glow envelope
    and the shade *and* the alpha follow it, so the frame ends fully
    transparent rather than as a dark opaque ribbon over the playlist."""
    _run(scene, 10.0)
    assert _alpha_of(scene.render(_loud(), 0.0)).max() == 255
    _run(scene, 4.0, heights=np.zeros(19))
    assert _alpha_of(scene.render(np.zeros(19), 0.0)).max() == 0


def test_the_fade_is_a_release_and_the_return_is_instant(scene):
    """Fast attack, slow release — the fractal's envelope shape. Part-way
    through the fade the sheet is dimmed, not gone; the first loud frame
    brings it back at full strength."""
    _run(scene, 10.0)
    _run(scene, 0.1, heights=np.zeros(19))
    mid = _alpha_of(scene.render(np.zeros(19), 0.0)).max()
    assert 0 < mid < 255
    _run(scene, 4.0, heights=np.zeros(19))
    assert _alpha_of(scene.render(np.zeros(19), 0.0)).max() == 0
    assert _alpha_of(scene.render(_loud(), 0.0)).max() == 255


def test_the_droplets_are_gone():
    """Nothing left behind that a later edit could route back to."""
    for name in ("_DROP_MAX", "_DROP_PULSE", "_DROP_RADIUS_FRAC"):
        assert not hasattr(vis_silly_scope, name)
    scene = SillyScopeScene()
    assert not hasattr(scene, "_drops")
    assert not hasattr(scene, "_stamp_drops")


# ── The dance ──────────────────────────────────────────────────────────────


def _beat_feed(scene, seconds, bpm=128.0, start_beat=0.0, heights=None):
    """Run the scene with a synthetic beat clock advancing at *bpm*."""
    frames = int(round(seconds * FRAMES_PER_SECOND))
    beat = start_beat
    per_frame = bpm / 60.0 * (FRAME_MS / 1000.0)
    for _ in range(frames):
        scene.render(_loud() if heights is None else heights, 0.0, beat)
        beat += per_frame
    return beat


def test_the_source_turns_on_the_four_beat_grid(scene):
    beat = _beat_feed(scene, 2.0)  # ~4.3 beats at 128: crosses beat 4
    assert scene._last_turn == 4
    target = scene._dance_target
    assert target != 0.0
    _beat_feed(scene, 1.0, start_beat=beat)  # to ~6.4: inside the phrase
    assert scene._last_turn == 4  # no turning point between the boundaries
    assert scene._dance_target == target


def test_turns_alternate_and_phrase_edges_move_further_and_quicker(scene):
    _beat_feed(scene, 2.0)  # crosses 4
    span_4 = scene._dance_span
    sign_4 = np.sign(scene._dance_target)
    amp_4 = abs(scene._dance_target)
    _beat_feed(scene, 2.0, start_beat=4.3)  # crosses 8
    assert scene._last_turn == 8
    assert np.sign(scene._dance_target) == -sign_4  # back and forth
    _beat_feed(scene, 4.0, start_beat=8.5)  # crosses 12 and then 16
    assert scene._last_turn == 16
    assert abs(scene._dance_target) > amp_4  # a phrase edge swings further
    assert scene._dance_span < span_4  # and arrives quicker


def test_the_dance_reaches_the_painted_source(scene):
    """The choreography is not private state: after a couple of phrases the
    newest columns sit away from mid-height, on steady music whose loudness
    wiggle alone would leave the source centred."""
    width, height = scene._size
    _beat_feed(scene, 4.0)
    centre = scene._centerline(width, height)
    assert abs(centre[-1] - 0.5 * height) > 0.05 * height


def test_no_clock_means_no_dance(scene):
    _run(scene, 4.0)
    assert scene._dance_pos == 0.0
    assert scene._last_turn == 0


def test_the_melody_follower_reads_the_mid_highs_not_the_bass(scene):
    """Bass-heavy music must not drive the melody term — that is the whole
    request. Two bursts of equal overall shape, one in band 2 (~100 Hz) and
    one in band 12 (~1.6 kHz): only the second reaches the melody follower."""
    bass = np.zeros(19, dtype=np.float32)
    bass[2] = 0.9
    _run(scene, 2.0, heights=bass)
    from_bass = scene._melody_fast
    scene.reset()
    mids = np.zeros(19, dtype=np.float32)
    mids[12] = 0.9
    _run(scene, 2.0, heights=mids)
    assert from_bass == 0.0
    assert scene._melody_fast > 0.3


# ── The tables ─────────────────────────────────────────────────────────────


def test_the_environment_ramp_has_more_than_one_step_in_it():
    """The chrome answer: layers of contrast, and they are free.

    A flat pool that maps to one plateau and one hard step is what reads as
    posterized paper rather than as liquid, so what matters about this table is
    that it turns over repeatedly — not where any one band sits.
    """
    ramp = build_env_ramp()
    assert ramp.dtype == np.float32
    assert 0.0 <= ramp.min() and ramp.max() <= 1.0
    turns = np.diff(np.sign(np.diff(ramp)))
    assert np.count_nonzero(turns) >= 6


def test_the_default_lut_is_the_gold_and_runs_dark_to_light():
    lut = build_color_lut(QColor.fromHsvF(*_GOLD_BASE_HSV))
    assert lut.shape == (256, 4)
    blue, green, red = lut[:, 0].astype(int), lut[:, 1].astype(int), lut[:, 2].astype(int)
    assert np.all(np.diff(red) >= 0)
    assert red[0] < red[-1]
    # Gold, not amber-to-white via grey: red leads green leads blue throughout.
    assert np.all(red >= green) and np.all(green >= blue)


def test_the_lut_wears_the_selected_hue_and_still_peaks_near_white():
    """The recipe is hue-generic: a blue selection makes a blue liquid whose
    highlights still burn out toward white, exactly as the gold's do."""
    lut = build_color_lut(QColor("#2266ff"))
    mid = slice(64, 192)
    assert lut[mid, 0].mean() > lut[mid, 2].mean()  # B leads R through the body
    assert min(int(v) for v in lut[255, :3]) > 210  # top of the ramp is near-white


def test_the_colour_setting_recolours_the_stream(scene):
    """The stream wears the waveform colour now — the fixed-gold ruling was
    reversed on request. Same music, two colours, different pixels, and the
    hue really lands on the sheet."""
    _run(scene, 2.0)
    gold = _bgra_of(scene.render(_loud(), 0.0))
    scene.set_color("#2266ff")
    scene.reset()
    _run(scene, 2.0)
    blue = _bgra_of(scene.render(_loud(), 0.0))
    lit = blue[..., 3] > 0
    assert blue[..., 0][lit].mean() > blue[..., 2][lit].mean()  # blue leads red
    gold_lit = gold[..., 3] > 0
    assert gold[..., 2][gold_lit].mean() > gold[..., 0][gold_lit].mean()


# ── How it joins the renderer ──────────────────────────────────────────────


def test_it_renders_and_is_not_offered_in_the_popout():
    """Fire's shape from the other end: a mode may render and not be offered."""
    assert "silly_scope" in RENDER_MODES
    assert "silly_scope" not in POPOUT_MODES
    assert "silly_scope" not in _VALID_VIS_MODES  # it is not a menu id
    assert _BACKDROP_VIS_MAP["backdrop_scope"] == "silly_scope"


def test_the_renderer_returns_the_scenes_image_and_never_keeps_it(qapp):
    """The corner-drawing trap: the shared 152x64 image must stay 152x64."""
    renderer = VisRenderer()
    renderer.set_mode("silly_scope")
    renderer.set_target_size(1216, 512)
    rng = np.random.default_rng(0)
    image = renderer.render(rng.normal(0, 0.2, 2048).astype(np.float32), 44100)
    assert image.width() * image.height() <= _BACKDROP_CAP_PX * 1.01
    assert renderer.image() is image
    renderer.set_mode("spectrum")
    after = renderer.render(rng.normal(0, 0.2, 2048).astype(np.float32), 44100)
    assert (after.width(), after.height()) == (152, 64)


def test_the_renderer_ticks_the_beat_clock_for_this_mode(qapp):
    """The dance's clock: silly_scope joined beat_tunnel as a mode that
    counts beats, so rendering must advance the clock's phase and feed the
    kick flux it locks from."""
    renderer = VisRenderer()
    renderer.set_mode("silly_scope")
    renderer.set_target_size(912, 384)
    renderer.set_track_tempo(128.0)
    rng = np.random.default_rng(3)
    for _ in range(30):
        renderer.render(rng.normal(0, 0.4, 2048).astype(np.float32), 44100)
    assert renderer._clock.phase > 0.5
    assert renderer._prev_log is not None  # kick flux really computed


def test_the_renderer_smooths_it_and_keeps_the_backdrops_own_rate(qapp):
    renderer = VisRenderer()
    renderer.set_mode("silly_scope")
    assert renderer.smooth_upscale() is True
    assert renderer.frame_ms() == FRAME_MS


def test_switching_to_it_clears_whatever_the_last_run_left(qapp):
    renderer = VisRenderer()
    renderer.set_mode("silly_scope")
    renderer.set_target_size(912, 384)
    rng = np.random.default_rng(1)
    for _ in range(120):
        renderer.render(rng.normal(0, 0.5, 2048).astype(np.float32), 44100)
    assert np.any(renderer._silly_scope._history != 0.0)
    renderer.set_mode("silly_scope")
    assert np.all(renderer._silly_scope._history == 0.0)


def test_silence_is_a_frame_it_can_render(qapp):
    """What the backdrop feeds after a pause, for _VIS_DECAY_MS."""
    renderer = VisRenderer()
    renderer.set_mode("silly_scope")
    renderer.set_target_size(912, 384)
    image = renderer.render(None, 44100)
    assert image.width() > 0


def test_the_retro_backdrop_face_is_gone(qapp):
    """Nothing left behind that a later edit could route back to."""
    assert not hasattr(VisRenderer, "_render_scope")
    assert not hasattr(vis_silly_scope, "_SCOPE_LEVELS")
    from src.gui.widgets import vis_canvas

    assert not hasattr(vis_canvas, "_SCOPE_SAMPLES")
    assert not hasattr(vis_canvas, "_SCOPE_LEVELS")
