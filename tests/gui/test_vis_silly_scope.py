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

from src.gui.widgets import vis_silly_scope
from src.gui.widgets.vis_silly_scope import (
    _BACKDROP_CAP_PX,
    _DROP_MAX,
    _POPOUT_CAP_PX,
    _WINDOW_SECONDS,
    SillyScopeScene,
    build_env_ramp,
    build_gold_lut,
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

    _run(scene, 0.6, heights=np.full(19, 1.0))  # the burst
    _run(scene, 0.4, heights=np.full(19, 0.2))
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
    _run(scene, 1.0, heights=np.full(19, 1.0))
    _run(scene, 0.5, heights=np.full(19, 0.2))
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
            scene.render(_loud(level=level), 0.0)
            elapsed += frame_ms / 1000.0
        width, height = scene._size
        states.append((
            scene._centerline(width, height),
            scene._scroll,
            scene._twist_phase,
            scene._presence,
        ))

    fast, slow = states
    assert np.abs(fast[0] - slow[0]).max() < 0.006 * 384  # a couple of pixels
    assert fast[1] == pytest.approx(slow[1], rel=0.01)
    assert fast[2] == pytest.approx(slow[2], rel=0.01)
    assert fast[3] == pytest.approx(slow[3], abs=0.02)


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
    """
    _run(scene, 3.0)
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
    assert scene._drops
    scene.reset()
    assert not scene._drops
    assert np.all(scene._history == 0.0)
    assert scene._scroll == 0.0
    assert np.ptp(scene._centerline(*scene._size)) == 0.0


# ── Droplets ───────────────────────────────────────────────────────────────


def test_beads_are_flicked_on_kicks_and_are_bounded(scene):
    _run(scene, 8.0, pulse=1.0)
    assert 0 < len(scene._drops) <= _DROP_MAX


def test_no_kick_no_beads(scene):
    _run(scene, 8.0, pulse=0.0)
    assert scene._drops == []


def test_beads_belong_to_the_size_they_were_flicked_at(scene):
    """They are positioned in pixels, so a resize is not something to rescale."""
    _run(scene, 6.0, pulse=1.0)
    assert scene._drops
    scene.set_target_size(1200, 500)
    assert scene._drops == []


def test_a_bead_falls_back_down(scene):
    _run(scene, 1.0, pulse=1.0)
    assert scene._drops
    drop = scene._drops[0]
    top = drop[1]
    for _ in range(60):
        scene.render(_loud(), 0.0)
        if drop not in scene._drops:
            break
    assert drop[1] > top or drop not in scene._drops


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


def test_the_gold_runs_dark_to_light_and_is_gold_all_the_way():
    lut = build_gold_lut()
    assert lut.shape == (256, 4)
    blue, green, red = lut[:, 0].astype(int), lut[:, 1].astype(int), lut[:, 2].astype(int)
    assert np.all(np.diff(red) >= 0)
    assert red[0] < red[-1]
    # Gold, not amber-to-white via grey: red leads green leads blue throughout.
    assert np.all(red >= green) and np.all(green >= blue)


def test_the_colour_setting_is_accepted_and_ignored(scene):
    """It exists so the renderer can forward the setting without asking who cares."""
    before = scene.render(_loud(), 0.0).copy()
    scene.set_color("#00ff00")
    scene.reset()
    after = scene.render(_loud(), 0.0)
    assert before == after


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
