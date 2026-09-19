"""Settings' half/full waveform switch and what it does to the Player's views.

Half view draws only the top of the Waveform and Zoomed Wave canvases, rising
from a baseline at the bottom edge, in half the height — the point is to give
that room back to the playlist. The paint tests sample ``grab()`` rather than
asserting on state, because the state is not the bug a user would see.
"""

import json

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from src.gui.styles.theme import Theme
from src.gui.widgets.player_engine import PlayerEngine
from src.gui.widgets.settings_panel import SettingsPanel
from src.gui.widgets.slice_section import SliceSection
from src.gui.widgets.toggle_switch import ToggleSwitch
from src.gui.widgets.waveform_canvas import WaveformCanvas, ZoomedWaveformCanvas
from src.utils.config import AppConfig, load_config

W, H = 200, 80
DURATION_MS = 10_000
WAVE = "#00ff00"


def _is_wave(img, x, y) -> bool:
    return QColor(img.pixel(x, y)) == QColor(WAVE)


@pytest.fixture
def canvas(qtbot):
    c = WaveformCanvas()
    qtbot.addWidget(c)
    c.set_waveform_color(WAVE)
    c.setRange(0, DURATION_MS)
    # A steady ±0.5 wave: every column reaches halfway to each edge.
    c.set_waveform(np.full(64, -0.5, np.float32), np.full(64, 0.5, np.float32))
    c.setFixedSize(W, H)
    return c


class TestCanvasHeight:
    def test_half_halves_both_minimum_heights_and_full_restores_them(self, qtbot):
        wave, zoom = WaveformCanvas(), ZoomedWaveformCanvas()
        qtbot.addWidget(wave)
        qtbot.addWidget(zoom)
        full = (wave.minimumHeight(), zoom.minimumHeight())
        for c in (wave, zoom):
            c.set_half(True)
        assert (wave.minimumHeight(), zoom.minimumHeight()) == (full[0] // 2, full[1] // 2)
        for c in (wave, zoom):
            c.set_half(False)
        assert (wave.minimumHeight(), zoom.minimumHeight()) == full

    def test_the_zoomed_views_budget_shrinks_with_it(self, qtbot, tmp_path):
        """The Player sizes its playlist from first_screen_height, so this is
        what actually hands the room back."""
        sec = SliceSection(PlayerEngine())
        qtbot.addWidget(sec)
        track = tmp_path / "t.wav"
        track.write_bytes(b"x")
        sec.set_track(str(track), DURATION_MS)
        sec._zoom_btn.setChecked(True)
        full = sec.first_screen_height()
        sec.set_waveform_half(True)
        assert sec.first_screen_height() == full - sec._zoom_waveform.minimumHeight()


class TestCanvasPaint:
    def test_full_view_is_mirrored_about_the_centre(self, canvas):
        img = canvas.grab().toImage()
        assert _is_wave(img, 100, H // 2 - 10)
        assert _is_wave(img, 100, H // 2 + 10)
        assert not _is_wave(img, 100, H - 5), "nothing below the lower half-wave"

    def test_half_view_rises_from_the_bottom_only(self, canvas):
        canvas.set_half(True)
        img = canvas.grab().toImage()
        assert _is_wave(img, 100, H - 5)
        assert _is_wave(img, 100, H // 2 + 5)
        assert not _is_wave(img, 100, 10), "a 0.5 peak stops halfway up"

    def test_half_view_takes_the_louder_side(self, canvas):
        """A transient that swings negative must not vanish from half view."""
        canvas.set_waveform(np.full(64, -0.9, np.float32), np.full(64, 0.1, np.float32))
        canvas.set_half(True)
        img = canvas.grab().toImage()
        assert _is_wave(img, 100, 15)

    def test_zoomed_half_view_rises_from_the_bottom_only(self, qtbot):
        z = ZoomedWaveformCanvas()
        qtbot.addWidget(z)
        z.setRange(0, DURATION_MS)
        z.setPosition(DURATION_MS // 2)
        z.set_waveform(np.full(1000, -0.5, np.float32), np.full(1000, 0.5, np.float32), 100.0)
        z.set_half(True)
        z.setFixedSize(W, H)
        img = z.grab().toImage()
        yellow = QColor(Theme.NEON_YELLOW)
        assert QColor(img.pixel(30, H - 5)) == yellow
        assert QColor(img.pixel(30, 10)) != yellow


class TestSetting:
    def test_defaults_to_half(self):
        assert AppConfig().player_waveform_half is True

    def test_an_old_config_without_the_key_loads_as_half(self, tmp_path):
        from src.utils.app_dirs import get_app_data_dir

        path = get_app_data_dir() / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"waveform_color": "#f0ff00"}))
        assert load_config().player_waveform_half is True

    @pytest.mark.parametrize("half", [True, False])
    def test_round_trips_through_the_panel(self, qtbot, half):
        panel = SettingsPanel()
        qtbot.addWidget(panel)
        panel.load_config(AppConfig(player_waveform_half=half))
        # Knob left = half, right = full.
        assert panel._waveform_full_switch.isChecked() is (not half)
        assert panel.get_config().player_waveform_half is half

    def test_flipping_the_switch_emits_and_updates_its_tooltip(self, qtbot):
        panel = SettingsPanel()
        qtbot.addWidget(panel)
        panel.load_config(AppConfig(player_waveform_half=True))
        before = panel._waveform_full_switch.toolTip()
        with qtbot.waitSignal(panel.settings_changed, timeout=1000):
            panel._waveform_full_switch.click()
        assert panel.get_config().player_waveform_half is False
        assert panel._waveform_full_switch.toolTip() != before


class TestToggleSwitchKnob:
    def test_knob_follows_a_state_set_with_signals_blocked(self, qtbot):
        """load_config sets the switch inside blockSignals, which emits no
        ``toggled`` — so the knob also hangs off checkStateSet."""
        sw = ToggleSwitch()
        qtbot.addWidget(sw)
        sw.blockSignals(True)
        sw.setChecked(True)
        sw.blockSignals(False)
        qtbot.waitUntil(lambda: sw.knobPos == 1.0, timeout=1000)
        sw.click()
        qtbot.waitUntil(lambda: sw.knobPos == 0.0, timeout=1000)

    def test_knob_follows_a_real_mouse_click(self, qtbot):
        """The user's path, and NOT the same code path as ``click()``: a press
        and release skip checkStateSet entirely (QAbstractButtonPrivate::click
        raises blockRefresh, and QCheckBox then calls its own checkStateSet
        non-virtually), so only ``toggled`` reports it. Written with
        QTest.mouseClick for that reason — the ``click()`` above passes either
        way and hid a switch whose knob never moved for a user.
        """
        sw = ToggleSwitch()
        qtbot.addWidget(sw)
        sw.show()
        qtbot.waitExposed(sw)
        center = sw.rect().center()
        qtbot.mouseClick(sw, Qt.MouseButton.LeftButton, pos=center)
        assert sw.isChecked()
        qtbot.waitUntil(lambda: sw.knobPos == 1.0, timeout=1000)
        qtbot.mouseClick(sw, Qt.MouseButton.LeftButton, pos=center)
        assert not sw.isChecked()
        qtbot.waitUntil(lambda: sw.knobPos == 0.0, timeout=1000)
