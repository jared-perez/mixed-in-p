"""Config handling for the History display limit."""

from src.utils.config import (
    DEFAULT_HISTORY_DISPLAY_LIMIT,
    HISTORY_DISPLAY_LIMITS,
    AppConfig,
    load_config,
    save_config,
)


class TestHistoryLimitConfig:
    def test_default_matches_named_default(self):
        assert AppConfig().history_display_limit == DEFAULT_HISTORY_DISPLAY_LIMIT == 100

    def test_default_is_a_valid_option(self):
        assert DEFAULT_HISTORY_DISPLAY_LIMIT in HISTORY_DISPLAY_LIMITS

    def test_valid_value_round_trips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "src.utils.config._config_path", lambda: tmp_path / "config.json"
        )
        cfg = AppConfig(history_display_limit=500)
        save_config(cfg)
        assert load_config().history_display_limit == 500

    def test_invalid_value_falls_back_to_default(self, tmp_path, monkeypatch):
        """A hand-edited or stale value outside the option set is corrected."""
        monkeypatch.setattr(
            "src.utils.config._config_path", lambda: tmp_path / "config.json"
        )
        save_config(AppConfig(history_display_limit=777))
        assert load_config().history_display_limit == DEFAULT_HISTORY_DISPLAY_LIMIT

    def test_retention_ceiling_covers_largest_option(self):
        """MAX_ENTRIES must be >= the biggest display option, or raising the
        limit could never reveal the promised number of rows."""
        from src.analysis.history import MAX_ENTRIES

        assert MAX_ENTRIES >= max(HISTORY_DISPLAY_LIMITS)
