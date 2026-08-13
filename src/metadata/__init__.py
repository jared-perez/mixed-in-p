"""Metadata handling for audio files.

Provides reading and writing of ID3/audio tags using mutagen.
"""

from .tags import (
    TAGLESS_EXTENSIONS,
    TrackMetadata,
    read_energy,
    read_metadata,
    stores_tags,
    write_metadata,
    update_bpm_key,
    update_comment_with_energy,
    write_energy,
)

__all__ = [
    "TAGLESS_EXTENSIONS",
    "TrackMetadata",
    "read_energy",
    "read_metadata",
    "stores_tags",
    "write_metadata",
    "update_bpm_key",
    "update_comment_with_energy",
    "write_energy",
]
