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

# Selectable row counts for the History panel's "Show" dropdown. The largest is
# also the effective retention ceiling — see analysis.history.MAX_ENTRIES, kept
# in step so raising the display limit can always reveal stored rows.
HISTORY_DISPLAY_LIMITS = (50, 100, 250, 500, 1000)

# Default row count. Not necessarily the first option — decoupled so the default
# can differ from the smallest selectable value.
DEFAULT_HISTORY_DISPLAY_LIMIT = 100

_VALID_ENERGY_FORMATS = {"number_only", "with_label"}
# What happens when tracks are added to a playlist that already holds them.
# "ask" prompts; the other two are the silent answers to that same prompt.
_VALID_DUPLICATE_POLICIES = {"ask", "add", "skip"}
_VALID_ENERGY_MODES = {"prepend", "append", "replace"}
_VALID_KEY_NOTATIONS = {"keycode", "traditional", "open_key"}
# Playlist text-size presets. The px values live in the Player panel —
# this is only the set of names a config file may hold.
_VALID_TEXT_SIZES = {"small", "medium", "large"}
_VALID_ARTWORK_VIEWS = {"top", "middle", "full"}
_VALID_VIS_MODES = {
    "off",
    # Behind the playlist rows.
    "backdrop",
    "backdrop_scope",
    "backdrop_spectrum",
    "backdrop_fire",
    "backdrop_fractal",
    "backdrop_loop_tunnel",
    "backdrop_beat_tunnel",
    # Popout visualizer window.
    "oscilloscope",
    "spectrum",
    "fractal",
    "loop_tunnel",
    "beat_tunnel",
}
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
    # The dedicated energy field (TXXX:EnergyLevel and friends), independent of
    # the comment above: a comment is prose and "4" in one is ambiguous, so a
    # field of its own is what makes the energy readable back without guessing.
    energy_field_enabled: bool = True
    energy_tag_format: str = "number_only"
    energy_tag_mode: str = "prepend"
    key_in_comment_enabled: bool = False
    # When both key and energy are written to the comment, write energy first.
    energy_written_first: bool = True
    convert_target_format: str = "AIFF"
    convert_mp3_bitrate: int = 320
    # None is the "Keep source" selection — the engine reads it as "don't
    # change this axis", which is what the CLI passes when the flag is omitted.
    convert_sample_rate: int | None = 44100
    convert_bit_depth: int | None = 16
    # Where converted files are written, as a mode plus a remembered folder.
    #
    # The two are deliberately independent: convert_output_dir holds the last
    # folder the user picked even while the Source toggle is on, so switching
    # back to it is one click rather than a second trip through the file
    # dialog. Only convert_use_source_dir decides what a conversion actually
    # does — on means "beside each source file", which is what the engine does
    # with output_dir=None, so a batch spanning several folders lands each file
    # next to its own original.
    #
    # A remembered folder that has since been deleted is cleared on load (and
    # forces the mode back on), rather than failing every conversion later with
    # a stale path.
    convert_output_dir: str = ""
    convert_use_source_dir: bool = True
    # Which steps a pipeline run performs. The order is fixed (rename ->
    # convert -> analyze -> playlist); these only say which of the three run,
    # and a run started from a panel flows through the later enabled ones.
    #
    # There is no toggle for the playlist add: it is where every run ends, so
    # with analyze off the files land there un-analysed rather than not at all.
    # The target is stored as the playlist's NAME, not a node id: an id means
    # nothing once the playlist it named has been deleted, while a name that no
    # longer matches anything reads as "create one", which is the right answer.
    #
    # These replaced a single convert_pipeline_enabled flag — see
    # _folded_pipeline_steps for what an old config becomes.
    pipeline_rename_enabled: bool = False
    pipeline_convert_enabled: bool = False
    pipeline_analyze_enabled: bool = False
    pipeline_playlist: str = ""
    spectrum_dynamic_range: float = 110.0
    # Full-length player waveform body color (#RRGGBB). Default is neon yellow.
    waveform_color: str = "#f0ff00"
    # When True, the Player playlist's inline metadata editing is locked off.
    player_edit_locked: bool = False
    # The visual showing in the Player, chosen from its eye-icon menu (see
    # _VALID_VIS_MODES). "off" is one of the modes rather than a separate
    # switch: picking a visual is what starts it. There was a
    # visualizations_enabled master switch in Settings until 2026-08-23 —
    # LEGACY_VIS_SWITCH below folds it into this field.
    visualization_mode: str = "off"
    # Force absolute paths in exported playlists. Off by default: the
    # exporter writes relative paths when the tracks sit under the playlist
    # file's own folder, which is what makes an exported folder portable to
    # another machine (see src/library/playlist_export.py).
    export_absolute_paths: bool = False
    # What to do when tracks are added to a playlist that already contains
    # them: "ask" (prompt Add/Skip/Cancel), "add" (always keep duplicates) or
    # "skip" (always drop them). Applies to every playlist including Scratch,
    # and to every entry point except loading a saved playlist, which restores
    # its stored duplicates verbatim.
    duplicate_policy: str = "ask"
    # Whether Scratch survives a restart. Off by default: Scratch is the
    # disposable working list the Player opens on, so each session starts
    # empty and a list worth keeping is kept with Save Playlist. Turning this
    # on makes Scratch behave like every other playlist. Only the contents are
    # cleared (at startup, so a crash can't strand a half-written list) — the
    # node itself is reserved and always exists.
    persist_scratch: bool = False
    # Online metadata lookup (Discogs). Off by default and, while off, the
    # lookup affordances are *hidden* rather than greyed — the app should look
    # fully offline, because it is. What ever leaves the machine is the artist
    # and title of the tracks the user chose to look up. Never the audio.
    online_lookup_enabled: bool = False
    # A Discogs personal access token, stored in plain text here alongside the
    # other preferences. It is read-scope and revocable in one click on the
    # user's Discogs account page, which is why this is the ecosystem norm
    # (beets, Picard) rather than per-platform keychain surface.
    discogs_token: str = ""
    # Whether a lookup also fetches the release's cover. Separate from the
    # master switch because art is the one proposal that costs a second
    # request and rewrites a large binary field; the write still happens only
    # after the user approves it, like every other field.
    online_fetch_artwork: bool = True
    language: str = DEFAULT_LANGUAGE
    # Colour scheme id (see THEMES in src/gui/styles/theme.py). Applied at
    # startup; changing it requires a restart (like ``language``).
    theme: str = "nuevo_leon"
    # How many rows the History panel shows (both the Key History and Rename
    # views). A display cap only — analysis entries are retained up to
    # analysis.history.MAX_ENTRIES and session files persist regardless, so
    # raising this later reveals older rows rather than re-creating them.
    history_display_limit: int = DEFAULT_HISTORY_DISPLAY_LIMIT
    # Base64-encoded QHeaderView.saveState() for the Player playlist columns
    # (order + widths). Empty = use the built-in default layout.
    player_column_state: str = ""
    # How many columns the state above was saved from. Qt happily restores a
    # 9-column state into a wider table — and in doing so *un-hides* every
    # section the state never knew about, so a saved layout from before a
    # column was added would silently show it. This says which sections the
    # state has an opinion about; the rest take their default visibility.
    player_column_count: int = 0
    # Which generation of the shipped column layout this config has seen. A
    # saved state always wins over the defaults, so a change to the *default*
    # order or visibility would never reach anyone who has used the app — this
    # is what lets such a change be applied once and then never again. 0 means
    # "written before the field existed", i.e. every config in the wild.
    player_column_defaults_version: int = 0
    # Playlist text size: small/medium/large. Applied live, no restart —
    # unlike the theme, nothing caches a font the way widgets cache colours.
    player_text_size: str = "medium"
    # Which part of the cover the playlist's Art column shows: top/middle/full.
    # "top" and "middle" are a band one row tall cut from a cover scaled the
    # same either way; "full" keeps the whole square and lets the row grow to
    # fit it. Applied live, like the text size it scales with.
    player_artwork_view: str = "top"
    # Base64-encoded QMainWindow.saveGeometry() (size + position + maximized
    # state). Empty = open at the default size, centered. The Keyboard panel's
    # transient resize is never stored here.
    window_geometry: str = ""


def _config_path() -> Path:
    """Return the path to the config JSON file."""
    from .app_dirs import get_app_data_dir
    return get_app_data_dir() / "config.json"


# The Settings switch that used to gate the Player's visuals before the mode
# became the only control. A config written by an older build still carries it.
LEGACY_VIS_SWITCH = "visualizations_enabled"


def _folded_vis_mode(data: dict) -> str:
    """The stored visual, with the retired master switch folded in.

    Every config in the wild carries a mode *and* a switch that was off by
    default, so reading the mode alone would start a visual for everyone who
    never asked for one — the switch was what had been suppressing it. An
    explicitly off switch therefore means "off", whatever mode sits beside it.

    No version field is needed to make this one-time: it keys on the legacy
    key still being present, and the first save without it (``asdict`` no
    longer has the field) removes it for good. Re-running until then is
    harmless — it is the same fold onto the same value.
    """
    mode = str(data.get("visualization_mode", AppConfig.visualization_mode))
    if not data.get(LEGACY_VIS_SWITCH, True):
        return "off"
    return _renamed_vis_mode(mode)


# Mode ids the menu no longer offers, and what each one becomes.
#
# The four tunnels were named for their *look* — and the look swapped: once the
# beat-locked tunnel's wall became nebula cloud it was plainly the
# wormhole-looking one, so the labels had to trade places. Renaming the ids
# rather than swapping them is what makes this migration safe, and it is the
# same reasoning as :func:`_folded_vis_mode`'s above: it keys on the stored
# value still being a retired name, so it is one-way and **harmless to
# re-run**. A straight swap would have no such trigger — both names are valid
# before and after, so it would need a version counter, and re-running one
# would silently flip the user's setting back.
#
# ``fire`` is a retirement rather than a rename: the popout window no longer
# offers it. It maps to the backdrop that draws the same flames instead of to
# "off", by the same rule the tunnels follow — a stored mode names the picture
# the user picked, and that picture still exists, so hand it back rather than
# taking their visual away without a word.
RETIRED_VIS_MODES = {
    "wormhole": "loop_tunnel",
    "tunnel_chase": "beat_tunnel",
    "backdrop_wormhole": "backdrop_loop_tunnel",
    "backdrop_tunnel_chase": "backdrop_beat_tunnel",
    "fire": "backdrop_fire",
}


def _renamed_vis_mode(mode: str) -> str:
    """The stored visual under a live id, keeping the picture it chose.

    A config written before a rename names the *visual the user picked*, so it
    maps to whichever id renders that same visual today — not to whichever id
    now wears the label it used to have. The menu row they chose has since
    changed its name; the picture behind it has not, and the picture is what
    was chosen. A mode the menu has dropped altogether follows the same rule
    and lands on whatever still draws it.
    """
    return RETIRED_VIS_MODES.get(mode, mode)


# The pipeline's controls before it grew per-step toggles: one flag that meant
# "convert, then analyse, then file into the playlist", and one playlist name.
LEGACY_PIPELINE_ENABLED = "convert_pipeline_enabled"
LEGACY_PIPELINE_PLAYLIST = "convert_pipeline_playlist"


def _folded_pipeline_steps(data: dict) -> tuple[bool, bool, bool]:
    """(rename, convert, analyze) with a pre-toggle pipeline flag folded in.

    The old flag was one switch over two steps, so ON becomes both of them ON —
    that is what it meant. Rename had no flag to inherit and starts off.

    No version field is needed to make this one-time, for the same reason
    _folded_vis_mode needs none: it keys on the old key still being present,
    and each new key wins wherever it exists, so the first save — which writes
    the new fields and not the old one — retires the fold for good. Re-running
    until then is the same fold onto the same value.
    """
    legacy = bool(data.get(LEGACY_PIPELINE_ENABLED, False))
    return (
        bool(data.get("pipeline_rename_enabled", AppConfig.pipeline_rename_enabled)),
        bool(data.get("pipeline_convert_enabled", legacy)),
        bool(data.get("pipeline_analyze_enabled", legacy)),
    )


def _folded_pipeline_playlist(data: dict) -> str:
    """The target playlist's name, from whichever key holds it."""
    return str(
        data.get(
            "pipeline_playlist",
            data.get(LEGACY_PIPELINE_PLAYLIST, AppConfig.pipeline_playlist),
        )
    )


def _optional_int(data: dict, key: str, default: int | None) -> int | None:
    """Read a setting that is either a number or null.

    A missing key falls back to the default; an explicit null stays None
    ("Keep source"), which a bare int() would raise on. A non-numeric value
    falls back rather than propagating a broken config.
    """
    if key not in data:
        return default
    value = data[key]
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_config() -> AppConfig:
    """Load config from disk, returning defaults if missing or corrupt."""
    path = _config_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            step_rename, step_convert, step_analyze = _folded_pipeline_steps(data)
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
                energy_field_enabled=bool(
                    data.get("energy_field_enabled", AppConfig.energy_field_enabled)
                ),
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
                # null in the JSON is "Keep source" and must survive as None,
                # so these can't go through a bare int().
                convert_sample_rate=_optional_int(
                    data, "convert_sample_rate", AppConfig.convert_sample_rate
                ),
                convert_bit_depth=_optional_int(
                    data, "convert_bit_depth", AppConfig.convert_bit_depth
                ),
                convert_output_dir=str(
                    data.get("convert_output_dir", AppConfig.convert_output_dir)
                ),
                convert_use_source_dir=bool(
                    data.get("convert_use_source_dir", AppConfig.convert_use_source_dir)
                ),
                pipeline_rename_enabled=step_rename,
                pipeline_convert_enabled=step_convert,
                pipeline_analyze_enabled=step_analyze,
                pipeline_playlist=_folded_pipeline_playlist(data),
                spectrum_dynamic_range=float(
                    data.get("spectrum_dynamic_range", AppConfig.spectrum_dynamic_range)
                ),
                waveform_color=str(data.get("waveform_color", AppConfig.waveform_color)),
                player_edit_locked=bool(
                    data.get("player_edit_locked", AppConfig.player_edit_locked)
                ),
                visualization_mode=_folded_vis_mode(data),
                export_absolute_paths=bool(
                    data.get("export_absolute_paths", AppConfig.export_absolute_paths)
                ),
                duplicate_policy=str(
                    data.get("duplicate_policy", AppConfig.duplicate_policy)
                ),
                persist_scratch=bool(
                    data.get("persist_scratch", AppConfig.persist_scratch)
                ),
                online_lookup_enabled=bool(
                    data.get("online_lookup_enabled", AppConfig.online_lookup_enabled)
                ),
                discogs_token=str(
                    data.get("discogs_token", AppConfig.discogs_token) or ""
                ).strip(),
                online_fetch_artwork=bool(
                    data.get("online_fetch_artwork", AppConfig.online_fetch_artwork)
                ),
                language=data.get("language", AppConfig.language),
                theme=data.get("theme", AppConfig.theme),
                history_display_limit=int(
                    data.get("history_display_limit", AppConfig.history_display_limit)
                ),
                player_column_state=data.get(
                    "player_column_state", AppConfig.player_column_state
                ),
                player_column_count=_optional_int(
                    data, "player_column_count", AppConfig.player_column_count
                ) or AppConfig.player_column_count,
                player_column_defaults_version=_optional_int(
                    data,
                    "player_column_defaults_version",
                    AppConfig.player_column_defaults_version,
                ) or AppConfig.player_column_defaults_version,
                player_text_size=data.get(
                    "player_text_size", AppConfig.player_text_size
                ),
                player_artwork_view=data.get(
                    "player_artwork_view", AppConfig.player_artwork_view
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
            if cfg.player_text_size not in _VALID_TEXT_SIZES:
                cfg.player_text_size = AppConfig.player_text_size
            if cfg.player_artwork_view not in _VALID_ARTWORK_VIEWS:
                cfg.player_artwork_view = AppConfig.player_artwork_view
            if cfg.energy_tag_format not in _VALID_ENERGY_FORMATS:
                cfg.energy_tag_format = AppConfig.energy_tag_format
            if cfg.energy_tag_mode not in _VALID_ENERGY_MODES:
                cfg.energy_tag_mode = AppConfig.energy_tag_mode
            if cfg.convert_target_format not in {"WAV", "FLAC", "AIFF", "MP3"}:
                cfg.convert_target_format = AppConfig.convert_target_format
            if cfg.convert_mp3_bitrate not in {128, 192, 256, 320}:
                cfg.convert_mp3_bitrate = AppConfig.convert_mp3_bitrate
            # None is valid on both: it is the "Keep source" selection.
            if cfg.convert_sample_rate not in {None, 32000, 44100, 48000, 96000}:
                cfg.convert_sample_rate = AppConfig.convert_sample_rate
            if cfg.convert_bit_depth not in {None, 8, 16, 24, 32}:
                cfg.convert_bit_depth = AppConfig.convert_bit_depth
            # A saved output folder that has been deleted or unmounted since is
            # forgotten, and the mode goes back on with it — the alternative is
            # a panel pointing at somewhere that isn't there and a batch that
            # fails file by file for a reason the row can't explain. Forcing
            # the mode matters as much as clearing the path: an "off" with no
            # folder behind it is a state with no destination at all.
            if cfg.convert_output_dir and not Path(cfg.convert_output_dir).is_dir():
                cfg.convert_output_dir = AppConfig.convert_output_dir
                cfg.convert_use_source_dir = True
            if not cfg.convert_output_dir:
                cfg.convert_use_source_dir = True
            cfg.spectrum_dynamic_range = max(60.0, min(cfg.spectrum_dynamic_range, 150.0))
            if not _HEX_COLOR_RE.match(cfg.waveform_color):
                cfg.waveform_color = AppConfig.waveform_color
            if cfg.visualization_mode not in _VALID_VIS_MODES:
                cfg.visualization_mode = AppConfig.visualization_mode
            if cfg.duplicate_policy not in _VALID_DUPLICATE_POLICIES:
                cfg.duplicate_policy = AppConfig.duplicate_policy
            if cfg.language not in LANGUAGE_CODES:
                cfg.language = AppConfig.language
            valid_themes = _valid_theme_ids()
            if valid_themes is not None and cfg.theme not in valid_themes:
                cfg.theme = AppConfig.theme
            if cfg.history_display_limit not in HISTORY_DISPLAY_LIMITS:
                cfg.history_display_limit = AppConfig.history_display_limit
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
