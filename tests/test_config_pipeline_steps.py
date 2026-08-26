"""Config for the pipeline's three step toggles and its target playlist.

These replaced a single convert_pipeline_enabled flag, so most of what is
worth testing here is the fold: what a config written by a build that had one
switch becomes under a build that has three.
"""

import json

import pytest

from src.utils.config import AppConfig, load_config, save_config


@pytest.fixture(autouse=True)
def config_at(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr("src.utils.config._config_path", lambda: path)
    return path


def write(config_at, data: dict) -> None:
    config_at.write_text(json.dumps(data), encoding="utf-8")


class TestDefaults:
    def test_every_step_starts_off(self):
        cfg = AppConfig()
        assert cfg.pipeline_rename_enabled is False
        assert cfg.pipeline_convert_enabled is False
        assert cfg.pipeline_analyze_enabled is False
        assert cfg.pipeline_playlist == ""

    def test_they_round_trip(self, config_at):
        save_config(
            AppConfig(
                pipeline_rename_enabled=True,
                pipeline_analyze_enabled=True,
                pipeline_playlist="Friday set",
            )
        )
        cfg = load_config()
        assert cfg.pipeline_rename_enabled is True
        assert cfg.pipeline_convert_enabled is False
        assert cfg.pipeline_analyze_enabled is True
        assert cfg.pipeline_playlist == "Friday set"


class TestFoldingTheOldFlag:
    def test_the_old_flag_on_means_convert_and_analyze(self, config_at):
        """That is what the one switch did: convert, analyse, file it."""
        write(config_at, {"convert_pipeline_enabled": True,
                          "convert_pipeline_playlist": "Friday set"})
        cfg = load_config()
        assert cfg.pipeline_convert_enabled is True
        assert cfg.pipeline_analyze_enabled is True
        assert cfg.pipeline_rename_enabled is False  # nothing to inherit from
        assert cfg.pipeline_playlist == "Friday set"

    def test_the_old_flag_off_leaves_every_step_off(self, config_at):
        write(config_at, {"convert_pipeline_enabled": False,
                          "convert_pipeline_playlist": "Friday set"})
        cfg = load_config()
        assert cfg.pipeline_convert_enabled is False
        assert cfg.pipeline_analyze_enabled is False
        assert cfg.pipeline_playlist == "Friday set"

    def test_the_new_keys_win_where_they_exist(self, config_at):
        """A stale legacy key beside them is older than the user's last choice."""
        write(config_at, {
            "convert_pipeline_enabled": True,
            "convert_pipeline_playlist": "Old",
            "pipeline_convert_enabled": False,
            "pipeline_analyze_enabled": True,
            "pipeline_rename_enabled": True,
            "pipeline_playlist": "New",
        })
        cfg = load_config()
        assert cfg.pipeline_convert_enabled is False
        assert cfg.pipeline_analyze_enabled is True
        assert cfg.pipeline_rename_enabled is True
        assert cfg.pipeline_playlist == "New"

    def test_the_first_save_retires_the_fold(self, config_at):
        """What makes it one-way without a version counter."""
        write(config_at, {"convert_pipeline_enabled": True,
                          "convert_pipeline_playlist": "Friday set"})
        save_config(load_config())
        stored = json.loads(config_at.read_text())
        assert "convert_pipeline_enabled" not in stored
        assert "convert_pipeline_playlist" not in stored
        assert stored["pipeline_convert_enabled"] is True
        assert stored["pipeline_playlist"] == "Friday set"

    def test_re_running_the_fold_is_harmless(self, config_at):
        write(config_at, {"convert_pipeline_enabled": True})
        first = load_config()
        second = load_config()
        assert first == second

    def test_switching_the_steps_off_afterwards_sticks(self, config_at):
        """The fold must not resurrect the old flag's answer on the next load."""
        write(config_at, {"convert_pipeline_enabled": True,
                          "convert_pipeline_playlist": "Friday set"})
        cfg = load_config()
        cfg.pipeline_convert_enabled = False
        cfg.pipeline_analyze_enabled = False
        save_config(cfg)
        reloaded = load_config()
        assert reloaded.pipeline_convert_enabled is False
        assert reloaded.pipeline_analyze_enabled is False

    def test_a_config_with_neither_key_takes_the_defaults(self, config_at):
        write(config_at, {"convert_target_format": "WAV"})
        cfg = load_config()
        assert cfg.pipeline_convert_enabled is False
        assert cfg.pipeline_playlist == ""


class TestAutoAnalyzeIsNotCoupled:
    def test_a_step_toggle_survives_auto_analyze_being_off(self, config_at):
        """load_config used to force the pipeline off here. The pipeline drives
        its own analysis, so it owes that setting nothing."""
        save_config(
            AppConfig(
                auto_analyze=False,
                pipeline_convert_enabled=True,
                pipeline_analyze_enabled=True,
            )
        )
        cfg = load_config()
        assert cfg.pipeline_convert_enabled is True
        assert cfg.pipeline_analyze_enabled is True

    def test_the_fold_ignores_auto_analyze_too(self, config_at):
        write(config_at, {"auto_analyze": False, "convert_pipeline_enabled": True})
        cfg = load_config()
        assert cfg.pipeline_analyze_enabled is True
