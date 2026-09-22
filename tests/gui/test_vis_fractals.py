"""The three fractal modes: one driver, three kernels.

``fractal`` (J Fractal) is the Julia set that shipped first; ``fractal_power``
(Tri Fractal) and ``fractal_trap`` (Blade Fractal) joined on 2026-09-21 and
share its orbit, camera, fade and palette. What these tests pin is the sharing
— that the siblings fade in and out with the music exactly as the Julia does —
and the one thing the Blade Fractal adds, a kick-driven swell whose release is
a time constant rather than a frame count.
"""

import numpy as np
import pytest

from src.gui.widgets.vis_canvas import (
    FAST_FRAME_MS,
    FFT_SIZE,
    FRACTAL_MODES,
    FRAME_MS,
    POPOUT_MODES,
    RENDER_MODES,
    VisRenderer,
)
from src.utils.config import _VALID_VIS_MODES, AppConfig, load_config, save_config

SR = 44100
SILENCE = np.zeros(FFT_SIZE, dtype=np.float32)


def noise(seed=0, gain=0.4):
    rng = np.random.default_rng(seed)
    return rng.normal(0, gain, FFT_SIZE).astype(np.float32)


def steady(gain=0.5):
    """A 1 kHz tone: music with no kick in it. Noise will not do for "no
    kick" — each block's bass energy wanders against the average, and the
    detector reads that as a beat."""
    t = np.arange(FFT_SIZE) / SR
    return (gain * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32)


def bass_hit(gain=0.9):
    """The tone plus a loud 80 Hz block: lands in the first two log bands,
    where the kick detector listens."""
    t = np.arange(FFT_SIZE) / SR
    return steady() + (gain * np.sin(2 * np.pi * 80.0 * t)).astype(np.float32)


def alpha(image):
    """The frame's alpha plane, 0..255 — the fractals fade by alpha."""
    w, h = image.width(), image.height()
    buf = image.constBits()
    return np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)[..., 3]


@pytest.fixture(params=FRACTAL_MODES)
def fractal(request, qapp):
    renderer = VisRenderer()
    renderer.set_mode(request.param)
    return renderer


class TestTheThreeShareOneDriver:
    def test_every_fractal_is_a_render_mode_and_a_popout_mode(self):
        for mode in FRACTAL_MODES:
            assert mode in RENDER_MODES
            assert mode in POPOUT_MODES
            assert mode in _VALID_VIS_MODES
            assert f"backdrop_{mode}" in _VALID_VIS_MODES

    def test_the_new_ids_round_trip_through_config(self):
        for mode in ("fractal_power", "backdrop_fractal_trap"):
            save_config(AppConfig(visualization_mode=mode))
            assert load_config().visualization_mode == mode

    def test_silence_after_a_mode_switch_draws_nothing(self, fractal):
        """The level follower starts at zero, so the first frames are fully
        transparent — the backdrop shows the plain playlist, not a frozen
        figure."""
        image = fractal.render(SILENCE, SR)
        assert (image.width(), image.height()) == (152, 64)
        assert alpha(image).max() == 0

    def test_music_lights_it_and_silence_fades_it_out(self, fractal):
        for _ in range(6):
            lit = alpha(fractal.render(noise(), SR))
        assert lit.max() > 0
        assert fractal._fract_level > 0.3
        # ~2 s of silence: the Julia's 0.94-per-frame release, shared by all.
        # The tail is asymptotic (0.94^75 ≈ 0.01), so "gone" is an alpha the
        # eye cannot see over the playlist grey, not a literal zero.
        for _ in range(int(2500 / FRAME_MS)):
            image = fractal.render(SILENCE, SR)
        assert fractal._fract_level < 0.03
        assert alpha(image).max() <= 8

    def test_the_siblings_fade_on_the_julias_own_envelope(self, qapp):
        """Same audio in, same ``_fract_level`` out: the fade is shared state,
        not three copies of one constant."""
        levels = []
        for mode in FRACTAL_MODES:
            renderer = VisRenderer()
            renderer.set_mode(mode)
            trace = []
            for i in range(30):
                renderer.render(noise(i) if i < 10 else SILENCE, SR)
                trace.append(renderer._fract_level)
            levels.append(trace)
        assert levels[0] == levels[1] == levels[2]

    def test_the_kernels_draw_different_pictures(self, qapp):
        """Three modes, three figures — not one Julia under three names."""
        frames = {}
        for mode in FRACTAL_MODES:
            renderer = VisRenderer()
            renderer.set_mode(mode)
            for i in range(8):
                image = renderer.render(noise(i), SR)
            frames[mode] = alpha(image).astype(int)
        assert np.abs(frames["fractal"] - frames["fractal_power"]).mean() > 5
        assert np.abs(frames["fractal"] - frames["fractal_trap"]).mean() > 5
        assert np.abs(frames["fractal_power"] - frames["fractal_trap"]).mean() > 5


class TestTheBladeFractalsSwell:
    def test_a_kick_fills_the_shape_and_it_thins_again(self, qapp):
        """Fullness is mostly the kick: the lit area grows on the hit and
        shrinks back between hits, at the same level."""
        renderer = VisRenderer()
        renderer.set_mode("fractal_trap")
        for _ in range(20):
            renderer.render(steady(), SR)
        assert renderer._trap_kick == 0.0
        resting = (alpha(renderer.render(steady(), SR)) > 40).mean()
        renderer.render(bass_hit(), SR)
        assert renderer._trap_kick > 0.5
        hit = (alpha(renderer.render(bass_hit(), SR)) > 40).mean()
        assert hit > resting * 1.3
        for _ in range(12):
            renderer.render(steady(), SR)
        after = (alpha(renderer.render(steady(), SR)) > 40).mean()
        assert after < hit
        assert renderer._trap_kick < 0.1

    def test_the_kick_release_is_a_time_constant(self, qapp):
        """0.75 a frame is ~100 ms to halfway at 33 ms and half that at 16.
        Fed the same second of audio at both rates, the follower must land
        in the same place (the per-frame-decay rule)."""
        settled = []
        for frame_ms in (FRAME_MS, FAST_FRAME_MS):
            renderer = VisRenderer()
            renderer.set_mode("fractal_trap")
            renderer.set_frame_interval(frame_ms)
            renderer._trap_kick = 1.0
            renderer._pulse = 0.0
            frames = int(round(330 / frame_ms))
            value = 1.0
            for _ in range(frames):
                value = max(renderer._pulse, value * renderer._trap_release)
            settled.append(value)
        assert settled[0] == pytest.approx(settled[1], rel=0.15)
        assert settled[0] < 0.1

    def test_the_julia_ignores_the_follower(self, qapp):
        """The J and Tri Fractals keep punching the zoom on the raw pulse, as
        shipped; only the Blade Fractal reads the smoothed kick."""
        renderer = VisRenderer()
        renderer.set_mode("fractal")
        renderer._trap_kick = 1.0
        renderer._pulse = 0.0
        renderer.render(SILENCE, SR)
        # The follower still advances (so a later switch starts fresh)...
        assert renderer._trap_kick < 1.0
        # ...but the Julia's brightness came from _pulse alone: nothing lit.
        assert alpha(renderer.image()).max() == 0
