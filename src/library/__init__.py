"""Playlist library — SQLite-backed track/playlist persistence.

User-facing name is "Playlists"; "library" is the internal name for the
data layer (tracks table + playlist tree + search).
"""

from src.library.library import (
    SCRATCH_NODE_ID,
    Library,
    Node,
    Track,
    compute_content_id,
    default_db_path,
    update_paths,
)

__all__ = [
    "SCRATCH_NODE_ID",
    "Library",
    "Node",
    "Track",
    "compute_content_id",
    "default_db_path",
    "update_paths",
]
