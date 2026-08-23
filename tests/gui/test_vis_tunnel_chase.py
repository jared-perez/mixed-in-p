"""Tunnel Chase: the turn schedule, the path, the picture, and the wiring.

The wormhole's tests are the template, with one change of substance: its
"rings slide past" and "silence still travels" tests encode *level drives
speed*, and here speed is the tempo. The shape of those tests is ported; the
assertions are not.

Pixel counting is numpy over the whole frame, never ``pixelColor`` in a loop
sampling every other pixel — a star arm is one pixel wide and a sampled test
steps straight over it.
"""

import time

import numpy as np
import pytest
from PySide6.QtGui import QImage

from src.gui.widgets import vis_tunnel_chase as tc
from src.gui.widgets.beat_clock import DEFAULT_BPM
from src.gui.widgets.player_panel import _BACKDROP_VIS_MAP, PlayerPanel
from src.gui.widgets.vis_canvas import (
    FFT_SIZE,
    FRAME_MS,
    POPOUT_MODES,
    RENDER_MODES,
    TUNNEL_FRAME_MS,
    VisRenderer,
)
from src.gui.widgets.vis_tunnel_chase import (
    BACKDROP_CAP,
    DS,
    POPOUT_CAP,
    TUNNEL_R,
    UNITS_PER_BEAT,
    PathAhead,
    TunnelChaseScene,
    schedule_turns,
)
from src.utils.config import _VALID_VIS_MODES


# ── The schedule ───────────────────────────────────────────────────────────


def test_turns_land_on_the_bar_and_on_the_phrase():
    """The brief: beat 1 of every bar, plus beat 3 of every fourth bar."""
    turns = schedule_turns(0, 64, np.random.default_rng(1))
    beats = [beat for beat, _direction, _heading in turns]
    assert beats == [b for b in range(64) if b % 4 == 0 or b % 16 == 2]


def test_the_schedule_continues_across_calls():
    """It is generated ahead of the camera in chunks, not all at once."""
    rng = np.random.default_rng(1)
    first = schedule_turns(0, 32, rng)
    second = schedule_turns(32, 64, rng)
    assert [b for b, _d, _h in first + second] == [
        b for b in range(64) if b % 4 == 0 or b % 16 == 2
    ]


def test_no_turn_repeats_or_reverses_the_one_before_it():
    """Both read as a wobble rather than as a course change."""
    turns = schedule_turns(0, 256, np.random.default_rng(1))
    for (_b0, first, _h0), (_b1, second, _h1) in zip(turns, turns[1:]):
        delta = (second - first) % (2 * np.pi)
        assert min(delta, 2 * np.pi - delta) > 0.1  # not the same direction
        assert abs(delta - np.pi) > 0.1  # and not its reverse


def test_the_phrase_turn_is_the_gentler_one():
    """The extra swing inside a bar is a flourish, not another course change."""
    turns = schedule_turns(0, 256, np.random.default_rng(1))
    bar = [h for b, _d, h in turns if b % 4 == 0]
    phrase = [h for b, _d, h in turns if b % 16 == 2]
    assert max(phrase) < max(bar)
    assert np.mean(phrase) < np.mean(bar)


# ── The path ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def long_path():
    """Forty bars of the shipped seed — the path a listener actually flies."""
    path = PathAhead()
    path.extend_to(40 * 4 * UNITS_PER_BEAT)
    return path


def test_the_frames_stay_orthonormal(long_path):
    """A Bishop frame is rotation-minimising by construction; drift would roll the mesh."""
    tan = np.array(long_path.tan)
    normal = np.array(long_path.normal)
    binormal = np.array(long_path.binormal)
    for vectors in (tan, normal, binormal):
        assert np.abs(np.linalg.norm(vectors, axis=1) - 1.0).max() < 1e-9
    assert np.abs((tan * normal).sum(axis=1)).max() < 1e-9
    assert np.abs((tan * binormal).sum(axis=1)).max() < 1e-9
    assert np.abs((normal * binormal).sum(axis=1)).max() < 1e-9


def test_the_path_is_stepped_by_arc_length(long_path):
    steps = np.linalg.norm(np.diff(np.array(long_path.pos), axis=0), axis=1)
    assert np.abs(steps - DS).max() < 1e-9


def test_the_walls_never_fold_into_themselves(long_path):
    """Curvature comes from the bump sum, not from differences over the polyline."""
    assert long_path.min_radius() >= 2.0 * TUNNEL_R


def test_the_turns_are_a_lean_rather_than_an_elbow(long_path):
    """The first version turned too fast, and it read as a series of corners.

    The bump's integral is the heading change, so widening it lowers the peak
    curvature in proportion — the turn still happens, it just takes longer.
    Measured: 0.9 beats gave a sharpest turn of 2.27 R, 1.6 gives 3.4.
    """
    assert long_path.min_radius() >= 3.0 * TUNNEL_R


def test_a_straightaway_is_a_long_lazy_curve(long_path):
    """Mostly not straight — but not restlessly curving either.

    A **band**, not a ceiling, because this was tuned from both directions.
    Before any drift, 53% of the flight was straighter than 1/50 R and every
    turn was therefore a departure from nothing, which is what made them feel
    abrupt. The first drift amplitude took that to 3.3%, which overshot — the
    tunnel never settled. It sits around 10% now, and both neighbours are
    regressions from a judgement someone made by watching it.

    The band is half-to-double around the tuned figure, which is about as
    tight as this measure deserves: it is hypersensitive at this amplitude
    (1/50 R is roughly the amplitude itself) and it moves with how much path
    is sampled (the same setting reads 8.9% over these 40 bars and 10.1% over
    60). It still fails at both settings that were tried and rejected — no
    drift at all reads 27.8%, and the first attempt's 0.05 reads 3.3% — though
    note the lower bound clears that second one by only 0.3 of a point.
    """
    kappa = np.array(long_path.kappa[1:])
    assert 0.036 < float((kappa < 0.02).mean()) < 0.14
    # ...and the wander is gentle enough never to read as a turn of its own.
    assert np.median(kappa) < 1.0 / (5.0 * TUNNEL_R)


def test_the_curvature_is_continuous(long_path):
    """A bump whose leading half was never scheduled would show up as a step.

    The schedule is generated ahead of the camera in chunks, and a turn
    centred up to _TURN_WIDTH beats away already bends the path here — so a
    lookahead shorter than the bump's own reach would truncate it. Nothing in
    the shape of the path may jump.
    """
    steps = np.abs(np.diff(np.array(long_path.kappa[1:])))
    assert steps.max() < 0.05


def test_the_schedule_always_covers_the_frontier():
    """The invariant behind the test above, asserted rather than inferred."""
    path = PathAhead()
    for target in (10.0, 60.0, 200.0, 700.0):
        path.extend_to(target)
        frontier = path.s0 + (len(path.pos) - 1) * DS
        reach = frontier / UNITS_PER_BEAT + tc._TURN_WIDTH
        assert path._scheduled_to >= reach


def test_the_path_is_forgotten_behind_the_camera():
    path = PathAhead()
    path.extend_to(400.0)
    path.trim(380.0)
    assert path.s0 > 0
    # ...and what is left still answers for where the camera is.
    position, _n, _b = path.at(380.0)
    assert np.isfinite(position).all()
    assert len(path.turns) < 200  # the schedule is trimmed with it


# ── The scene ──────────────────────────────────────────────────────────────


@pytest.fixture
def scene(qapp):
    """A scene at backdrop size. qapp because painting a QImage needs QGuiApplication."""
    scene = TunnelChaseScene()
    scene.set_target_size(1216, 512)
    return scene


def _pixels(image):
    """``(h, w, 4)`` BGRA as numpy — the whole frame, not a sample of it."""
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    raw = np.frombuffer(image.constBits(), dtype=np.uint8)
    return raw.reshape(image.height(), image.bytesPerLine() // 4, 4)[:, : image.width()]


def _fly(scene, from_beat=0.0, to_beat=8.0, fps=60, bpm=128.0, pulse_at=None):
    """Feed the scene a run of frames and return the last image."""
    step = bpm / 60.0 / fps
    beat = from_beat
    image = None
    while beat <= to_beat:
        pulse = 1.0 if (pulse_at is not None and abs(beat - pulse_at) < step) else 0.0
        image = scene.render(beat, 0.6, pulse)
        beat += step
    return image


def test_speed_is_the_tempo_not_the_level(scene):
    """The wormhole's level-driven travel is exactly what this replaces."""
    scene.render(0.0, 0.0, 0.0)
    scene.render(4.0, 0.0, 0.0)
    quiet = scene._cam_s
    scene.reset()
    scene.render(0.0, 1.0, 0.0)
    scene.render(4.0, 1.0, 0.0)
    assert scene._cam_s == quiet == 4.0 * UNITS_PER_BEAT


def test_rings_slide_past_rather_than_riding_along(scene):
    """Rings sit at fixed world arc-lengths; anchored to the camera they would only bend."""
    scene.render(0.1, 0.5, 0.0)  # camera at 0.25 units, first ring at 1.0
    first_ring = scene._ring_s[0]
    camera = scene._cam_s
    scene.render(0.2, 0.5, 0.0)
    assert scene._cam_s > camera  # the camera advanced...
    assert scene._ring_s[0] == first_ring  # ...and the ring stayed put


def test_a_ring_reaching_the_camera_has_already_faded_to_nothing(scene):
    """The bright chord across the lens, and why it is a fade and not a clip.

    A ring passing beside the camera on a bend projects a correct but
    startling chord right across the frame. Raising the near plane to hide it
    makes rings pop out of existence instead; fading them over the last 0.9
    units means that by the time any vertex is behind the plane the ring is
    already drawing at zero alpha.
    """
    dissolving = 0
    for beat in np.arange(0.0, 24.0, 0.05):
        scene.render(float(beat), 0.6, 0.0)
        geometry = scene._geometry
        for k in range(len(geometry["ring_fade"])):
            if not geometry["ahead"][k].all():
                dissolving += 1
                # The very number the painter takes its alpha from.
                assert geometry["ring_fade"][k] == 0.0
    assert dissolving > 20  # rings really did pass the camera in that run


def test_spokes_are_clipped_at_the_near_plane_not_dropped(scene):
    """Dropping them leaves a cone floating mid-frame instead of a tube around you.

    A spoke whose near end is beside or behind the camera still has to be drawn
    from the frame edge inward — those lines are what put the viewer inside.
    """
    clipped_frames = 0
    for beat in np.arange(0.0, 24.0, 0.05):
        scene.render(float(beat), 0.6, 0.0)
        geometry = scene._geometry
        if geometry["nearest"][0] < tc._NEAR:
            clipped_frames += 1
            # Every spoke of the ring being passed survives, moved up to the
            # plane rather than discarded.
            assert geometry["spoke_ok"][0].all()
    assert clipped_frames > 10


def test_the_viewer_stays_inside_the_tube_as_a_ring_passes(scene):
    """The cone regression, measured where it actually shows.

    Only the frames in which the nearest ring has come inside the near plane
    can tell the two treatments apart, and only the *mesh* can — stars cover
    the whole frame, so an alpha test passes against a cone. Measured: with
    the spokes clipped at the plane the mesh reaches at least three of the four
    edges in every such frame; with them dropped instead it reaches **none**,
    which is the tube collapsing to a cone floating mid-frame.
    """
    checked = 0
    for beat in np.arange(4.5, 8.0, 128.0 / 60.0 / 60.0):
        image = scene.render(float(beat), 0.6, 0.0)
        if scene._geometry["nearest"][0] >= tc._NEAR:
            continue
        checked += 1
        raw = _pixels(image)
        blue, green, red, alpha = (raw[..., i].astype(int) for i in range(4))
        mesh = (alpha > 0) & (red > 150) & (green > 150) & (blue < 80)
        edges = [mesh[0].any(), mesh[-1].any(), mesh[:, 0].any(), mesh[:, -1].any()]
        assert sum(bool(e) for e in edges) >= 3
    assert checked > 10  # the run really did pass some rings


def test_it_draws_a_tunnel_stars_and_planets(scene):
    """Wireframe down the middle, pale sky behind it, a shaded disc among it."""
    image = _fly(scene, 0.0, 4.0, pulse_at=4.0)
    raw = _pixels(image)
    blue, green, red, alpha = (raw[..., i].astype(int) for i in range(4))
    lit = alpha > 0
    # The wireframe is the theme colour: saturated, almost no blue.
    mesh = lit & (red > 150) & (green > 150) & (blue < 80)
    # Stars and planets are washed toward white, so they carry blue.
    pale = lit & (blue > 120)
    cores = lit & (red > 230) & (green > 230) & (blue > 230)
    assert mesh.sum() > 500
    assert pale.sum() > 100
    assert cores.sum() > 20  # the white centres of the near four-point stars


def test_the_sky_is_paler_than_the_wireframe(scene):
    """The brief: stars and planets pale versions of the colour, plus some grey."""
    _fly(scene, 0.0, 4.0, pulse_at=4.0)
    palette = scene._palette()
    mesh = scene._color
    for colour in palette:
        assert colour.blue() > mesh.blue()


# ── Stars respond to the kick ──────────────────────────────────────────────


def _brightest_star(image):
    raw = _pixels(image)
    blue, red, alpha = raw[..., 0].astype(int), raw[..., 2].astype(int), raw[..., 3].astype(int)
    sky = (alpha > 0) & (blue > 120) & (red > 120)
    return int(alpha[sky].max()) if sky.any() else 0


def test_stars_are_lit_by_the_kick(scene):
    _fly(scene, 0.0, 4.0)  # settle with no kicks at all
    quiet = _brightest_star(scene.image())
    scene.render(4.1, 0.3, 1.0)
    assert _brightest_star(scene.image()) > 2 * quiet


def test_the_kick_glow_fades_rather_than_snapping_back(scene):
    scene.render(1.0, 0.3, 1.0)
    assert scene._star_glow == 1.0
    glows = []
    beat = 1.0
    for _ in range(6):
        beat += 0.05
        scene.render(beat, 0.3, 0.0)
        glows.append(scene._star_glow)
    assert glows == sorted(glows, reverse=True)
    assert 0.0 < glows[-1] < 1.0


def test_the_glow_release_is_the_same_length_of_time_at_both_frame_rates(qapp):
    """0.82 a frame is half a second at 33 ms and a quarter at 16 — a different visual."""
    half_second = []
    for frame_ms in (33.0, 1000.0 / 60.0):
        scene = TunnelChaseScene()
        scene.set_frame_interval(frame_ms)
        scene.render(0.0, 0.3, 1.0)
        beat, elapsed = 0.0, 0.0
        while elapsed < 0.5:
            beat += 128.0 / 60.0 * frame_ms / 1000.0
            elapsed += frame_ms / 1000.0
            scene.render(beat, 0.3, 0.0)
        half_second.append(scene._star_glow)
    assert half_second[0] == pytest.approx(half_second[1], abs=0.02)


def test_stars_never_go_out_entirely(scene):
    """The floor keeps a starfield there for a track with no kick in it."""
    scene.render(0.0, 0.3, 1.0)
    _fly(scene, 0.05, 20.0)
    assert scene._star_glow < 0.01
    assert _brightest_star(scene.image()) > 0


# ── The image ──────────────────────────────────────────────────────────────


def test_the_image_follows_the_host_aspect(scene):
    scene.set_target_size(1000, 500)
    assert (scene.image().width(), scene.image().height()) == (1000, 500)


def test_a_retina_popout_is_capped_and_left_to_the_host_to_upscale(qapp):
    """1400x800 logical at 2x: 1260x720, not 2800x1600 (~10 ms a frame)."""
    scene = TunnelChaseScene()
    scene.set_target_size(2800, 1600, popout=True)
    assert (scene.image().width(), scene.image().height()) == (1260, 720)
    assert scene.image().height() <= POPOUT_CAP[1]


def test_the_backdrop_gets_the_smaller_budget(qapp):
    """The playlist repaint behind it costs ~11 ms; the frame must not add to that."""
    scene = TunnelChaseScene()
    scene.set_target_size(2800, 1600)
    assert scene.image().height() <= BACKDROP_CAP[1]
    assert scene.image().width() <= BACKDROP_CAP[0]


def test_the_cap_never_distorts_the_aspect(qapp):
    """A stretched wireframe draws ellipses where the rings should be."""
    scene = TunnelChaseScene()
    for width, height in ((3000, 600), (2800, 1600), (600, 1200)):
        scene.set_target_size(width, height, popout=True)
        image = scene.image()
        assert image.width() / image.height() == pytest.approx(width / height, rel=0.01)


def test_a_host_smaller_than_the_cap_renders_at_its_own_size(qapp):
    scene = TunnelChaseScene()
    scene.set_target_size(400, 200)
    assert (scene.image().width(), scene.image().height()) == (400, 200)


def test_target_size_ignores_an_unshown_host(scene):
    before = scene.image()
    scene.set_target_size(0, 0)
    scene.set_target_size(-4, 300)
    assert scene.image() is before


def test_target_size_does_not_reallocate_when_unchanged(scene):
    """This runs before every frame."""
    first = scene.image()
    scene.set_target_size(1216, 512)
    assert scene.image() is first


def test_a_frame_stays_cheap(scene):
    """A loose guard against an accidental O(pixels) rewrite.

    It measures ~3.4 ms at this size against a 16 ms budget; the bound is
    generous so it cannot flake under a full-suite load. If it flakes anyway,
    delete it rather than widen it — the real cost lives in the plan.
    """
    _fly(scene, 0.0, 2.0)
    times = []
    beat = 2.0
    for _ in range(40):
        beat += 128.0 / 60.0 / 60.0
        start = time.perf_counter()
        scene.render(beat, 0.6, 0.0)
        times.append(time.perf_counter() - start)
    assert float(np.median(times)) * 1000 < 20.0


def test_reset_returns_to_the_start_of_a_fresh_path(scene):
    _fly(scene, 0.0, 8.0, pulse_at=4.0)
    scene.reset()
    assert scene._cam_s == 0.0
    assert scene._star_glow == 0.0
    assert scene._path.s0 == 0.0
    assert _pixels(scene.image())[..., 3].sum() == 0


# ── VisRenderer integration ────────────────────────────────────────────────


def _noise(rng):
    return (rng.standard_normal(FFT_SIZE) * 0.2).astype(np.float32)


def test_the_renderer_returns_the_scenes_own_image(qapp):
    renderer = VisRenderer()
    renderer.set_mode("tunnel_chase")
    renderer.set_target_size(1000, 500)
    image = renderer.render(_noise(np.random.default_rng(0)), 44100)
    assert (image.width(), image.height()) == (1000, 500)
    assert renderer.image() is image


def test_switching_away_leaves_the_other_modes_at_their_own_size(qapp):
    """The scene's image must never land in VisRenderer._image.

    The scope and spectrum renderers paint into that at 152x64; a 1216-wide one
    left there would have them drawing into a corner of it, and every host
    would happily stretch the result.
    """
    renderer = VisRenderer()
    renderer.set_mode("tunnel_chase")
    renderer.set_target_size(1216, 512)
    renderer.render(_noise(np.random.default_rng(0)), 44100)
    renderer.set_mode("spectrum")
    image = renderer.render(_noise(np.random.default_rng(1)), 44100)
    assert (image.width(), image.height()) == (152, 64)


def test_the_frame_rate_and_the_smoothing_are_per_mode(qapp):
    """60 fps and interpolation for this one; 30 and chunky pixels for the rest."""
    renderer = VisRenderer()
    renderer.set_mode("tunnel_chase")
    assert renderer.frame_ms() == TUNNEL_FRAME_MS
    assert renderer.smooth_upscale() is True
    for mode in ("spectrum", "fire", "fractal", "wormhole", "oscilloscope"):
        renderer.set_mode(mode)
        assert renderer.frame_ms() == FRAME_MS
        assert renderer.smooth_upscale() is False


def test_the_bass_average_keeps_its_time_constant_at_either_rate(qapp):
    """0.97 a frame is 1.1 s at 33 ms and half that at 16 — a different pulse."""
    settled = []
    for frame_ms in (FRAME_MS, TUNNEL_FRAME_MS):
        renderer = VisRenderer()
        renderer.set_frame_interval(frame_ms)
        renderer.set_mode("tunnel_chase")
        rng = np.random.default_rng(0)
        elapsed = 0.0
        while elapsed < 1.0:  # one second of the same audio, either way
            renderer.render(_noise(rng), 44100)
            elapsed += frame_ms / 1000.0
        settled.append(renderer._bass_att)
    assert settled[0] == pytest.approx(settled[1], rel=0.15)


def test_the_kick_flux_is_only_computed_where_it_is_used(qapp):
    """A log1p over 1025 bins is cheap, and still a tax on five modes."""
    renderer = VisRenderer()
    renderer.set_mode("spectrum")
    for _ in range(4):
        renderer.render(_noise(np.random.default_rng(0)), 44100)
    assert renderer._prev_log is None
    assert renderer._kick_flux == 0.0
    renderer.set_mode("tunnel_chase")
    for _ in range(4):
        renderer.render(_noise(np.random.default_rng(0)), 44100)
    assert renderer._prev_log is not None


def test_a_tag_reaches_the_beat_clock_and_no_tag_falls_back(qapp):
    renderer = VisRenderer()
    renderer.set_mode("tunnel_chase")
    renderer.set_track_tempo(135.0)
    assert renderer.beat_state()["tempo_bpm"] == pytest.approx(135.0)
    renderer.set_track_tempo(None)
    assert renderer.beat_state()["tempo_bpm"] == pytest.approx(DEFAULT_BPM)


def test_beat_state_is_only_offered_by_the_mode_that_has_one(qapp):
    renderer = VisRenderer()
    renderer.set_mode("wormhole")
    assert renderer.beat_state() is None


def test_a_seek_drops_the_evidence_and_keeps_the_flight(qapp):
    renderer = VisRenderer()
    renderer.set_mode("tunnel_chase")
    renderer.set_track_tempo(128.0)
    rng = np.random.default_rng(0)
    for _ in range(30):
        renderer.render(_noise(rng), 44100)
    phase = renderer.beat_state()["phase"]
    renderer.reset_beat_clock()
    assert renderer.beat_state()["phase"] == phase
    assert renderer.beat_state()["locked"] is False


def test_mode_is_allow_listed_and_offered_by_both_hosts():
    assert "tunnel_chase" in RENDER_MODES
    assert "tunnel_chase" in POPOUT_MODES
    assert "tunnel_chase" in _VALID_VIS_MODES
    assert "backdrop_tunnel_chase" in _VALID_VIS_MODES
    assert _BACKDROP_VIS_MAP["backdrop_tunnel_chase"] == "tunnel_chase"


# ── PlayerPanel wiring ─────────────────────────────────────────────────────


@pytest.fixture
def player(qtbot):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    return panel


def _track(tmp_path, name="a.wav", bpm="128"):
    """A real (very short) file, so the Player's decode path is the fast one."""
    soundfile = pytest.importorskip("soundfile")
    path = tmp_path / name
    soundfile.write(str(path), np.zeros(4410, dtype=np.float32), 44100)
    return {"file_path": str(path), "display_name": name, "bpm": bpm}


def test_playing_a_track_pushes_its_tag_to_the_backdrop(player, tmp_path):
    player._select_vis_mode("backdrop_tunnel_chase")
    player.add_tracks([_track(tmp_path)])
    player._play_track(0)
    assert player._backdrop_renderer.beat_state()["tempo_bpm"] == pytest.approx(128.0)


def test_a_popout_opened_mid_track_is_given_the_tempo_too(player, tmp_path):
    """The wormhole had no per-track state at all, so this plumbing is new."""
    player.add_tracks([_track(tmp_path, bpm="135")])
    player._play_track(0)
    player._select_vis_mode("tunnel_chase")
    canvas = player._vis_window._canvas
    assert canvas._renderer.beat_state()["tempo_bpm"] == pytest.approx(135.0)


def test_an_untagged_track_leaves_the_clock_to_work_it_out(player, tmp_path):
    """entry.bpm is a tag string, and an empty one is not a float."""
    player._select_vis_mode("backdrop_tunnel_chase")
    player.add_tracks([_track(tmp_path, bpm="")])
    player._play_track(0)
    assert player._backdrop_renderer.beat_state()["tempo_bpm"] == pytest.approx(
        DEFAULT_BPM
    )


def test_a_seek_reaches_the_backdrops_clock(player, tmp_path, qtbot):
    player._select_vis_mode("backdrop_tunnel_chase")
    player.add_tracks([_track(tmp_path)])
    player._play_track(0)
    player._backdrop_renderer._clock._locked_bin = 3  # pretend it locked
    player._engine.seeked.emit()
    assert player._backdrop_renderer.beat_state()["locked"] is False


def test_the_popout_timer_follows_the_modes_frame_rate(player, qtbot):
    player._select_vis_mode("wormhole")
    assert player._vis_window._timer.interval() == FRAME_MS
    player._select_vis_mode("tunnel_chase")
    assert player._vis_window._timer.interval() == TUNNEL_FRAME_MS
    player._select_vis_mode("fractal")
    assert player._vis_window._timer.interval() == FRAME_MS


def test_the_backdrop_stays_at_thirty_whatever_the_mode(player):
    """Its cost is the host: repainting the rows behind the frame is ~11 ms."""
    player._select_vis_mode("backdrop_tunnel_chase")
    assert player._vis_tick_timer.interval() == FRAME_MS
    assert player._vis_decay_frames() == 2000 // FRAME_MS


def test_both_rows_are_in_the_visuals_menu(player):
    labels = [player._vis_actions[m].text() for m in ("backdrop_tunnel_chase", "tunnel_chase")]
    assert all(labels)
    modes = list(player._vis_actions)
    # Each sits beside the wormhole it is a sibling of, near the head of its
    # group — the menu leads with the richest visuals in each half.
    assert modes.index("backdrop_tunnel_chase") == modes.index("backdrop_wormhole") + 1
    assert modes.index("tunnel_chase") == modes.index("wormhole") + 1
