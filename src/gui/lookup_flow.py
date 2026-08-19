"""Shared pieces of the online-lookup flow, used by both panels that offer it.

The Metadata panel looks up one file; the Player playlist looks up a selection.
They differ in how they *gather* files and how they report progress, and in
nothing else — the failure sentences, the tag write and the query construction
are the same work, and duplicating them is how two surfaces drift into
disagreeing about what a rate limit is called.

Strings here use ``QCoreApplication.translate`` rather than ``self.tr``: there
is no widget instance to hang them on, and the context name is fixed so the
same sentence is translated once for both callers.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from src.metadata.tags import TrackMetadata, read_metadata, write_metadata
from src.online import matching
from src.online.result import (
    ERROR_AUTH,
    ERROR_NETWORK,
    ERROR_NOT_FOUND,
    ERROR_NO_TOKEN,
    ERROR_RATE_LIMIT,
    ERROR_SERVER,
    TrackQuery,
)

logger = logging.getLogger(__name__)

# NB: every translate() call below spells this context out as a literal.
# lupdate parses the source text — it cannot resolve a variable — so passing a
# module constant here extracts nothing at all, and the sentences would fall
# back to English in every language with no warning that they had.

# Key the review dialog uses for approved cover bytes. Plain '#', not
# '#:' — lupdate harvests the latter as a note to translators and staples it
# onto the next translatable string, which here is an error sentence.
ARTWORK_FIELD = "artwork"


def error_text(kind: str) -> str:
    """One sentence per failure kind — no codes, no stack traces.

    Every branch ends in something the user can *do*, because "it didn't work"
    with no next step is what makes people abandon a feature rather than fix
    their token.
    """
    if kind == ERROR_NO_TOKEN:
        return QCoreApplication.translate(
            "LookupFlow", "Add your Discogs token in Settings to look up track details."
        )
    if kind == ERROR_AUTH:
        return QCoreApplication.translate(
            "LookupFlow",
            "Discogs rejected that token. Check it in Settings, or generate a new one.",
        )
    if kind == ERROR_RATE_LIMIT:
        return QCoreApplication.translate(
            "LookupFlow",
            "Discogs is rate limiting this connection. Wait a minute and try again.",
        )
    if kind == ERROR_NOT_FOUND:
        return QCoreApplication.translate(
            "LookupFlow",
            "Nothing on Discogs matched this track. Editing the Artist and Title "
            "fields and trying again usually helps.",
        )
    if kind == ERROR_SERVER:
        return QCoreApplication.translate(
            "LookupFlow", "Discogs is having trouble right now. Try again later."
        )
    if kind == ERROR_NETWORK:
        return QCoreApplication.translate(
            "LookupFlow", "Couldn't reach Discogs. Check your internet connection."
        )
    return QCoreApplication.translate(
        "LookupFlow", "Couldn't read Discogs' answer. Try again later."
    )


def query_for(
    file_path: str,
    artist: str | None = None,
    title: str | None = None,
    album: str | None = None,
    duration: float | None = None,
    read_tags: bool = False,
) -> TrackQuery:
    """Build the search query for one file.

    ``read_tags`` re-reads the file when the caller has no values to hand (the
    playlist has them already; the Metadata panel's form is the fresher
    source). Either way the filename is the fallback, so a file with no tags at
    all is still searchable — which is the case that most needs looking up.
    """
    if read_tags and not (artist and title):
        try:
            meta = read_metadata(file_path)
            artist = artist or meta.artist
            title = title or meta.title
            album = album or meta.album
            duration = duration if duration is not None else meta.duration
        except Exception as exc:  # noqa: BLE001 — an unreadable file still searches
            logger.debug("Could not read tags for %s: %s", file_path, exc)
    return matching.build_query(
        artist=artist,
        title=title,
        album=album,
        duration=duration,
        filename_stem=Path(file_path).stem,
    )


def sniff_mime(data: bytes) -> str:
    """The MIME type of downloaded cover bytes, read from the bytes themselves.

    There is no filename to go on — a Discogs image URL is a signed, expiring
    address — and writing "image/jpeg" over a PNG produces art some players
    refuse to draw.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


def apply_values(file_path: str, values: dict) -> str:
    """Write approved values to a file. Returns "" on success, else a sentence.

    Goes through the same ``tags.py`` calls a manual edit makes, deliberately:
    the Windows file-lock retry rules and the WAV guard then apply for free,
    and every panel that watches those files learns about the change the way it
    already does.
    """
    if not values:
        return ""
    values = dict(values)
    artwork = values.pop(ARTWORK_FIELD, None)
    meta = TrackMetadata()
    fields: list[str] = []
    for key, value in values.items():
        setattr(meta, key, value)
        fields.append(key)
    try:
        if fields:
            write_metadata(file_path, meta, fields)
        if artwork:
            write_metadata(
                file_path,
                TrackMetadata(artwork=bytes(artwork), artwork_mime=sniff_mime(artwork)),
                fields=[ARTWORK_FIELD],
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to apply looked-up metadata to %s: %s", file_path, exc)
        return QCoreApplication.translate(
            "LookupFlow", "Couldn't write these tags: {0}"
        ).format(exc)
    logger.info(
        "Applied %d online field(s) to %s",
        len(fields) + (1 if artwork else 0),
        Path(file_path).name,
    )
    return ""
