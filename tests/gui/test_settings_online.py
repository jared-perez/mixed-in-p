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


# --- the token switches the feature on ---------------------------------------


def test_pasting_a_token_turns_the_lookup_on(panel):
    # Nobody pastes a Discogs token in order to leave Discogs switched off,
    # and the two controls sit one above the other — so the feature staying
    # off read as a token that had not taken.
    assert panel._online_lookup_cb.isChecked() is False
    panel._discogs_token_edit.setText("abc123")
    assert panel._online_lookup_cb.isChecked() is True
    # And it is saved with the token it belongs to, not merely displayed.
    assert panel.get_config().online_lookup_enabled is True


def test_clearing_the_token_does_not_turn_the_lookup_off(panel):
    # A lookup works without a token — slower, and with no cover art — so an
    # empty box is not a request to switch the feature off.
    panel._discogs_token_edit.setText("abc123")
    panel._discogs_token_edit.setText("")
    assert panel._online_lookup_cb.isChecked() is True


def test_editing_a_token_does_not_overrule_a_deliberate_off(panel):
    # Only the empty → filled transition ticks it, so someone who turned the
    # feature off with a token in the box stays off while they edit it.
    panel.load_config(AppConfig(online_lookup_enabled=False, discogs_token="abc123"))
    panel._discogs_token_edit.setText("abc124")
    assert panel._online_lookup_cb.isChecked() is False


def test_loading_a_saved_token_is_not_mistaken_for_typing_one(panel):
    # Otherwise every launch of a user who had switched the feature back off
    # would switch it on again for them.
    panel.load_config(AppConfig(online_lookup_enabled=False, discogs_token="abc123"))
    assert panel._online_lookup_cb.isChecked() is False


def test_the_tick_is_not_persisted_on_every_keystroke(panel):
    """It is reflected, and left for editingFinished to save with the token.

    Ticking it for real here would emit settings_changed per keystroke and
    write a dozen half-tokens to disk — which is exactly why the token itself
    is persisted on editingFinished rather than on textChanged.
    """
    emitted: list = []
    panel.settings_changed.connect(lambda: emitted.append(1))
    panel._discogs_token_edit.setText("abc123")
    assert emitted == []
    panel._discogs_token_edit.editingFinished.emit()
    assert len(emitted) == 1
