"""Data types shared by every online metadata provider.

No provider-specific vocabulary lives here: a ``Candidate`` is one release a
provider thinks might be the file, and ``ProposedTags`` is what the review
dialog diffs against the file's current tags. Both are plain dataclasses with
no Qt and no network, so the matching layer and its tests can build them by
hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

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


# A record size, as Discogs writes it: 7", 10", 12", and the occasional 5¼".
# Preferred over the medium name on the switcher's line, because `12"` says
# everything `Vinyl` says and one thing more.
_SIZE_RE = re.compile(r'^\d+(?:[.,]\d+)?\s*["”″]$')

# Format words naming what *kind* of release this is rather than what it is
# made of. Two pressings of one title are told apart by those two things
# together, and by nothing else Discogs flattens in (45 RPM, Stereo, Reissue).
_RELEASE_KINDS = frozenset(
    {
        "album",
        "single",
        "ep",
        "lp",
        "mini-album",
        "maxi-single",
        "compilation",
        "mixtape",
        "sampler",
    }
)


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
    # The track number to write, already read out of `position` by whichever
    # provider built this row. Derived here rather than at the point of use so
    # that re-deriving tags for a *different* row costs no provider knowledge
    # and no second request — reading "A1" or "1-3" is the provider's job, and
    # it has already done it.
    number: int = 0

    def label_line(self) -> str:
        """One-line description for the track picker.

        Untranslated for the same reason :meth:`Candidate.label_line` is:
        every part is data, and the only prose is punctuation. The duration
        earns its place — a remix 12" puts five rows of one title in this
        list, and the running time is often the only thing between them that
        a sleeve actually prints.
        """
        head = self.position.strip() or (str(self.ordinal) if self.ordinal else "")
        parts = [p for p in (head, self.title) if p]
        length = _as_clock(self.duration)
        if length:
            parts.append(length)
        return " — ".join(parts)


def _as_clock(seconds: float | None) -> str:
    """Seconds as "M:SS", or "" for the blanks vinyl-era entries are full of."""
    if not seconds or seconds < 0:
        return ""
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


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
    # Every playable row of the release, in the order and with the filtering
    # `pick_track` ran against — so the dialog's track picker offers exactly
    # the list the automatic choice was made from, and an override needs no
    # second request. Empty until fetch() reads the release.
    tracklist: tuple[TrackEntry, ...] = ()

    def format_line(self) -> str:
        """The pressing in at most two words: what it is, and what kind.

        ``formats`` is ``_flatten_formats``' output — the format name *and*
        every description Discogs hangs off it (``Vinyl, 12", 45 RPM, Single,
        Stereo``). The whole tuple on a one-line label is as unreadable as
        leaving it off, so this takes only the two words that tell two
        pressings of one title apart: the medium (a record size where there is
        one) and the release kind.
        """
        size = medium = kind = ""
        for word in self.formats:
            text = word.strip()
            if not text:
                continue
            if not medium:
                medium = text
            if not size and _SIZE_RE.match(text):
                size = text
            if not kind and text.casefold() in _RELEASE_KINDS:
                kind = text
        return ", ".join(p for p in (size or medium, kind) if p)

    def label_line(self) -> str:
        """One-line description for the candidate switcher.

        Deliberately not translated: every part of it is data (a label name, a
        year, a country, a format code), and the only prose — the separators —
        is punctuation.
        """
        parts = [p for p in (self.album, self.label, self.format_line()) if p]
        tail = [str(p) for p in (self.year, self.country) if p]
        if tail:
            parts.append(" ".join(tail))
        return " — ".join(parts)

    # ------------------------------------------------- the release, storable

    def release_facts(self) -> dict:
        """Everything here that belongs to the *release* rather than to a file.

        What ``score`` and ``track`` say is "how well this release matched
        *that* file", which is a per-file answer and must not be stored against
        a release that another file will read back. ``tracklist`` is the
        release's own and stays.

        A plain dict rather than columns on purpose: this is a cache of an
        external description whose field set is Discogs' to change, and a
        schema migration per field is a bad trade for data nothing queries. A
        reader tolerates keys it does not know and keys that are not there, so
        widening it later costs nothing.
        """
        return {
            "provider": self.provider,
            "release_id": self.release_id,
            "master_id": self.master_id,
            "artist": self.artist,
            "album": self.album,
            "year": self.year,
            "label": self.label,
            "styles": list(self.styles),
            "genres": list(self.genres),
            "formats": list(self.formats),
            "country": self.country,
            "thumb_url": self.thumb_url,
            "cover_url": self.cover_url,
            "page_url": self.page_url,
            "tracklist": [
                {
                    "position": e.position,
                    "title": e.title,
                    "artist": e.artist,
                    "duration": e.duration,
                    "ordinal": e.ordinal,
                    "number": e.number,
                }
                for e in self.tracklist
            ],
        }

    @classmethod
    def from_release_facts(cls, facts: dict) -> "Candidate":
        """Rebuild a candidate from :meth:`release_facts`.

        Every field is read with a default, so a blob written by an older build
        — or a newer one, whose extra keys are simply ignored — still produces
        a usable candidate rather than raising in the middle of a panel load.
        """
        entries = tuple(
            TrackEntry(
                position=str(row.get("position") or ""),
                title=str(row.get("title") or ""),
                artist=str(row.get("artist") or ""),
                duration=row.get("duration"),
                ordinal=int(row.get("ordinal") or 0),
                number=int(row.get("number") or 0),
            )
            for row in facts.get("tracklist") or []
            if isinstance(row, dict)
        )
        return cls(
            provider=str(facts.get("provider") or ""),
            release_id=int(facts.get("release_id") or 0),
            master_id=facts.get("master_id"),
            artist=str(facts.get("artist") or ""),
            album=str(facts.get("album") or ""),
            year=facts.get("year"),
            label=str(facts.get("label") or ""),
            styles=tuple(str(v) for v in facts.get("styles") or ()),
            genres=tuple(str(v) for v in facts.get("genres") or ()),
            formats=tuple(str(v) for v in facts.get("formats") or ()),
            country=str(facts.get("country") or ""),
            thumb_url=str(facts.get("thumb_url") or ""),
            cover_url=str(facts.get("cover_url") or ""),
            page_url=str(facts.get("page_url") or ""),
            tracklist=entries,
        )


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

    def with_track(self, entry: TrackEntry, release_artist: str = ""):
        """A copy of this proposal, read off a different row of the release.

        Only the three fields that belong to a *track* move; album, label,
        genre, year and the URLs belong to the release and are the same
        whichever row the file turns out to be. Nothing here fetches: the row
        already carries its own number, so an override costs no request.

        The artist rule is `fetch`'s, deliberately duplicated rather than
        shared: a compilation credits the track, not "Various", and a release
        with one artist leaves every row's artist blank.
        """
        return replace(
            self,
            title=entry.title or None,
            artist=(entry.artist or release_artist) or None,
            track_number=entry.number or None,
        )

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
