"""Config handling for the Convert panel's rate and depth, which are optional.

None is the "Keep source" selection and has to survive a round trip through
JSON as null — a bare int() on the way back in would raise, and treating a
missing key and an explicit null the same way would silently reset the choice.
"""

import json

import pytest

from src.utils.config import AppConfig, load_config, save_config


@pytest.fixture(autouse=True)
def config_at(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr("src.utils.config._config_path", lambda: path)
    return path


class TestKeepSourceRoundTrip:
    def test_none_survives(self, config_at):
        save_config(AppConfig(convert_sample_rate=None, convert_bit_depth=None))

        assert json.loads(config_at.read_text())["convert_sample_rate"] is None
        cfg = load_config()
        assert cfg.convert_sample_rate is None
        assert cfg.convert_bit_depth is None

    def test_numbers_still_survive(self):
        save_config(AppConfig(convert_sample_rate=96000, convert_bit_depth=24))
        cfg = load_config()
        assert (cfg.convert_sample_rate, cfg.convert_bit_depth) == (96000, 24)

    def test_one_axis_kept_one_set(self):
        save_config(AppConfig(convert_sample_rate=None, convert_bit_depth=16))
        cfg = load_config()
        assert cfg.convert_sample_rate is None
        assert cfg.convert_bit_depth == 16

    def test_missing_key_takes_the_default(self, config_at):
        """An older config predating the option is not read as "Keep source"."""
        config_at.write_text(json.dumps({"convert_target_format": "FLAC"}))
        cfg = load_config()
        assert cfg.convert_sample_rate == AppConfig.convert_sample_rate
        assert cfg.convert_bit_depth == AppConfig.convert_bit_depth

    def test_defaults_are_unchanged_by_the_new_option(self):
        """Adding "Keep source" did not make it the shipped default."""
        assert AppConfig().convert_sample_rate == 44100
        assert AppConfig().convert_bit_depth == 16

    def test_junk_falls_back_rather_than_raising(self, config_at):
        config_at.write_text(json.dumps({"convert_sample_rate": "loud"}))
        assert load_config().convert_sample_rate == AppConfig.convert_sample_rate

    def test_out_of_range_value_is_still_corrected(self):
        """The validity check has to admit None without admitting anything."""
        save_config(AppConfig(convert_sample_rate=12345))
        assert load_config().convert_sample_rate == AppConfig.convert_sample_rate
