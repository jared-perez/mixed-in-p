"""Data types shared by every online metadata provider.

No provider-specific vocabulary lives here: a ``Candidate`` is one release a
provider thinks might be the file, and ``ProposedTags`` is what the review
dialog diffs against the file's current tags. Both are plain dataclasses with
no Qt and no network, so the matching layer and its tests can build them by
hand.
"""

from __future__ import annotations

from dataclasses import dataclass

# Failure kinds. These are logic values, not UI prose — the human-readable
# (and translated) strings are built in the dialog, the same split
# ``update_worker.STATUS_*`` uses.
ERROR_NO_TOKEN = "no_token"          # feature enabled but no token entered
ERROR_AUTH = "auth"                  # token rejected (401/403)
ERROR_RATE_LIMIT = "rate_limit"      # 429 survived the backoff
ERROR_NETWORK = "network"            # offline, DNS, timeout, TLS
ERROR_SERVER = "server"              # 5xx
ERROR_NOT_FOUND = "not_found"        # 404 on a release we were just given
ERROR_BAD_RESPONSE = "bad_response"  # 200 with JSON we can't read


class LookupFailed(Exception):
    """A lookup that failed in a way the UI has a sentence for.

    ``kind`` is one of the ERROR_* codes above. Named ``LookupFailed`` rather
    than ``LookupError`` on purpose — the latter is a builtin, and shadowing it
    in a module that also catches broad exceptions is a trap waiting to happen.
    """

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(detail or kind)
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True)
class TrackQuery:
    """What we know about the local file, and are willing to send.

    Artist and title are the only fields ever put on the wire; album and
    duration are used locally to rank what comes back. Nothing else about the
    file leaves the machine, and never the audio.
    """

    artist: str = ""
    title: str = ""
    album: str = ""
    duration: float | None = None  # seconds, from the decoded file

    def is_usable(self) -> bool:
        """True if there is enough here to search with.

        A title alone is workable (Discogs' ``track=`` param does the heavy
        lifting); an artist alone is not — it returns that artist's whole
        discography in no useful order.
        """
        return bool(self.title.strip())


@dataclass(frozen=True)
class TrackEntry:
    """One row of a release's tracklist."""

    position: str = ""          # free-form vinyl text: "A1", "B2", "1-3"
    title: str = ""
    artist: str = ""            # per-track artist; set on compilations
    duration: float | None = None  # seconds; often absent on vinyl-era entries
    ordinal: int = 0            # 1-based index within the release


@dataclass
class Candidate:
    """One release a provider offers as a possible match for the file.

    Populated from a *search* response, which carries no tracklist — so
    ``track`` stays None until :meth:`Provider.fetch` reads the release itself.
    ``score`` is filled in by the matching layer, not by the provider.
    """

    provider: str = ""
    release_id: int = 0
    master_id: int | None = None
    artist: str = ""            # release artist ("Various" on compilations)
    album: str = ""             # release title
    year: int | None = None
    label: str = ""
    styles: tuple[str, ...] = ()
    genres: tuple[str, ...] = ()
    formats: tuple[str, ...] = ()   # format names + descriptions, flattened
    country: str = ""
    thumb_url: str = ""
    cover_url: str = ""
    page_url: str = ""          # human-facing release page, for the dialog
    score: float = 0.0
    track: TrackEntry | None = None  # the matched row, after fetch()

    def label_line(self) -> str:
        """One-line description for the candidate switcher.

        Deliberately not translated: every part of it is data (a label name, a
        year, a country, a format code), and the only prose — the separators —
        is punctuation.
        """
        parts = [p for p in (self.album, self.label) if p]
        tail = [str(p) for p in (self.year, self.country) if p]
        if tail:
            parts.append(" ".join(tail))
        return " — ".join(parts)


@dataclass
class ProposedTags:
    """Provider values for one file, ready to diff against its current tags.

    Field names match ``metadata.tags.TrackMetadata`` so the review dialog can
    pair them up without a translation table. Every field is optional: a
    provider that has nothing for one leaves it None, and a None is never
    offered as a change.

    ``artwork_url`` is the *address* of the cover, not the bytes — the image is
    fetched only if the user asks to see or apply it.
    """

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    genre: str | None = None
    year: int | None = None
    track_number: int | None = None
    label: str | None = None
    artwork_url: str = ""
    source_url: str = ""        # the release page, for attribution
    provider: str = ""

    def as_fields(self) -> dict[str, object]:
        """The proposed values by tag-field name, dropping the empty ones."""
        values: dict[str, object] = {
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "genre": self.genre,
            "year": self.year,
            "track_number": self.track_number,
            "label": self.label,
        }
        return {k: v for k, v in values.items() if v not in (None, "")}
