"""Waveform colour modes: the canvases' cached body, the zoom scrubber's colour,
the Settings controls, and the Player feeding colours in.

Paint is checked by sampling ``grab()``: this is custom painting, not QSS, so
it survives the suite's missing stylesheet, and an array assertion would pass
against a paint bug.
"""

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from src.gui.widgets import player_panel as player_panel_mod
from src.gui.widgets.player_panel import PlayerPanel
from src.gui.widgets.settings_panel import SettingsPanel
from src.gui.widgets.waveform_canvas import WaveformCanvas, ZoomedWaveformCanvas
from src.utils.config import WAVEFORM_COLOR_MODES, AppConfig, load_config

W, H = 200, 80
DURATION_MS = 10_000
N = 100
WAVE = "#00ff00"


def colour_at(widget, x, y) -> QColor:
    return QColor(widget.grab().toImage().pixel(x, y))


def halves(n=N):
    """Left half red, right half blue."""
    colors = np.zeros((n, 3), np.uint8)
    colors[: n // 2] = (255, 0, 0)
    colors[n // 2:] = (0, 0, 255)
    return colors


@pytest.fixture
def canvas(qtbot):
    c = WaveformCanvas()
    qtbot.addWidget(c)
    c.set_waveform_color(WAVE)
    c.setRange(0, DURATION_MS)
    c.set_waveform(np.full(N, -0.5, np.float32), np.full(N, 0.5, np.float32))
    c.setFixedSize(W, H)
    return c


class TestOverviewCanvas:
    def test_column_colours_are_painted_where_their_columns_are(self, canvas):
        canvas.set_column_colors(halves())
        assert colour_at(canvas, 40, H // 2 - 10) == QColor(255, 0, 0)
        assert colour_at(canvas, 160, H // 2 - 10) == QColor(0, 0, 255)

    def test_none_draws_the_waveform_colour(self, canvas):
        canvas.set_column_colors(halves())
        canvas.set_column_colors(None)
        assert colour_at(canvas, 40, H // 2 - 10) == QColor(WAVE)

    def test_colours_for_another_length_are_ignored(self, canvas):
        """A stale array from the previous track must not index this one."""
        canvas.set_column_colors(halves(N + 7))
        assert colour_at(canvas, 40, H // 2 - 10) == QColor(WAVE)

    @pytest.mark.parametrize(
        "change",
        [
            lambda c: c.set_waveform_color("#ff00ff"),
            lambda c: c.set_column_colors(halves()),
            lambda c: c.set_half(True),
            lambda c: c.setFixedSize(W, H + 40),
            lambda c: c.set_waveform(np.full(N, -0.1, np.float32), np.full(N, 0.1, np.float32)),
        ],
        ids=["colour", "column colours", "half", "resize", "new waveform"],
    )
    def test_every_input_invalidates_the_cached_body(self, canvas, change):
        before = canvas.grab().toImage()
        change(canvas)
        assert canvas.grab().toImage() != before

    def test_position_ticks_reuse_the_cache(self, canvas):
        canvas.grab()
        cached = canvas._cache
        canvas.setSliderValue(5000)
        canvas.grab()
        assert canvas._cache is cached

    def test_clear_drops_the_colours(self, canvas):
        canvas.set_column_colors(halves())
        canvas.clear()
        assert canvas._column_colors is None
        assert canvas._cache is None


class TestZoomCanvas:
    @pytest.fixture
    def zoom(self, qtbot):
        z = ZoomedWaveformCanvas()
        qtbot.addWidget(z)
        bps = 1000.0
        n = int(DURATION_MS / 1000 * bps)
        z.set_waveform(np.full(n, -0.5, np.float32), np.full(n, 0.5, np.float32), bps)
        z.setRange(0, DURATION_MS)
        z.setFixedSize(W, H)
        return z

    def test_follows_the_waveform_colour_in_solid(self, zoom):
        zoom.set_waveform_color(WAVE)
        zoom.setPosition(2000)
        assert colour_at(zoom, 30, H // 2 - 10) == QColor(WAVE)

    def test_samples_the_overviews_colours_by_time(self, zoom):
        """The window around 2 s sits in the red first half, around 8 s in the
        blue second half; across the 5 s boundary it shows both."""
        zoom.set_column_colors(halves())
        zoom.setPosition(2000)
        assert colour_at(zoom, 30, H // 2 - 10) == QColor(255, 0, 0)
        zoom.setPosition(8000)
        assert colour_at(zoom, 30, H // 2 - 10) == QColor(0, 0, 255)
        zoom.setPosition(5000)
        assert colour_at(zoom, 20, H // 2 - 10) == QColor(255, 0, 0)
        assert colour_at(zoom, W - 20, H // 2 - 10) == QColor(0, 0, 255)


def _settings(qtbot, **fields):
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel.load_config(AppConfig(**fields))
    return panel


class TestSettings:
    def test_defaults(self):
        cfg = AppConfig()
        assert cfg.waveform_color_mode == "solid"
        assert cfg.waveform_color_absolute is False

    @pytest.mark.parametrize("absolute", [False, True])
    @pytest.mark.parametrize("mode", WAVEFORM_COLOR_MODES)
    def test_round_trips_through_the_panel(self, qtbot, mode, absolute):
        """get_config rebuilds the whole AppConfig from the widgets: a field it
        forgets resets on every other settings change."""
        panel = _settings(qtbot, waveform_color_mode=mode, waveform_color_absolute=absolute)
        cfg = panel.get_config(AppConfig())
        assert (cfg.waveform_color_mode, cfg.waveform_color_absolute) == (mode, absolute)

    def test_tone_is_stored_as_centroid(self, qtbot):
        panel = _settings(qtbot)
        index = panel._waveform_mode_combo.findText(panel.tr("Tone"))
        panel._waveform_mode_combo.setCurrentIndex(index)
        assert panel.get_config().waveform_color_mode == "centroid"

    def test_round_trips_through_disk(self, qtbot):
        from src.utils.config import save_config

        save_config(AppConfig(waveform_color_mode="bands", waveform_color_absolute=True))
        cfg = load_config()
        assert (cfg.waveform_color_mode, cfg.waveform_color_absolute) == ("bands", True)

    def test_an_unknown_stored_mode_loads_as_solid(self):
        from src.utils.app_dirs import get_app_data_dir
        import json

        path = get_app_data_dir() / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"waveform_color_mode": "tone"}))
        assert load_config().waveform_color_mode == "solid"

    @pytest.mark.parametrize(
        "mode, picker, scaled",
        [
            ("solid", True, False),
            ("loudness", True, True),
            ("bands", False, True),
            ("centroid", False, True),
        ],
    )
    def test_controls_follow_the_mode(self, qtbot, mode, picker, scaled):
        panel = _settings(qtbot, waveform_color_mode=mode)
        assert panel._wave_custom_btn.isEnabled() is picker
        assert all(b.isEnabled() is picker for b in panel._wave_swatches.values())
        assert panel._waveform_picker_hint.isHidden() is picker
        assert panel._waveform_absolute_switch.isEnabled() is scaled

    def test_changing_the_mode_emits(self, qtbot):
        panel = _settings(qtbot)
        with qtbot.waitSignal(panel.settings_changed, timeout=1000):
            panel._waveform_mode_combo.setCurrentIndex(
                panel._waveform_mode_combo.findData("bands")
            )
        assert not panel._wave_custom_btn.isEnabled()

    def test_a_real_click_on_the_switch_emits_and_updates_its_tooltip(self, qtbot):
        panel = _settings(qtbot, waveform_color_mode="bands")
        panel.show()
        sw = panel._waveform_absolute_switch
        qtbot.waitExposed(sw)
        before = sw.toolTip()
        with qtbot.waitSignal(panel.settings_changed, timeout=1000):
            qtbot.mouseClick(sw, Qt.MouseButton.LeftButton, pos=sw.rect().center())
        assert panel.get_config().waveform_color_absolute is True
        assert sw.toolTip() != before

    def test_load_updates_the_tooltip_with_signals_blocked(self, qtbot):
        a = _settings(qtbot, waveform_color_absolute=False)._waveform_absolute_switch.toolTip()
        b = _settings(qtbot, waveform_color_absolute=True)._waveform_absolute_switch.toolTip()
        assert a != b


class TestPlayer:
    PATH = "/music/track.wav"

    @pytest.fixture
    def player(self, qtbot, monkeypatch):
        panel = PlayerPanel()
        qtbot.addWidget(panel)
        t = np.arange(44100 * 3, dtype=np.float32) / 44100
        mono = (0.5 * np.sin(2 * np.pi * 60 * t)).astype(np.float32)
        mono[44100:] = (0.5 * np.sin(2 * np.pi * 9000 * t[44100:])).astype(np.float32)
        panel._cache_put(self.PATH, np.stack([mono, mono], axis=1), 44100)
        panel._playing_path = self.PATH
        panel.spectral_calls = 0
        real = player_panel_mod.spectral_columns

        def counting(*args, **kwargs):
            panel.spectral_calls += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(player_panel_mod, "spectral_columns", counting)
        panel._build_waveform_for_current()
        return panel

    def colors(self, player):
        return player._slice.waveform_widget()._column_colors

    def test_solid_and_loudness_never_run_the_fft(self, player):
        player.set_waveform_color_mode("solid", False)
        assert self.colors(player) is None
        player.set_waveform_color_mode("loudness", False)
        assert self.colors(player) is not None
        assert player.spectral_calls == 0

    def test_a_frequency_mode_analyses_once_per_track(self, player):
        player.set_waveform_color_mode("bands", False)
        player.set_waveform_color_mode("centroid", False)
        player.set_waveform_color_mode("centroid", True)
        player.set_waveform_color("#123456")
        assert player.spectral_calls == 1

    def test_bands_colour_the_bass_red_and_the_highs_green(self, player):
        player.set_waveform_color_mode("bands", False)
        colors = self.colors(player)
        n = len(colors)
        bass, highs = colors[n // 6], colors[5 * n // 6]
        assert bass[0] > bass[1] and bass[0] > bass[2]
        assert highs[1] > highs[0] and highs[1] > highs[2]

    def test_both_canvases_get_the_colours(self, player):
        player.set_waveform_color_mode("centroid", False)
        assert player._slice._zoom_waveform._column_colors is self.colors(player)

    def test_a_new_track_drops_the_old_colours(self, player):
        player.set_waveform_color_mode("bands", False)
        player._playing_path = "/music/other.wav"
        player._refresh_waveform_colors()
        assert self.colors(player) is None
