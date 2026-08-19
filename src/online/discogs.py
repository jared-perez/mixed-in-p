"""Discogs provider — stdlib HTTP, personal token, live rate pacing.

No new dependency: a token in a header and JSON out is urllib territory, the
same posture ``gui/workers/update_worker.py`` already takes (and the reason
``QtNetwork`` stays out of the bundle). ``python3-discogs-client`` exists and
is alive, but would buy nothing here.

Three things about the API that shape this file:

* **The User-Agent is mandatory and must be distinctive.** urllib's default
  ``Python-urllib/3.x`` is precisely the one Discogs blocks.
* **The rate limit is 60/min authenticated on a moving 60-second window**, and
  going over returns 429 with *no* ``Retry-After``. Every response carries the
  live counters, so the pacer reads those rather than hardcoding 60 — if
  Discogs changes the number, this follows it.
* **Freshness rule: fetched content must not be cached longer than needed.**
  So there is no results cache here. Fetch, show, the user applies, the values
  become their own tags (the core data is CC0, which makes that clean), and
  the payload is discarded. The only memo is per-lookup and dies with it.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from src import __version__

from . import matching
from .result import (
    ERROR_AUTH,
    ERROR_BAD_RESPONSE,
    ERROR_NETWORK,
    ERROR_NO_TOKEN,
    ERROR_NOT_FOUND,
    ERROR_RATE_LIMIT,
    ERROR_SERVER,
    Candidate,
    LookupFailed,
    ProposedTags,
    TrackEntry,
    TrackQuery,
)

logger = logging.getLogger(__name__)

API_ROOT = "https://api.discogs.com"
RELEASE_PAGE = "https://www.discogs.com/release/{id}"
# Where the user generates the personal access token the feature needs.
TOKEN_PAGE_URL = "https://www.discogs.com/settings/developers"

PROVIDER_NAME = "discogs"
DISPLAY_NAME = "Discogs"
# Shown in the review dialog and the About box. Established practice for
# CC0 core data; kept as one string so both surfaces credit it identically.
ATTRIBUTION = "Data courtesy of Discogs"

# Distinctive, versioned, with a contact address — what the ToS asks for.
USER_AGENT = f"MixedInP/{__version__} +https://jared-perez.github.io/mixed-in-p/"

REQUEST_TIMEOUT_S = 15.0
# How long to wait out a 429 before retrying, and how many times. The window is
# rolling, so slots free up continuously and a short wait usually suffices;
# three of these is 15 seconds, after which the file is reported as rate
# limited rather than left spinning.
RETRY_WAIT_S = 5.0
MAX_RETRIES = 3
# Pace pre-emptively once the live counter says this few requests are left in
# the window, so a batch slows down instead of walking into a 429.
PACE_THRESHOLD = 2
PACE_WAIT_S = 2.0

# Search results per page. The dialog shows a handful of candidates and the
# repress flood collapses by master, so asking for more only spends quota.
DEFAULT_SEARCH_LIMIT = 25


def _duration_seconds(text: str) -> float | None:
    """Parse Discogs' "M:SS" (or "H:MM:SS") duration. Blank is common."""
    parts = (text or "").strip().split(":")
    if not parts or not all(p.strip().isdigit() for p in parts):
        return None
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds or None


def _track_number(position: str, ordinal: int) -> int:
    """The track number to write, from free-form vinyl position text.

    "5" is a track number; "A1" is a side and a groove, and "1-3" is disc 1
    track 3 — for anything that isn't a plain number, the count within the
    release is the honest answer.
    """
    text = (position or "").strip()
    if text.isdigit():
        return int(text)
    if "-" in text:
        tail = text.rsplit("-", 1)[1].strip()
        if tail.isdigit():
            return int(tail)
    return ordinal


def _flatten_formats(payload: dict[str, Any]) -> tuple[str, ...]:
    """Every format word on a release, names and descriptions together.

    Search results carry a flat ``format`` list; a release carries
    ``formats: [{name, descriptions}]`` — both spellings appear, so both are
    read. The result feeds the unofficial-release filter and the
    duration-reliability term, neither of which cares which key it came from.
    """
    words: list[str] = []
    for item in payload.get("format") or []:
        if isinstance(item, str):
            words.append(item)
    for entry in payload.get("formats") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if isinstance(name, str):
            words.append(name)
        for desc in entry.get("descriptions") or []:
            if isinstance(desc, str):
                words.append(desc)
    return tuple(words)


def _split_search_title(text: str) -> tuple[str, str]:
    """Search results spell the title "Artist - Album"; split it back apart."""
    if " - " in text:
        artist, album = text.split(" - ", 1)
        return artist.strip(), album.strip()
    return "", text.strip()


def _join_artists(entries: list[Any]) -> str:
    """Join a Discogs artist array, honouring its per-entry join words.

    ``[{name: "A", join: "&"}, {name: "B"}]`` is the record's own idea of how
    the credit reads, and for a DJ that is part of the identity ("A & B" is a
    different act from "A"). Falls back to ", " where no join word is given.
    """
    parts: list[str] = []
    for index, entry in enumerate(entries or []):
        if not isinstance(entry, dict):
            continue
        name = matching.strip_artist_suffix(str(entry.get("name") or "").strip())
        if not name:
            continue
        if parts:
            join = str(entries[index - 1].get("join") or "").strip()
            parts.append(f" {join} " if join and join != "," else ", ")
        parts.append(name)
    return "".join(parts).strip()


class DiscogsProvider:
    """Search and read Discogs releases with a user's personal token.

    ``opener`` and ``sleeper`` are injected so the whole class is testable on
    canned JSON with no network and no wall-clock waiting — the suite's rule
    that no test ever touches the network is absolute, and a rate-limit test
    that really slept for five seconds would be its own problem.

    ``on_wait`` is called with a number of seconds whenever the provider is
    about to pace itself, so the UI can say "waiting for rate limit" honestly
    instead of showing a stuck spinner.
    """

    name = PROVIDER_NAME
    display_name = DISPLAY_NAME

    def __init__(
        self,
        token: str = "",
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
        on_wait: Callable[[float], None] | None = None,
        prefer_master_year: bool = True,
    ) -> None:
        self.token = (token or "").strip()
        self._opener = opener or urllib.request.urlopen
        self._sleep = sleeper or time.sleep
        # Public: the worker thread re-points this at a Qt signal so the panel
        # can say *why* it paused. A private name would make that reach in.
        self.on_wait = on_wait
        self.prefer_master_year = prefer_master_year
        # Live counters from the last response's headers; None until the first
        # one lands. Never hardcoded — Discogs is free to change the numbers.
        self.rate_limit: int | None = None
        self.rate_remaining: int | None = None

    # --- plumbing ----------------------------------------------------------

    def is_configured(self) -> bool:
        """True once a token is present.

        Without one the API allows 25 req/min and returns *blank image fields*,
        so the feature would half-work silently. The UI says so rather than
        letting the user discover it one missing cover at a time.
        """
        return bool(self.token)

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.discogs.v2.discogs+json",
        }
        if self.token:
            headers["Authorization"] = f"Discogs token={self.token}"
        return headers

    def _note_rate_headers(self, response: Any) -> None:
        """Record the live rate-limit counters from a response."""
        headers = getattr(response, "headers", None)
        if headers is None:
            return
        getter = getattr(headers, "get", None)
        if getter is None:
            return
        self.rate_limit = _as_int(getter("x-discogs-ratelimit"))
        self.rate_remaining = _as_int(getter("x-discogs-ratelimit-remaining"))

    def _pace(self) -> None:
        """Wait before a request if the window is nearly spent."""
        if self.rate_remaining is None or self.rate_remaining > PACE_THRESHOLD:
            return
        self._wait(PACE_WAIT_S)

    def _wait(self, seconds: float) -> None:
        if self.on_wait:
            self.on_wait(seconds)
        self._sleep(seconds)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """One GET, with pacing, 429 backoff and errors mapped to ERROR_*."""
        if not self.is_configured():
            raise LookupFailed(ERROR_NO_TOKEN)
        url = API_ROOT + path
        if params:
            query = {k: v for k, v in params.items() if v not in (None, "")}
            url = f"{url}?{urllib.parse.urlencode(query)}"

        attempt = 0
        while True:
            self._pace()
            request = urllib.request.Request(url, headers=self._headers())
            try:
                with self._opener(request, timeout=REQUEST_TIMEOUT_S) as response:
                    self._note_rate_headers(response)
                    raw = response.read()
            except urllib.error.HTTPError as exc:
                self._note_rate_headers(exc)
                attempt += 1
                if exc.code == 429 and attempt < MAX_RETRIES:
                    # No Retry-After on this API — wait out a slice of the
                    # moving window and try again.
                    self._wait(RETRY_WAIT_S)
                    continue
                raise LookupFailed(_http_error_kind(exc.code), str(exc)) from exc
            except urllib.error.URLError as exc:
                raise LookupFailed(ERROR_NETWORK, str(exc)) from exc
            except LookupFailed:
                raise
            except Exception as exc:  # timeout, TLS, socket — all "no network"
                raise LookupFailed(ERROR_NETWORK, str(exc)) from exc

            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                raise LookupFailed(ERROR_BAD_RESPONSE, str(exc)) from exc
            if not isinstance(payload, dict):
                raise LookupFailed(ERROR_BAD_RESPONSE, "expected a JSON object")
            return payload

    # --- the two provider calls -------------------------------------------

    def search(
        self, query: TrackQuery, limit: int = DEFAULT_SEARCH_LIMIT
    ) -> list[Candidate]:
        """Candidate releases for one file, ranked best first.

        One request. The ranking (bootleg filter, artist pre-filter, scoring,
        repress collapse) is :func:`matching.rank_candidates` — pure, and
        tested on its own.
        """
        if not query.is_usable():
            return []
        payload = self._get(
            "/database/search",
            {
                "artist": query.artist or None,
                "track": query.title,
                "type": "release",
                "per_page": max(1, min(int(limit), 100)),
            },
        )
        results = payload.get("results")
        if not isinstance(results, list):
            raise LookupFailed(ERROR_BAD_RESPONSE, "search response had no results")
        candidates = [
            self._candidate_from_search(entry)
            for entry in results
            if isinstance(entry, dict)
        ]
        return matching.rank_candidates(query, candidates)

    def _candidate_from_search(self, entry: dict[str, Any]) -> Candidate:
        artist, album = _split_search_title(str(entry.get("title") or ""))
        labels = entry.get("label") or []
        return Candidate(
            provider=PROVIDER_NAME,
            release_id=_as_int(entry.get("id")) or 0,
            master_id=_as_int(entry.get("master_id")),
            artist=matching.strip_artist_suffix(artist),
            album=album,
            year=_as_int(entry.get("year")),
            label=str(labels[0]) if labels else "",
            styles=tuple(str(s) for s in entry.get("style") or []),
            genres=tuple(str(g) for g in entry.get("genre") or []),
            formats=_flatten_formats(entry),
            country=str(entry.get("country") or ""),
            thumb_url=str(entry.get("thumb") or ""),
            cover_url=str(entry.get("cover_image") or ""),
            page_url=RELEASE_PAGE.format(id=_as_int(entry.get("id")) or 0),
        )

    def fetch(self, candidate: Candidate, query: TrackQuery) -> ProposedTags:
        """Read the chosen release and propose tag values for the file.

        One request, plus one more for the master when the release has one and
        ``prefer_master_year`` is on — DJs want the year the record came out,
        not the year this pressing did. That extra call is best-effort: if it
        fails, the pressing year stands rather than the whole lookup failing.
        """
        payload = self._get(f"/releases/{candidate.release_id}")
        release_artist = _join_artists(payload.get("artists") or [])
        tracklist = self._tracklist(payload)
        entry, score = matching.pick_track(query, tracklist, release_artist)

        candidate.track = entry
        candidate.score = score
        if release_artist:
            candidate.artist = release_artist
        album = str(payload.get("title") or candidate.album)
        styles = tuple(str(s) for s in payload.get("styles") or []) or candidate.styles
        genres = tuple(str(g) for g in payload.get("genres") or []) or candidate.genres
        labels = payload.get("labels") or []
        label = ""
        if labels and isinstance(labels[0], dict):
            label = matching.strip_artist_suffix(str(labels[0].get("name") or ""))

        year = _as_int(payload.get("year")) or candidate.year
        master_id = _as_int(payload.get("master_id")) or candidate.master_id
        if self.prefer_master_year and master_id:
            year = self._master_year(master_id) or year

        artist = ""
        if entry and entry.artist:
            artist = entry.artist  # a compilation credits the track, not "Various"
        elif release_artist:
            artist = release_artist

        return ProposedTags(
            title=entry.title if entry else None,
            artist=artist or None,
            album=album or None,
            genre=_genre_from(styles, genres) or None,
            year=year,
            track_number=(
                _track_number(entry.position, entry.ordinal) if entry else None
            ),
            label=label or None,
            artwork_url=_primary_image(payload) or candidate.cover_url,
            source_url=str(payload.get("uri") or candidate.page_url),
            provider=PROVIDER_NAME,
        )

    def _tracklist(self, payload: dict[str, Any]) -> list[TrackEntry]:
        """The release's playable rows, as TrackEntry.

        Headings and index tracks (``type_`` other than "track") are skipped —
        they carry a title and no audio, and would otherwise win a title match
        against the section they name.
        """
        entries: list[TrackEntry] = []
        ordinal = 0
        for row in payload.get("tracklist") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("type_") or "track").strip().casefold() != "track":
                continue
            ordinal += 1
            entries.append(
                TrackEntry(
                    position=str(row.get("position") or ""),
                    title=str(row.get("title") or ""),
                    artist=_join_artists(row.get("artists") or []),
                    duration=_duration_seconds(str(row.get("duration") or "")),
                    ordinal=ordinal,
                )
            )
        return entries

    def _master_year(self, master_id: int) -> int | None:
        """The original release year, or None if the master can't be read."""
        try:
            payload = self._get(f"/masters/{master_id}")
        except LookupFailed as exc:
            logger.debug("Master %s unavailable (%s); keeping pressing year",
                         master_id, exc.kind)
            return None
        return _as_int(payload.get("year"))

    def fetch_artwork(self, url: str) -> bytes:
        """Download a cover image.

        Separate from :meth:`fetch` because the address is cheap and the image
        is not: nothing downloads a cover until the dialog shows it or the user
        applies it. Discogs' image URLs are time-limited and signed, which is
        another reason they are never stored.
        """
        if not url:
            return b""
        request = urllib.request.Request(url, headers=self._headers())
        try:
            with self._opener(request, timeout=REQUEST_TIMEOUT_S) as response:
                self._note_rate_headers(response)
                return response.read()
        except urllib.error.HTTPError as exc:
            raise LookupFailed(_http_error_kind(exc.code), str(exc)) from exc
        except Exception as exc:
            raise LookupFailed(ERROR_NETWORK, str(exc)) from exc


def _genre_from(styles: tuple[str, ...], genres: tuple[str, ...]) -> str:
    """The genre tag value: styles first, joined.

    ``genres`` on Discogs is coarse ("Electronic") and ``styles`` is the DJ
    taxonomy ("Techno", "Deep House") — writing the former is a known
    complaint about tools that do. Genres are used only when a release has no
    styles at all, which beats writing nothing.
    """
    chosen = styles[:2] if styles else genres[:1]
    return "; ".join(s for s in chosen if s)


def _primary_image(payload: dict[str, Any]) -> str:
    """The release's primary image URL, falling back to the first one."""
    images = payload.get("images") or []
    best = ""
    for image in images:
        if not isinstance(image, dict):
            continue
        url = str(image.get("uri") or image.get("resource_url") or "")
        if not url:
            continue
        if str(image.get("type") or "").casefold() == "primary":
            return url
        best = best or url
    return best


def _http_error_kind(code: int) -> str:
    if code in (401, 403):
        return ERROR_AUTH
    if code == 404:
        return ERROR_NOT_FOUND
    if code == 429:
        return ERROR_RATE_LIMIT
    if code >= 500:
        return ERROR_SERVER
    return ERROR_BAD_RESPONSE


def _as_int(value: Any) -> int | None:
    """Int or None, tolerating the strings and zeros the API mixes in.

    Discogs writes an unknown year as ``0`` and sometimes as ``"0"``; both mean
    "no year", and a 0 written into a year tag is worse than a blank one.
    """
    if value in (None, "", 0, "0"):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
