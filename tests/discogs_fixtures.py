"""Canned Discogs payloads and a fake ``urlopen`` for the online tests.

Not named ``test_*`` on purpose — it is imported by the real test modules, not
collected as one. Every payload here is trimmed to the fields the provider
actually reads, in the shapes the live API returns (verified against
api.discogs.com when the plan was written): a search response carrying the
repress flood plus a bootleg, a release whose tracklist has both an extended
mix and a radio edit, a Various-artists compilation, a vinyl release with the
blank durations that era is full of, and a master.

**No test in this suite touches the network** — same absolutism as the app-data
isolation in ``tests/conftest.py``. The provider takes an injectable opener so
that rule needs no monkeypatching of urllib.
"""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

# --- search -----------------------------------------------------------------

# Four results for "Underworld — Born Slippy": two pressings of one master (the
# repress flood), one bootleg, and one release by an unrelated artist that the
# fuzzy search dragged in.
SEARCH_RESPONSE: dict[str, Any] = {
    "pagination": {"page": 1, "pages": 1, "per_page": 25, "items": 4},
    "results": [
        {
            "id": 1001,
            "master_id": 77,
            "title": "Underworld - Born Slippy",
            "year": "1996",
            "country": "UK",
            "label": ["Junior Boy's Own"],
            "genre": ["Electronic"],
            "style": ["Techno", "Progressive House"],
            "format": ["Vinyl", '12"', "45 RPM"],
            "formats": [
                {"name": "Vinyl", "qty": "1", "descriptions": ['12"', "45 RPM"]}
            ],
            "thumb": "https://img.discogs.com/thumb-1001.jpg",
            "cover_image": "https://img.discogs.com/cover-1001.jpg",
        },
        {
            # Same record, CD repress two years later — collapses onto 1001.
            "id": 1002,
            "master_id": 77,
            "title": "Underworld - Born Slippy",
            "year": "1998",
            "country": "Europe",
            "label": ["Junior Boy's Own"],
            "genre": ["Electronic"],
            "style": ["Techno"],
            "format": ["CD", "Single"],
            "formats": [{"name": "CD", "qty": "1", "descriptions": ["Single"]}],
            "thumb": "https://img.discogs.com/thumb-1002.jpg",
            "cover_image": "https://img.discogs.com/cover-1002.jpg",
        },
        {
            "id": 1003,
            "master_id": 77,
            "title": "Underworld - Born Slippy",
            "year": "2001",
            "country": "Unknown",
            "label": ["Not On Label"],
            "format": ["Vinyl", "Unofficial Release"],
            "formats": [
                {
                    "name": "Vinyl",
                    "qty": "1",
                    "descriptions": ['12"', "Unofficial Release"],
                }
            ],
            "thumb": "",
            "cover_image": "",
        },
        {
            "id": 1004,
            "master_id": 88,
            "title": "Leftfield - Release The Pressure",
            "year": "1995",
            "country": "UK",
            "label": ["Hard Hands"],
            "format": ["CD"],
            "formats": [{"name": "CD", "qty": "1", "descriptions": []}],
            "thumb": "",
            "cover_image": "",
        },
    ],
}

# --- releases ---------------------------------------------------------------

# The everyday case: one artist, several versions of the same track. The
# version suffix is the whole point — an extended mix and a radio edit are
# different records to a DJ.
RELEASE_RESPONSE: dict[str, Any] = {
    "id": 1001,
    "master_id": 77,
    "title": "Born Slippy",
    "year": 1996,
    "country": "UK",
    "uri": "https://www.discogs.com/release/1001",
    "artists": [{"name": "Underworld", "join": ""}],
    "labels": [{"name": "Junior Boy's Own (2)", "catno": "JBO 44"}],
    "genres": ["Electronic"],
    "styles": ["Techno", "Progressive House", "Breaks"],
    "formats": [{"name": "Vinyl", "qty": "1", "descriptions": ['12"', "45 RPM"]}],
    "images": [
        {
            "type": "secondary",
            "uri": "https://img.discogs.com/back-1001.jpg",
            "resource_url": "https://img.discogs.com/back-1001.jpg",
        },
        {
            "type": "primary",
            "uri": "https://img.discogs.com/front-1001.jpg",
            "resource_url": "https://img.discogs.com/front-1001.jpg",
        },
    ],
    "released": "1996-05-13",
    "notes": "Comes in a printed inner sleeve.",
    "extraartists": [
        {"name": "Rick Smith (2)", "role": "Producer"},
        {"name": "Underworld", "role": "Written-By"},
        # No role: "somebody was involved" is not a credit, and this row is
        # here to be dropped.
        {"name": "Nobody In Particular", "role": ""},
    ],
    "identifiers": [
        {"type": "Barcode", "value": "5 016553 004417"},
        {"type": "Matrix / Runout", "value": "JBO 44 A1", "description": "Side A"},
        {"type": "Matrix / Runout", "value": "JBO 44 B1", "description": "Side B"},
        # Free-form types are allowed and a busy release carries a dozen; this
        # one is here to prove the filter is a filter.
        {"type": "Rights Society", "value": "MCPS"},
    ],
    "community": {"have": 4100, "want": 584, "rating": {"count": 240, "average": 3.86}},
    "tracklist": [
        {"type_": "heading", "position": "", "title": "Side A", "duration": ""},
        {
            "type_": "track",
            "position": "A1",
            "title": "Born Slippy (Nuxx) (Extended Mix)",
            "duration": "9:44",
        },
        {
            "type_": "track",
            "position": "B1",
            "title": "Born Slippy (Nuxx) (Radio Edit)",
            "duration": "4:02",
            # Per-track credits are the DJ-relevant ones: a remix 12" credits
            # a different person on every side.
            "extraartists": [{"name": "Darren Price", "role": "Remix"}],
        },
    ],
}

# A compilation: the release artist is "Various" and the real one is on the
# row. This is the shape that breaks tools which read only the release artist.
VA_RELEASE_RESPONSE: dict[str, Any] = {
    "id": 2001,
    "master_id": 0,
    "title": "Renaissance: The Mix Collection",
    "year": 1994,
    "uri": "https://www.discogs.com/release/2001",
    "artists": [{"name": "Various", "join": ""}],
    "labels": [{"name": "Renaissance", "catno": "REN CD1"}],
    "genres": ["Electronic"],
    "styles": ["Progressive House", "Trance"],
    "formats": [{"name": "CD", "qty": "2", "descriptions": ["Compilation", "Mixed"]}],
    "images": [],
    "tracklist": [
        {
            "type_": "track",
            "position": "1-1",
            "title": "Sunrise",
            "duration": "6:12",
            "artists": [{"name": "M People", "join": ""}],
        },
        {
            "type_": "track",
            "position": "1-2",
            "title": "Papua New Guinea",
            "duration": "7:30",
            "artists": [{"name": "The Future Sound Of London (2)", "join": ""}],
        },
    ],
}

# Vinyl-era submission: no durations at all, which must be neutral rather than
# a reason to rank this below a CD repress.
VINYL_RELEASE_RESPONSE: dict[str, Any] = {
    "id": 3001,
    "master_id": 0,
    "title": "Acid Trax",
    "year": 1987,
    "uri": "https://www.discogs.com/release/3001",
    "artists": [{"name": "Phuture", "join": ""}],
    "labels": [{"name": "Trax Records", "catno": "TX 142"}],
    "genres": ["Electronic"],
    "styles": ["Acid House"],
    "formats": [{"name": "Vinyl", "qty": "1", "descriptions": ['12"']}],
    "images": [],
    "tracklist": [
        {"type_": "track", "position": "A", "title": "Acid Tracks", "duration": ""},
        {"type_": "track", "position": "B1", "title": "Your Only Friend", "duration": ""},
    ],
}

MASTER_RESPONSE: dict[str, Any] = {
    "id": 77,
    "title": "Born Slippy",
    "year": 1995,  # earlier than every pressing above — the point of asking
    "main_release": 1001,
}


class FakeResponse:
    """Minimal stand-in for what ``urlopen`` returns: a context manager."""

    def __init__(self, payload: Any, headers: dict[str, str] | None = None) -> None:
        self._body = (
            payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        )
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def http_error(code: int, url: str = "https://api.discogs.com/x") -> urllib.error.HTTPError:
    """An HTTPError shaped like the ones urllib raises."""
    return urllib.error.HTTPError(url, code, "boom", {}, io.BytesIO(b""))


class FakeOpener:
    """Routes requests to canned payloads by URL substring, and records them.

    ``routes`` maps a substring of the URL to either a payload (dict/bytes) or
    an exception to raise. A list value is consumed one entry per call, which
    is how a 429-then-success retry is expressed.
    """

    def __init__(
        self,
        routes: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.routes = routes or {}
        self.headers = headers or {}
        self.requests: list[Any] = []

    @property
    def urls(self) -> list[str]:
        return [r.full_url for r in self.requests]

    def __call__(self, request: Any, timeout: float | None = None) -> FakeResponse:
        self.requests.append(request)
        url = request.full_url
        for fragment, value in self.routes.items():
            if fragment not in url:
                continue
            if isinstance(value, list):
                value = value.pop(0) if value else {}
            if isinstance(value, BaseException):
                raise value
            return FakeResponse(value, dict(self.headers))
        raise AssertionError(f"unexpected request to {url}")
