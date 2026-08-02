"""Config handling for the Playlists settings (§22 duplicate policy, export)."""

import pytest

from src.utils.config import AppConfig, load_config, save_config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Never touch the developer's real config.json."""
    monkeypatch.setattr(
        "src.utils.config._config_path", lambda: tmp_path / "config.json"
    )


class TestDuplicatePolicy:
    def test_default_is_ask(self):
        """Asking is the shipped default: duplicates are neither silently
        added nor silently dropped until the user says which they want."""
        assert AppConfig().duplicate_policy == "ask"

    @pytest.mark.parametrize("value", ["ask", "add", "skip"])
    def test_each_valid_value_round_trips(self, value):
        save_config(AppConfig(duplicate_policy=value))
        assert load_config().duplicate_policy == value

    def test_an_unknown_value_falls_back_to_ask(self):
        """A hand-edited or stale value must not disable the prompt."""
        save_config(AppConfig(duplicate_policy="always_maybe"))
        assert load_config().duplicate_policy == "ask"


class TestExportAbsolutePaths:
    """Regression: the field existed but load_config() never read it back."""

    def test_it_round_trips(self):
        save_config(AppConfig(export_absolute_paths=True))
        assert load_config().export_absolute_paths is True

    def test_the_default_still_survives_a_round_trip(self):
        save_config(AppConfig())
        assert load_config().export_absolute_paths is False


class TestPersistScratch:
    def test_default_is_off(self):
        """Scratch is disposable by design — the name promises it."""
        assert AppConfig().persist_scratch is False

    def test_it_round_trips(self):
        """The same read-back that export_absolute_paths originally missed."""
        save_config(AppConfig(persist_scratch=True))
        assert load_config().persist_scratch is True

    def test_the_default_still_survives_a_round_trip(self):
        save_config(AppConfig())
        assert load_config().persist_scratch is False
