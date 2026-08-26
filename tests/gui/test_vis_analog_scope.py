"""The analog scope — what the ``oscilloscope`` mode draws, in either host.

It used to be the *popout's face* of a mode with two of them, the backdrop
wearing a chunky 152x64 retro grid. That grid is gone: the backdrop's scope
slot draws ``stream`` now (a separate mode id — see
``test_vis_stream.py``), so this mode has one picture again and the tests
that pinned the split pin the retirement instead.

Assertions are on the scene's arrays and on image *sizes*, never on a pixel
being a particular colour at a particular place. The suite runs styleless and
offscreen, and both pixel-diff traps in CLAUDE.md (device pixel ratio, the
missing stylesheet) apply. Where a pixel is read at all it is only compared
against *the same pixel of another frame of the same scene*, which those traps
do not reach; the look itself is judged by rendering stills with
``scripts/vis_sheet.py --mode oscilloscope --popout``, as it is for every
visual.
"""

import numpy as np
import pytest

from src.gui.widgets.player_panel import _BACKDROP_VIS_MAP
from src.gui.widgets import vis_analog_scope
from src.gui.widgets.vis_analog_scope import (
    _AXIS_LEVEL,
    _BACKDROP_CAP_PX,
    _GRID_LEVEL,
    _GRID_ROWS,
    _POPOUT_CAP_PX,
    _WINDOW,
    AnalogScopeScene,
    build_graticule,
    build_lut,
    find_trigger,
)
from src.gui.widgets.vis_canvas import (
    FAST_FRAME_MS,
    FFT_SIZE,
    FRAME_MS,
    POPOUT_MODES,
    RENDER_MODES,
    VisRenderer,
)
from src.utils.config import _VALID_VIS_MODES

SR = 44100


def tone(freq=220.0, seconds=2.0, sr=SR, phase=0.0):
    t = np.arange(int(sr * seconds)) / sr
    return (0.7 * np.sin(2 * np.pi * freq * t + phase)).astype(np.float32)


def play(scene, signal, frames=40, frame_ms=16.0, sr=SR):
    """Feed *frames* consecutive blocks, the way the popout's timer does."""
    pos = FFT_SIZE
    hop = int(sr * frame_ms / 1000.0)
    for _ in range(frames):
        scene.render(signal[pos - FFT_SIZE : pos], sr)
        pos += hop
    return scene


@pytest.fixture
def scene(qapp):
    """A scene at a modest popout size. qapp because building a QImage needs one."""
    sc = AnalogScopeScene()
    sc.set_frame_interval(float(FAST_FRAME_MS))
    sc.set_target_size(640, 320, popout=True)
    return sc


# ── The host split ─────────────────────────────────────────────────────────


def test_a_host_that_never_said_popout_gets_the_scene_too(qapp):
    """The retro face is retired: there is one picture, at the backdrop's cap.

    Nothing routes here without ``popout=True`` today — the backdrop's scope
    slot draws the stream — but the scene has always carried a backdrop
    cap for the host it never meets, and ``vis_sheet --mode oscilloscope``
    without ``--popout`` drives exactly this path.
    """
    renderer = VisRenderer()
    renderer.set_mode("oscilloscope")
    renderer.set_target_size(2400, 1200)  # popout defaults False
    image = renderer.render(tone()[:FFT_SIZE], SR)
    # The cap is on the area, but each dimension is rounded to a whole pixel
    # afterwards, so the product can land a few hundred pixels over it. That
    # slack is the rounding, not a leak.
    assert image.width() * image.height() <= _BACKDROP_CAP_PX * 1.01
    assert (image.width(), image.height()) != (152, 64)
    assert renderer.image() is image


def test_the_popout_gets_the_scene_at_the_hosts_size(qapp):
    renderer = VisRenderer()
    renderer.set_mode("oscilloscope")
    renderer.set_target_size(1216, 512, popout=True)
    image = renderer.render(tone()[:FFT_SIZE], SR)
    assert (image.width(), image.height()) == (1216, 512)
    assert renderer.image() is image


def test_the_scenes_image_is_never_left_in_the_shared_one(qapp):
    """The corner-drawing trap: return the big image, never assign it.

    The scope and spectrum renderers paint into ``_image`` at 152x64. A
    1216-wide one left there would have the next spectrum frame drawn into a
    corner of it, and every host would stretch the result.
    """
    renderer = VisRenderer()
    renderer.set_mode("oscilloscope")
    renderer.set_target_size(1216, 512, popout=True)
    renderer.render(tone()[:FFT_SIZE], SR)
    renderer.set_mode("spectrum")
    image = renderer.render(tone()[:FFT_SIZE], SR)
    assert (image.width(), image.height()) == (152, 64)


def test_the_smoothing_is_a_question_about_the_mode_again(qapp):
    """It used to split per host, and the reason for that split is gone.

    While the backdrop wore the chunky grid, "should the host interpolate?" had
    two answers for one mode id. Now the glow field is the only picture this
    mode draws, so both hosts get the same answer — and it is True, because a
    glow field would staircase once the area cap bites.
    """
    backdrop = VisRenderer()
    backdrop.set_mode("oscilloscope")
    backdrop.set_target_size(1216, 512)
    assert backdrop.smooth_upscale() is True

    popout = VisRenderer()
    popout.set_mode("oscilloscope")
    popout.set_target_size(1216, 512, popout=True)
    assert popout.smooth_upscale() is True

    assert backdrop.frame_ms() == popout.frame_ms() == FAST_FRAME_MS


def test_the_mode_id_and_the_config_set_did_not_move():
    """The scope keeps its own id and its popout row; only the backdrop left.

    ``backdrop_scope`` still names a valid setting and still selects — it just
    draws the stream now, which is why there is no migration on either
    side of this change.
    """
    assert "oscilloscope" in RENDER_MODES
    assert "oscilloscope" in POPOUT_MODES
    assert "oscilloscope" in _VALID_VIS_MODES
    assert "backdrop_scope" in _VALID_VIS_MODES
    assert _BACKDROP_VIS_MAP["backdrop_scope"] == "stream"


# ── Size and the frame budget ──────────────────────────────────────────────


def test_a_big_host_is_capped_by_area_with_its_aspect_held(scene):
    scene.set_target_size(2800, 1600, popout=True)
    height, width = scene._buf.shape
    assert width * height <= _POPOUT_CAP_PX
    assert width * height > _POPOUT_CAP_PX * 0.95  # capped, not shrunk to a floor
    assert width / height == pytest.approx(2800 / 1600, rel=0.01)
    assert (scene.image().width(), scene.image().height()) == (width, height)


def test_a_host_under_the_cap_renders_native(scene):
    scene.set_target_size(1216, 512, popout=True)
    assert scene._buf.shape == (512, 1216)


def test_the_backdrops_cap_is_the_smaller_one(scene):
    """It never reaches this scene today; the split is stated, not implied."""
    scene.set_target_size(2800, 1600, popout=False)
    height, width = scene._buf.shape
    assert width * height <= _BACKDROP_CAP_PX


def test_a_host_that_is_not_on_screen_yet_keeps_the_previous_size(scene):
    before = scene._buf.shape
    scene.set_target_size(0, 0, popout=True)
    scene.set_target_size(-4, 120, popout=True)
    assert scene._buf.shape == before


# ── The trigger ────────────────────────────────────────────────────────────


def test_the_trace_stands_still_on_a_steady_tone(qapp):
    """Successive blocks of one sine trigger on the same point in the cycle.

    That is the whole difference between an oscilloscope and noise scrolling
    past, and it is asserted on the *displayed samples* rather than on the
    index: two different indexes one period apart are the same picture.
    """
    signal = tone(freq=200.0, seconds=2.0)
    hop = int(SR * FAST_FRAME_MS / 1000.0)
    pos = FFT_SIZE
    target = 0
    traces = []
    for _ in range(12):
        block = signal[pos - FFT_SIZE : pos]
        target = find_trigger(block, target, _WINDOW)
        traces.append(block[target : target + 64])
        target -= hop
        pos += hop
    first = traces[0]
    for trace in traces[1:]:
        assert np.abs(trace - first).max() < 0.02


def test_a_crossing_nearer_the_target_wins(qapp):
    """Continuity: not "the first crossing", which swaps alignment.

    A waveform with several rising crossings per cycle has several candidate
    alignments; picking the nearest to where the last frame's trigger has
    drifted to is what stops the trace hopping between them.
    """
    block = np.full(FFT_SIZE, -0.5, dtype=np.float32)
    for start in (100, 400, 700):
        block[start + 1 : start + 40] = 0.5
    assert find_trigger(block, 380, _WINDOW) == 400
    assert find_trigger(block, 690, _WINDOW) == 700
    assert find_trigger(block, 0, _WINDOW) == 100


def test_silence_and_dc_fall_back_to_the_clamped_target(qapp):
    limit = FFT_SIZE - _WINDOW
    assert find_trigger(np.zeros(FFT_SIZE, dtype=np.float32), 300, _WINDOW) == 300
    assert find_trigger(np.full(FFT_SIZE, 0.4, dtype=np.float32), 300, _WINDOW) == 300
    # ...and never past the point where the window would run off the block.
    assert find_trigger(np.zeros(FFT_SIZE, dtype=np.float32), 99999, _WINDOW) == limit
    assert find_trigger(np.zeros(FFT_SIZE, dtype=np.float32), -50, _WINDOW) == 0


def test_a_block_shorter_than_the_window_triggers_at_zero(qapp):
    assert find_trigger(tone(seconds=0.01)[:200], 40, _WINDOW) == 0


# ── The phosphor ───────────────────────────────────────────────────────────


def test_a_still_beam_settles_rather_than_running_away(scene):
    """The ceiling is what keeps a held note from pinning the whole trace white."""
    play(scene, tone(freq=110.0), frames=120)
    assert scene._buf.max() <= 1.61


def test_the_same_second_of_audio_looks_the_same_at_either_rate(qapp):
    """A decay written per frame is a duration only at one frame rate.

    The stamp is scaled by (1 - decay) for the same reason: without it the
    33 ms host would settle 1.75x dimmer for identical audio, which reads as
    tuning rather than as a bug.
    """
    signal = tone(freq=220.0, seconds=2.0)
    settled = []
    for frame_ms in (float(FRAME_MS), float(FAST_FRAME_MS)):
        sc = AnalogScopeScene()
        sc.set_frame_interval(frame_ms)
        sc.set_target_size(640, 320, popout=True)
        elapsed = 0.0
        pos = FFT_SIZE
        while elapsed < 1.0:  # one second of the same audio, either way
            sc.render(signal[pos - FFT_SIZE : pos], SR)
            pos += int(SR * frame_ms / 1000.0)
            elapsed += frame_ms / 1000.0
        settled.append(sc._buf)
    assert settled[0].max() == pytest.approx(settled[1].max(), rel=0.05)
    assert settled[0].mean() == pytest.approx(settled[1].mean(), rel=0.10)


def test_silence_decays_toward_the_flat_line(scene):
    play(scene, tone(freq=110.0), frames=60)
    lit = scene._buf.copy()
    height = scene._buf.shape[0]
    middle = height // 2
    energies = []
    for _ in range(30):
        scene.render(None, SR)
        rows = np.arange(height)
        away = scene._buf[np.abs(rows - middle) > 3]
        energies.append(float(away.sum()))
    # Everything that is not the flat line the beam has fallen to fades, and
    # keeps fading — monotonically, because the only input is the decay.
    assert energies[0] < float(lit[np.abs(np.arange(height) - middle) > 3].sum())
    assert all(b < a for a, b in zip(energies, energies[1:]))
    assert energies[-1] < energies[0] * 0.05


def test_a_fast_beam_lays_down_less_per_pixel_than_a_slow_one(scene):
    """The CRT's own behaviour, and mostly free: a point is a slice of *time*.

    A square wave spends nearly all of it on the two flat levels and crosses
    between them in a handful of samples, so the crossing columns must come out
    dimmer per lit pixel than the flat ones.
    """
    t = np.arange(SR) / SR
    square = (0.8 * np.sign(np.sin(2 * np.pi * 60.0 * t))).astype(np.float32)
    play(scene, square, frames=40)
    buf = scene._buf
    height = scene._buf.shape[0]
    middle = height // 2
    band = 8
    flat = buf[np.abs(np.arange(height) - middle) > band]
    crossing = buf[np.abs(np.arange(height) - middle) <= band]
    assert flat.max() > 4 * crossing.max()


def test_the_beam_stays_a_continuous_thread_on_a_steep_edge(scene):
    """The oversample-plus-vertical-split half of the same problem.

    One pixel per path point dots a near-vertical segment; the trace has to
    reach every row between the two levels, not just some of them.
    """
    t = np.arange(SR) / SR
    square = (0.8 * np.sign(np.sin(2 * np.pi * 60.0 * t))).astype(np.float32)
    play(scene, square, frames=20)
    lit_rows = (scene._buf > 1e-4).any(axis=1)
    height = scene._buf.shape[0]
    top, bottom = np.flatnonzero(lit_rows)[[0, -1]]
    assert lit_rows[top : bottom + 1].all()
    assert bottom - top > height * 0.6  # it really is spanning the frame


def test_a_resize_reallocates_and_the_next_frame_still_renders(scene):
    play(scene, tone(), frames=10)
    scene.set_target_size(900, 300, popout=True)
    assert scene._buf.shape == (300, 900)
    assert not scene._buf.any()  # the trails belong to the old geometry
    image = scene.render(tone()[:FFT_SIZE], SR)
    assert (image.width(), image.height()) == (900, 300)


def test_reset_forgets_the_picture_but_not_the_rate(scene):
    """vis_sheet sets the interval before the mode, and set_mode is what resets."""
    scene.set_frame_interval(float(FRAME_MS))
    decay = scene._decay
    play(scene, tone(), frames=10)
    scene.reset()
    assert not scene._buf.any()
    assert scene._decay == decay


# ── The palette ────────────────────────────────────────────────────────────


def test_the_ramp_runs_black_to_green_to_white():
    lut = build_lut()
    assert tuple(lut[0]) == (0, 0, 0, 0)
    blue, green, red, alpha = lut[255]
    assert (blue, green, red, alpha) == (255, 255, 255, 255)
    mid = lut[128]
    assert mid[1] > mid[0] and mid[1] > mid[2]  # green channel leads
    # Monotone in every channel, so no band of the ramp goes backwards.
    for channel in range(4):
        assert np.all(np.diff(lut[:, channel].astype(int)) >= 0)


def test_the_colour_setting_is_deliberately_ignored(scene):
    """Every other visual follows it; this one is a green CRT by definition."""
    before = scene._lut.copy()
    scene.set_color("#ff00ff")
    assert np.array_equal(scene._lut, before)


# ── The graticule ──────────────────────────────────────────────────────────


def test_the_divisions_are_square_on_a_wide_host():
    """A 2.4:1 popout with 10 fixed columns draws a spreadsheet, not a scope."""
    grid = build_graticule(512, 1216)
    assert grid is not None
    lit_rows = np.flatnonzero((grid > 0).sum(axis=1) > grid.shape[1] * 0.5)
    lit_cols = np.flatnonzero((grid > 0).sum(axis=0) > grid.shape[0] * 0.5)
    # Interior division lines, plus the centre axis which is one of them.
    row_gap = np.diff(lit_rows).max()
    col_gap = np.diff(lit_cols).max()
    assert row_gap == pytest.approx(col_gap, rel=0.1)
    assert len(lit_rows) >= _GRID_ROWS - 1


def test_the_centre_axes_are_picked_out():
    grid = build_graticule(512, 1216)
    assert grid[(512 - 1) // 2].max() == pytest.approx(_AXIS_LEVEL)
    division = grid[grid > 0]
    assert division.min() == pytest.approx(_GRID_LEVEL)


def test_the_line_weight_follows_the_resolution():
    """An etched line is a physical width, not a pixel; see _GRID_REF_H."""

    def axis_thickness(grid):
        mid = (grid.shape[0] - 1) // 2
        column = grid[:, grid.shape[1] // 4]
        return int((column >= _AXIS_LEVEL)[mid : mid + 6].sum())

    thin = build_graticule(512, 1216)
    thick = build_graticule(1024, 880)
    assert axis_thickness(thick) > axis_thickness(thin)


def test_it_is_switched_off_cleanly(monkeypatch):
    monkeypatch.setattr(vis_analog_scope, "_GRID_ON", False)
    assert build_graticule(512, 1216) is None
    scene = AnalogScopeScene()
    scene.set_target_size(640, 320, popout=True)
    image = scene.render(tone()[:FFT_SIZE], SR)  # no grid, no crash
    assert (image.width(), image.height()) == (640, 320)


def test_a_host_too_small_to_divide_gets_none():
    assert build_graticule(8, 8) is None


def test_the_grid_never_enters_the_phosphor(scene):
    """It is laid over the frame, not stamped into it.

    Inside the buffer it would decay, bloom, and — because the buffer is
    multiplied and added to every frame — accumulate to its own steady state,
    so a static grid would drift in brightness for the first second and pick up
    a halo it should not have.
    """
    for _ in range(40):
        scene.render(None, SR)  # silence: only the flat line is drawn
    height, width = scene._buf.shape
    middle = height // 2
    away = scene._buf[np.abs(np.arange(height) - middle) > 4]
    assert away.max() == pytest.approx(0.0, abs=1e-6)


def test_the_grid_is_the_same_every_frame(scene):
    """Constant, not accumulating — the layer is added, never fed back."""
    first = scene.render(None, SR).copy()
    second = scene.render(None, SR).copy()
    corner = (scene.image().width() // 4, 4)
    assert first.pixelColor(*corner) == second.pixelColor(*corner)


def test_it_is_rebuilt_when_the_host_resizes(scene):
    scene.render(tone()[:FFT_SIZE], SR)
    assert scene._grid is not None and scene._grid.shape == scene._buf.shape
    scene.set_target_size(900, 300, popout=True)
    assert scene._grid is None  # dropped, not stretched
    scene.render(tone()[:FFT_SIZE], SR)
    assert scene._grid.shape == (300, 900)
