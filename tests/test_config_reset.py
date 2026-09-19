"""reset_to_defaults: the shipped settings, minus what a reset must not touch.

The Settings page's "Reset to Default" button is one call to this; everything
the button promises is decided here.
"""

from dataclasses import fields

import pytest

from src.utils.config import (
    PRESERVED_ON_RESET,
    AppConfig,
    reset_to_defaults,
)


def _customised() -> AppConfig:
    """A config with every field moved off its shipped value.

    Built by walking the dataclass rather than by listing fields, so a setting
    added later is covered the day it lands — the point of the test is that
    *everything* resets, and a hand-written list would only ever test the
    fields someone remembered.
    """
    cfg = AppConfig()
    for f in fields(cfg):
        shipped = getattr(cfg, f.name)
        if isinstance(shipped, bool):
            changed = not shipped
        elif isinstance(shipped, float):
            changed = shipped + 1.0
        elif isinstance(shipped, int):
            changed = shipped + 1
        elif isinstance(shipped, str):
            changed = shipped + "x"
        else:  # None — the "Keep source" convert fields
            changed = 48000
        setattr(cfg, f.name, changed)
    return cfg


class TestWhatResets:
    def test_every_other_field_goes_back_to_its_shipped_value(self):
        restored = reset_to_defaults(_customised())
        shipped = AppConfig()
        for f in fields(shipped):
            if f.name in PRESERVED_ON_RESET:
                continue
            assert getattr(restored, f.name) == getattr(shipped, f.name), f.name

    @pytest.mark.parametrize("name", PRESERVED_ON_RESET)
    def test_the_preserved_fields_are_carried_across(self, name):
        source = _customised()
        assert getattr(reset_to_defaults(source), name) == getattr(source, name)

    def test_language_and_theme_are_among_them(self):
        """The two the user asked for by name, stated rather than derived."""
        restored = reset_to_defaults(AppConfig(language="fr", theme="daylight"))
        assert restored.language == "fr"
        assert restored.theme == "daylight"

    def test_the_source_config_is_left_alone(self):
        """A reset builds a new config; the caller's own is not rewritten."""
        source = _customised()
        before = source.convert_target_format
        reset_to_defaults(source)
        assert source.convert_target_format == before

    def test_resetting_a_shipped_config_changes_nothing(self):
        assert reset_to_defaults(AppConfig()) == AppConfig()
