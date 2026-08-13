"""The energy field's setting, and its independence from the comment's.

The regression this guards is the one that has bitten this config before: a
field added to the dataclass but never read back in ``load_config``, so it
silently reverts to the default on every launch.
"""

import json

import pytest

from src.utils.config import AppConfig, load_config, save_config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Never touch the developer's real config.json."""
    monkeypatch.setattr(
        "src.utils.config._config_path", lambda: tmp_path / "config.json"
    )
    return tmp_path / "config.json"


def test_it_is_on_by_default():
    """A field that reads back exactly is worth having on: it costs one tag
    and it is the only source the library can trust."""
    assert AppConfig().energy_field_enabled is True


@pytest.mark.parametrize("value", [True, False])
def test_it_round_trips(value):
    save_config(AppConfig(energy_field_enabled=value))
    assert load_config().energy_field_enabled is value


def test_an_older_config_gets_the_default(isolated_config):
    """Upgrading users have no such key. They must not be read as having
    switched it off."""
    isolated_config.write_text(json.dumps({"energy_tag_enabled": True}), encoding="utf-8")

    assert load_config().energy_field_enabled is True


def test_the_two_energy_settings_are_independent():
    """The comment is prose and optional; the field is exact and separately
    optional. Neither governs the other."""
    save_config(AppConfig(energy_tag_enabled=False, energy_field_enabled=True))
    cfg = load_config()
    assert (cfg.energy_tag_enabled, cfg.energy_field_enabled) == (False, True)

    save_config(AppConfig(energy_tag_enabled=True, energy_field_enabled=False))
    cfg = load_config()
    assert (cfg.energy_tag_enabled, cfg.energy_field_enabled) == (True, False)
