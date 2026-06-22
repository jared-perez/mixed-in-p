"""Application configuration persistence."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .i18n import DEFAULT_LANGUAGE, LANGUAGE_CODES

logger = logging.getLogger(__name__)

_VALID_NAMING_PREFS = {
    "tempo_key_prefix",
    "key_tempo_prefix",
    "key_prefix",
    "suffix_key_tempo",
    "suffix_key",
}

_VALID_ENERGY_FORMATS = {"number_only", "with_label"}
_VALID_ENERGY_MODES = {"prepend", "append", "replace"}
_VALID_KEY_NOTATIONS = {"keycode", "traditional", "open_key"}
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _valid_theme_ids() -> set[str] | None:
    """The selectable theme ids, sourced from the GUI theme registry (THEMES).

    Imported lazily so this utils module — which the CLI also uses — never drags
    the PySide6/GUI layer in at import time; the cost is paid only if theme
    validation actually runs. Returns ``None`` if that layer isn't importable
    (e.g. a headless context), signalling "skip theme validation" so a valid
    stored theme is left intact rather than wrongly reset. Deriving the set here
    means a new palette added to THEMES is accepted with no change to config.
    """
    try:
        from ..gui.styles.theme import THEMES
    except Exception:
        return None
    return set(THEMES)


@dataclass
class AppConfig:
    """Persistent application settings."""

    min_bpm: float = 99.0
    max_bpm: float = 199.0
    auto_rename: bool = True
    naming_preference: str = "tempo_key_prefix"
    key_notation: str = "keycode"
    auto_analyze: bool = True
    auto_write_bpm: bool = True
    auto_write_key: bool = True
    energy_tag_enabled: bool = True
    energy_tag_format: str = "number_only"
    energy_tag_mode: str = "prepend"
    key_in_comment_enabled: bool = False
    # When both key and energy are written to the comment, write energy first.
    energy_written_first: bool = True
    convert_target_format: str = "AIFF"
    convert_mp3_bitrate: int = 320
    convert_sample_rate: int = 44100
    convert_bit_depth: int = 16
    spectrum_dynamic_range: float = 110.0
    # Full-length player waveform body color (#RRGGBB). Default is neon yellow.
    waveform_color: str = "#f0ff00"
    # When True, the Player playlist's inline metadata editing is locked off.
    player_edit_locked: bool = False
    language: str = DEFAULT_LANGUAGE
    # Colour scheme id (see THEMES in src/gui/styles/theme.py). Applied at
    # startup; changing it requires a restart (like ``language``).
    theme: str = "nuevo_leon"
    # Base64-encoded QHeaderView.saveState() for the Player playlist columns
    # (order + widths). Empty = use the built-in default layout.
    player_column_state: str = ""
    # Base64-encoded QMainWindow.saveGeometry() (size + position + maximized
    # state). Empty = open at the default size, centered. The Keyboard panel's
    # transient resize is never stored here.
    window_geometry: str = ""


def _config_path() -> Path:
    """Return the path to the config JSON file."""
    from .app_dirs import get_app_data_dir
    return get_app_data_dir() / "config.json"


def load_config() -> AppConfig:
    """Load config from disk, returning defaults if missing or corrupt."""
    path = _config_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            cfg = AppConfig(
                min_bpm=float(data.get("min_bpm", AppConfig.min_bpm)),
                max_bpm=float(data.get("max_bpm", AppConfig.max_bpm)),
                auto_rename=bool(data.get("auto_rename", AppConfig.auto_rename)),
                naming_preference=data.get("naming_preference", AppConfig.naming_preference),
                key_notation=data.get(
                    "key_notation",
                    # Migrate from the legacy boolean if present.
                    "traditional" if data.get("use_traditional_key") else AppConfig.key_notation,
                ),
                auto_analyze=bool(data.get("auto_analyze", AppConfig.auto_analyze)),
                # Split from the legacy combined auto_write_metadata flag; fall
                # back to it so old configs keep their previous behaviour.
                auto_write_bpm=bool(
                    data.get("auto_write_bpm", data.get("auto_write_metadata", AppConfig.auto_write_bpm))
                ),
                auto_write_key=bool(
                    data.get("auto_write_key", data.get("auto_write_metadata", AppConfig.auto_write_key))
                ),
                energy_tag_enabled=bool(data.get("energy_tag_enabled", AppConfig.energy_tag_enabled)),
                energy_tag_format=data.get("energy_tag_format", AppConfig.energy_tag_format),
                energy_tag_mode=data.get("energy_tag_mode", AppConfig.energy_tag_mode),
                key_in_comment_enabled=bool(data.get("key_in_comment_enabled", AppConfig.key_in_comment_enabled)),
                energy_written_first=bool(
                    # Fall back to the legacy key so existing configs migrate.
                    data.get("energy_written_first",
                             data.get("key_secondary_to_energy", AppConfig.energy_written_first))
                ),
                convert_target_format=data.get("convert_target_format", AppConfig.convert_target_format),
                convert_mp3_bitrate=int(data.get("convert_mp3_bitrate", AppConfig.convert_mp3_bitrate)),
                convert_sample_rate=int(data.get("convert_sample_rate", AppConfig.convert_sample_rate)),
                convert_bit_depth=int(data.get("convert_bit_depth", AppConfig.convert_bit_depth)),
                spectrum_dynamic_range=float(
                    data.get("spectrum_dynamic_range", AppConfig.spectrum_dynamic_range)
                ),
                waveform_color=str(data.get("waveform_color", AppConfig.waveform_color)),
                player_edit_locked=bool(
                    data.get("player_edit_locked", AppConfig.player_edit_locked)
                ),
                language=data.get("language", AppConfig.language),
                theme=data.get("theme", AppConfig.theme),
                player_column_state=data.get(
                    "player_column_state", AppConfig.player_column_state
                ),
                window_geometry=data.get(
                    "window_geometry", AppConfig.window_geometry
                ),
            )
            # Sanitise
            cfg.min_bpm = max(50.0, min(cfg.min_bpm, 248.0))
            cfg.max_bpm = max(52.0, min(cfg.max_bpm, 250.0))
            if cfg.min_bpm >= cfg.max_bpm:
                cfg.min_bpm = AppConfig.min_bpm
                cfg.max_bpm = AppConfig.max_bpm
            if cfg.naming_preference not in _VALID_NAMING_PREFS:
                cfg.naming_preference = AppConfig.naming_preference
            if cfg.key_notation not in _VALID_KEY_NOTATIONS:
                cfg.key_notation = AppConfig.key_notation
            if cfg.energy_tag_format not in _VALID_ENERGY_FORMATS:
                cfg.energy_tag_format = AppConfig.energy_tag_format
            if cfg.energy_tag_mode not in _VALID_ENERGY_MODES:
                cfg.energy_tag_mode = AppConfig.energy_tag_mode
            if cfg.convert_target_format not in {"WAV", "FLAC", "AIFF", "MP3"}:
                cfg.convert_target_format = AppConfig.convert_target_format
            if cfg.convert_mp3_bitrate not in {128, 192, 256, 320}:
                cfg.convert_mp3_bitrate = AppConfig.convert_mp3_bitrate
            if cfg.convert_sample_rate not in {32000, 44100, 48000, 96000}:
                cfg.convert_sample_rate = AppConfig.convert_sample_rate
            if cfg.convert_bit_depth not in {8, 16, 24, 32}:
                cfg.convert_bit_depth = AppConfig.convert_bit_depth
            cfg.spectrum_dynamic_range = max(60.0, min(cfg.spectrum_dynamic_range, 150.0))
            if not _HEX_COLOR_RE.match(cfg.waveform_color):
                cfg.waveform_color = AppConfig.waveform_color
            if cfg.language not in LANGUAGE_CODES:
                cfg.language = AppConfig.language
            valid_themes = _valid_theme_ids()
            if valid_themes is not None and cfg.theme not in valid_themes:
                cfg.theme = AppConfig.theme
            return cfg
    except Exception as exc:
        logger.warning("Failed to load config: %s", exc)
    return AppConfig()


def save_config(cfg: AppConfig) -> None:
    """Persist config to disk."""
    path = _config_path()
    try:
        path.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to save config: %s", exc)
