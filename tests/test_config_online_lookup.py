"""The online-lookup settings: off by default, and round-tripped intact."""

from __future__ import annotations

import json

from src.utils.app_dirs import get_app_data_dir
from src.utils.config import AppConfig, load_config, save_config


def test_the_feature_is_off_and_untokened_by_default():
    # The app makes no network request until the user opts in, and the default
    # config is what a fresh install runs on.
    cfg = AppConfig()
    assert cfg.online_lookup_enabled is False
    assert cfg.discogs_token == ""


def test_artwork_fetching_defaults_on_but_is_gated_by_the_master_switch():
    # Art is worth having by default; nothing fetches it while the feature is
    # off, because nothing fetches anything.
    assert AppConfig().online_fetch_artwork is True


def test_the_settings_round_trip_through_disk():
    save_config(
        AppConfig(
            online_lookup_enabled=True,
            discogs_token="abc123",
            online_fetch_artwork=False,
        )
    )
    cfg = load_config()
    assert cfg.online_lookup_enabled is True
    assert cfg.discogs_token == "abc123"
    assert cfg.online_fetch_artwork is False


def test_a_config_written_before_this_feature_takes_the_defaults():
    # An older config has none of these keys, and must read as "off" rather
    # than raising or half-enabling.
    path = get_app_data_dir() / "config.json"
    path.write_text(json.dumps({"min_bpm": 90.0}), encoding="utf-8")
    cfg = load_config()
    assert cfg.online_lookup_enabled is False
    assert cfg.discogs_token == ""
    assert cfg.online_fetch_artwork is True


def test_a_pasted_token_keeps_no_surrounding_whitespace():
    # Copying a token out of a web page brings a newline with it, and a header
    # value with a stray newline is rejected by urllib before it is by Discogs.
    save_config(AppConfig(discogs_token="  abc123\n"))
    assert load_config().discogs_token == "abc123"
