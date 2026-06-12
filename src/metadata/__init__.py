"""Metadata handling for audio files.

Provides reading and writing of ID3/audio tags using mutagen.
"""

from .tags import (
    TrackMetadata,
    read_metadata,
    write_metadata,
    update_bpm_key,
    update_comment_with_energy,
)

__all__ = [
    "TrackMetadata",
    "read_metadata",
    "write_metadata",
    "update_bpm_key",
    "update_comment_with_energy",
]
