"""Persistent history of recently analyzed tracks.

Keeps the last MAX_ENTRIES analysis results (newest first) in a single JSON
file in the app data directory, so the History panel can show recent key
detections across app restarts. Re-analyzing a file replaces its older entry;
renaming a file (e.g. via the auto-rename pipeline) repoints its entry at the
new path so the history always shows the current filename.

This module has NO heavy dependencies (no librosa/numpy) — safe to import
from GUI code.
"""

from __future__ import annotations

import json
from pathlib import Path

MAX_ENTRIES = 50


def get_history_file() -> Path:
    """Get the analysis history file path, creating the data dir if needed."""
    from src.utils.app_dirs import get_app_data_dir

    data_dir = get_app_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "analysis_history.json"


def load_entries(history_file: Path | None = None) -> list[dict]:
    """Load analysis history entries, newest first.

    Returns an empty list if the file is missing or unreadable — history is
    best-effort and must never break analysis.
    """
    if history_file is None:
        history_file = get_history_file()
    if not history_file.exists():
        return []
    try:
        with open(history_file, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict)][:MAX_ENTRIES]


def add_entry(entry: dict, history_file: Path | None = None) -> None:
    """Prepend an analysis entry, keeping at most MAX_ENTRIES.

    An existing entry for the same file_path is replaced (re-analysis
    refreshes a track's spot rather than duplicating it).
    """
    if history_file is None:
        history_file = get_history_file()
    entries = load_entries(history_file)
    file_path = entry.get("file_path")
    entries = [e for e in entries if e.get("file_path") != file_path]
    entries.insert(0, entry)
    _save(entries, history_file)


def update_paths(
    renames: list[tuple[str, str]], history_file: Path | None = None
) -> None:
    """Repoint history entries at their new paths after files were renamed.

    Args:
        renames: List of (old_path, new_path) tuples
    """
    if not renames:
        return
    if history_file is None:
        history_file = get_history_file()
    entries = load_entries(history_file)
    mapping = dict(renames)
    changed = False
    for entry in entries:
        new_path = mapping.get(entry.get("file_path"))
        if new_path:
            entry["file_path"] = new_path
            changed = True
    if changed:
        _save(entries, history_file)


def _save(entries: list[dict], history_file: Path) -> None:
    with open(history_file, "w") as f:
        json.dump(entries[:MAX_ENTRIES], f, indent=2)
