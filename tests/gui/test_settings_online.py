"""The Online Metadata section of Settings: round-trip, and the token's echo."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLineEdit

from src.gui.widgets.settings_panel import SettingsPanel
from src.utils.config import AppConfig


@pytest.fixture
def panel(qtbot):
    widget = SettingsPanel()
    qtbot.addWidget(widget)
    return widget


def test_a_fresh_panel_reads_as_off(panel):
    # The panel is constructed before any config is loaded; if its own default
    # were "on", a user who never opens Settings would have the feature on.
    cfg = panel.get_config()
    assert cfg.online_lookup_enabled is False
    assert cfg.discogs_token == ""


def test_the_three_settings_survive_a_round_trip(panel):
    panel.load_config(
        AppConfig(
            online_lookup_enabled=True,
            discogs_token="abc123",
            online_fetch_artwork=False,
        )
    )
    cfg = panel.get_config()
    assert cfg.online_lookup_enabled is True
    assert cfg.discogs_token == "abc123"
    assert cfg.online_fetch_artwork is False


def test_the_token_is_not_shown_on_screen(panel):
    # It is a credential; anyone screen-sharing Settings shouldn't hand it out.
    assert panel._discogs_token_edit.echoMode() == QLineEdit.EchoMode.Password


def test_a_pasted_token_loses_its_surrounding_whitespace(panel):
    panel._discogs_token_edit.setText("  abc123  ")
    assert panel.get_config().discogs_token == "abc123"


def test_the_section_does_not_disturb_the_other_settings(panel):
    # get_config() rebuilds the whole AppConfig; a field this panel does not
    # manage must come through from the base untouched.
    base = AppConfig(convert_mp3_bitrate=192, online_lookup_enabled=True)
    assert panel.get_config(base).convert_mp3_bitrate == 192
