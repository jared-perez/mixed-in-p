"""Settings' "Reset to Default": the confirm, and what the window puts back.

Driven through a real MainWindow for the second half, because what a reset has
to get right is the *pushing*: several panels own a config field and write it
themselves, so a reset that only rewrote the file would leave those panels
showing — and then re-saving — the values it just cleared. A stub panel cannot
have that bug.

Structure, never pixels: the suite runs with no application stylesheet.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from src.gui.convert_pipeline import STEP_ORDER
from src.gui.widgets.settings_panel import SettingsPanel
from src.utils.config import AppConfig, load_config, save_config


@pytest.fixture
def answer_box(monkeypatch):
    """Answer the confirmation, and count the times it was asked."""
    asked = []

    def build(button):
        def fake(*args, **kwargs):
            asked.append(args[2] if len(args) > 2 else "")
            return button

        monkeypatch.setattr(QMessageBox, "warning", fake)
        return asked

    return build


# ------------------------------------------------------------------- the ask


class TestTheConfirmation:
    @pytest.fixture
    def panel(self, qtbot):
        widget = SettingsPanel()
        qtbot.addWidget(widget)
        return widget

    def test_reset_asks_first_and_emits_when_confirmed(self, panel, qtbot, answer_box):
        asked = answer_box(QMessageBox.StandardButton.Reset)
        with qtbot.waitSignal(panel.reset_requested, timeout=1000):
            panel._reset_btn.click()
        assert len(asked) == 1

    def test_cancelling_changes_nothing(self, panel, answer_box):
        answer_box(QMessageBox.StandardButton.Cancel)
        fired = []
        panel.reset_requested.connect(lambda: fired.append(True))
        panel._reset_btn.click()
        assert not fired

    def test_the_question_names_what_survives(self, panel, answer_box):
        """The two exemptions the user has to know about before clicking."""
        asked = answer_box(QMessageBox.StandardButton.Cancel)
        panel._reset_btn.click()
        assert "language" in asked[0].lower()
        assert "theme" in asked[0].lower()


# ---------------------------------------------------------------- the window


@pytest.fixture
def window(qtbot):
    made = []

    def build(**cfg):
        save_config(AppConfig(**cfg))
        from src.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)
        made.append(win)
        return win

    yield build
    for win in made:
        win._player_panel.shutdown_workers()


# A config with something changed in every panel that owns a field, so one
# reset can be checked everywhere it has to reach.
CUSTOMISED = dict(
    language="fr",
    theme="daylight",
    min_bpm=70.0,
    max_bpm=180.0,
    auto_rename=False,
    key_notation="traditional",
    convert_target_format="MP3",
    convert_mp3_bitrate=128,
    player_edit_locked=True,
    visualization_mode="backdrop_fire",
    metronome_global_click=False,
    duplicate_policy="add",
    history_display_limit=500,
    pipeline_rename_enabled=True,
    pipeline_convert_enabled=True,
    pipeline_playlist="Tonight",
    discogs_token="secret-token",
    online_lookup_enabled=True,
    player_column_state="c3RhdGU=",
    player_column_count=15,
    player_column_defaults_version=2,
    window_geometry="Z2VvbQ==",
)


class TestTheWindowRestoresEverything:
    def test_the_stored_config_is_back_to_shipped(self, window):
        win = window(**CUSTOMISED)
        win._on_settings_reset()
        stored = load_config()
        assert stored.min_bpm == AppConfig.min_bpm
        assert stored.auto_rename == AppConfig.auto_rename
        assert stored.convert_target_format == AppConfig.convert_target_format
        assert stored.player_edit_locked == AppConfig.player_edit_locked
        assert stored.visualization_mode == AppConfig.visualization_mode
        assert stored.metronome_global_click == AppConfig.metronome_global_click
        assert stored.discogs_token == ""

    def test_language_theme_and_layout_survive(self, window):
        win = window(**CUSTOMISED)
        # Read back rather than compared against CUSTOMISED: the Player
        # rewrites the column trio at startup when the stored layout predates
        # the shipped one, so what must survive the reset is whatever is on
        # disk the moment before it — not what this test put there.
        before = load_config()
        win._on_settings_reset()
        stored = load_config()
        assert stored.language == "fr"
        assert stored.theme == "daylight"
        assert stored.window_geometry == "Z2VvbQ=="
        assert stored.player_column_state == before.player_column_state
        assert stored.player_column_count == before.player_column_count
        assert (
            stored.player_column_defaults_version
            == before.player_column_defaults_version
        )

    def test_the_settings_page_shows_the_restored_values(self, window):
        win = window(**CUSTOMISED)
        win._on_settings_reset()
        panel = win._settings_panel
        assert panel._min_bpm_spin.value() == int(AppConfig.min_bpm)
        assert panel._auto_rename_cb.isChecked() is AppConfig.auto_rename
        assert panel._duplicate_policy_combo.currentData() == "ask"
        assert panel._discogs_token_edit.text() == ""
        # ...while the two exemptions are still selected in their combos.
        assert panel._language_combo.currentData() == "fr"
        assert panel._theme_combo.currentData() == "daylight"

    def test_the_convert_panel_shows_the_restored_format(self, window):
        """A panel left showing MP3 would write MP3 back on the next click."""
        win = window(**CUSTOMISED)
        win._on_settings_reset()
        convert = win._conversion_panel
        assert convert._format_combo.currentText() == AppConfig.convert_target_format
        assert convert._samplerate_combo.currentData() == AppConfig.convert_sample_rate
        assert convert._bitdepth_combo.currentData() == AppConfig.convert_bit_depth
        assert convert._use_source_dir is True

    def test_the_player_panel_controls_follow(self, window):
        win = window(**CUSTOMISED)
        win._on_settings_reset()
        player = win._player_panel
        assert player._edit_lock_cb.isChecked() is False
        assert player._vis_mode == "off"
        assert player._metronome_section.view.global_click is True

    def test_the_pipeline_is_switched_off_in_both_mirrors(self, window):
        win = window(**CUSTOMISED)
        win._on_settings_reset()
        for step in STEP_ORDER:
            assert win._header.pipeline.step_enabled(step) is False
            assert win._panel_for_step(step)._pipeline_toggle.isChecked() is False
        assert win._header.pipeline.pipeline_target() == (None, "")
        assert load_config().pipeline_playlist == ""

    def test_a_panel_writing_after_the_reset_does_not_resurrect_a_setting(
        self, window
    ):
        """The reason the panels are pushed to at all, stated as a test.

        _persist_config re-reads the panel-owned fields from disk, so anything
        a panel is still holding gets written back the next time the window
        saves. With the panel reloaded there is nothing stale to write.
        """
        win = window(**CUSTOMISED)
        win._on_settings_reset()
        win._conversion_panel._save_convert_settings()
        win._persist_config()
        assert load_config().convert_target_format == AppConfig.convert_target_format

    def test_the_history_and_spectrum_panels_follow(self, window):
        win = window(**CUSTOMISED)
        win._on_settings_reset()
        assert win._history_panel._display_limit == AppConfig.history_display_limit
        assert win._spectrum_panel._split is AppConfig.spectrum_split
