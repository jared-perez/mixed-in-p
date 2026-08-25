"""The analog scope — the popout's face of the ``oscilloscope`` mode.

The mode now draws two different pictures depending on which host asked, so
most of what matters here is the *split*: the backdrop's renderer must keep the
152x64 retro grid it has always drawn, and only a renderer that has been told
``popout=True`` gets the phosphor scene.

Assertions are on the scene's buffer and on image *sizes*, never on pixel
colours at coordinates. The suite runs styleless and offscreen, and both
pixel-diff traps in CLAUDE.md (device pixel ratio, the missing stylesheet)
apply; the look itself is judged by rendering stills with
``scripts/vis_sheet.py --mode oscilloscope --popout``, as it is for every
visual.
"""

import numpy as np
import pytest

from src.gui.widgets.player_panel import _BACKDROP_VIS_MAP
from src.gui.widgets.vis_analog_scope import (
    _BACKDROP_CAP_PX,
    _POPOUT_CAP_PX,
    _WINDOW,
    AnalogScopeScene,
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


def test_the_backdrop_still_gets_the_retro_grid(qapp):
    """A renderer nobody called popout on draws the 152x64 trace it always did."""
    renderer = VisRenderer()
    renderer.set_mode("oscilloscope")
    renderer.set_target_size(2400, 1200)  # the backdrop's call: popout defaults False
    image = renderer.render(tone()[:FFT_SIZE], SR)
    assert (image.width(), image.height()) == (152, 64)
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


def test_the_smoothing_follows_the_host_and_the_rate_follows_the_mode(qapp):
    """Two answers with different shapes, and the asymmetry is deliberate.

    The upscale is a question about the picture, so it splits per host: the
    popout's glow field would staircase once the area cap bites, the backdrop's
    grid is meant to be chunky. The frame rate is asked only of the mode
    because only the popout ever reads it — the backdrop's tick timer stays at
    FRAME_MS whatever is playing, since its cost is repainting the rows.
    """
    backdrop = VisRenderer()
    backdrop.set_mode("oscilloscope")
    backdrop.set_target_size(1216, 512)
    assert backdrop.smooth_upscale() is False

    popout = VisRenderer()
    popout.set_mode("oscilloscope")
    popout.set_target_size(1216, 512, popout=True)
    assert popout.smooth_upscale() is True

    assert backdrop.frame_ms() == popout.frame_ms() == FAST_FRAME_MS


def test_nothing_about_the_menu_or_the_config_moved():
    """Same mode id in every list — no migration, no orphaned translations."""
    assert "oscilloscope" in RENDER_MODES
    assert "oscilloscope" in POPOUT_MODES
    assert "oscilloscope" in _VALID_VIS_MODES
    assert "backdrop_scope" in _VALID_VIS_MODES
    assert _BACKDROP_VIS_MAP["backdrop_scope"] == "oscilloscope"


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
