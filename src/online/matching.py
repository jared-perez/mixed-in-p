"""Normalisation, scoring and filename parsing — all pure functions.

Everything here is deterministic and dependency-free, so the mis-tagging
failure modes that plague this class of tool are testable as golden cases
rather than as "try it and see":

* a version suffix is **signal**, not noise — "(Extended Mix)" and
  "(Radio Edit)" are different records to a DJ, and collapsing them is the
  chronic mis-tag in tools that normalise brackets away. ``feat.`` clauses
  *are* stripped, because those genuinely vary between databases.
* a missing duration is neutral and never a penalty — vinyl-era submissions
  routinely have none, and penalising them would rank every 12" below the CD
  repress of the same record.
* the repress flood (one album, dozens of near-identical releases) collapses
  by ``master_id`` so the candidate list is a list of *records*, not of
  pressings.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .result import Candidate, TrackEntry, TrackQuery

# Below this, a candidate is reported as "no confident match" instead of being
# pre-selected. A wrong pre-selection is worse than no answer: it teaches the
# user to distrust every row the feature produces.
MATCH_FLOOR = 0.55

# How close two durations must be to count as agreeing. Discogs durations are
# per-track "M:SS" transcribed by hand from a sleeve, so they are minute-ish
# accurate at best; the file's own duration includes silence the sleeve never
# counted.
DURATION_TOLERANCE_S = 4.0

# A parenthetical opening with one of these is a credit, not a version — the
# only bracket content stripped before comparison.
_FEAT_RE = re.compile(
    r"[\(\[]\s*(?:feat|feats|featuring|ft|with)\b[^\)\]]*[\)\]]",
    re.IGNORECASE,
)
# The same credit written without brackets, running to the end of the string.
_FEAT_TAIL_RE = re.compile(
    r"\s+(?:feat|feats|featuring|ft)\.?\s+.*$",
    re.IGNORECASE,
)
# Discogs disambiguates same-named artists with a trailing "(2)".
_ARTIST_SUFFIX_RE = re.compile(r"\s*\(\d+\)\s*$")
_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")

# Format words that make a release's duration trustworthy: a digital or CD
# tracklist is transcribed from the medium, a vinyl one from a sleeve.
_RELIABLE_FORMATS = {"cd", "file", "digital", "flac", "mp3", "wav", "cdr"}
_UNOFFICIAL_MARKERS = {"unofficial release", "bootleg", "counterfeit"}

# Weights for score_candidate. They sum to 1.0 over whichever terms actually
# apply; a term with nothing to compare is dropped and the rest renormalised,
# which is what makes a missing value neutral rather than a penalty.
_W_ARTIST = 0.60
_W_ALBUM = 0.25
_W_FORMAT = 0.15

# Weights for score_track, same renormalising rule.
_W_TRACK_TITLE = 0.70
_W_TRACK_ARTIST = 0.15
_W_TRACK_DURATION = 0.15


def strip_artist_suffix(name: str) -> str:
    """Drop Discogs' trailing disambiguation number: "Aphex Twin (2)"."""
    return _ARTIST_SUFFIX_RE.sub("", name).strip()


def normalize(text: str) -> str:
    """Fold a string to its comparable form.

    Case, accents, punctuation and whitespace runs are removed; ``feat.``
    credits go with them. Version suffixes are deliberately left in place —
    see the module docstring.
    """
    if not text:
        return ""
    folded = _FEAT_RE.sub(" ", text)
    folded = _FEAT_TAIL_RE.sub("", folded)
    folded = unicodedata.normalize("NFKD", folded)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.casefold()
    # An ampersand is written three ways across databases; make them one word.
    folded = folded.replace("&", " and ")
    folded = _PUNCT_RE.sub(" ", folded)
    return _SPACE_RE.sub(" ", folded).strip()


def tokens(text: str) -> set[str]:
    """The normalised word set of a string."""
    return set(normalize(text).split())


def similarity(a: str, b: str) -> float:
    """How alike two strings are, 0..1, after normalisation.

    The character ratio alone is too forgiving of word order and too harsh on a
    missing subtitle, so it is averaged with token overlap (Jaccard). Two empty
    strings are 0.0, not 1.0: "we know nothing about either" is not a match,
    and returning 1.0 there would rank every blank field as perfect.
    """
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    overlap = len(ta & tb) / len(ta | tb)
    return (ratio + overlap) / 2


def artist_similarity(a: str, b: str) -> float:
    """Artist comparison, with Discogs' "(2)" suffix removed from both ends."""
    return similarity(strip_artist_suffix(a), strip_artist_suffix(b))


def shares_artist_token(a: str, b: str) -> bool:
    """True if two artist strings have any significant word in common.

    The cheap pre-filter from the plan: a search for one artist regularly
    returns releases by another (Discogs' search is fuzzy), and a result with
    no word in common with ours is never the right record. Short words are
    ignored so "the" and "dj" can't carry a match on their own.
    """
    ta = {t for t in tokens(a) if len(t) > 2}
    tb = {t for t in tokens(b) if len(t) > 2}
    if not ta or not tb:
        # Nothing to disagree with — let the score decide rather than dropping.
        return True
    if "various" in ta or "various" in tb:
        # A compilation's release artist is "Various"; the real artist is on
        # the track entry, which this stage has not read yet.
        return True
    return bool(ta & tb)


def is_unofficial(formats: tuple[str, ...] | list[str]) -> bool:
    """True if a release is a bootleg / unofficial pressing."""
    lowered = {str(f).strip().casefold() for f in formats}
    return bool(lowered & _UNOFFICIAL_MARKERS)


def _format_reliability(formats: tuple[str, ...] | list[str]) -> float:
    """1.0 for a digital/CD release, 0.5 for anything else (i.e. vinyl).

    Not a judgement about audio quality — it is about whether the tracklist's
    durations and track order can be trusted, which is what we score against.
    """
    lowered = {str(f).strip().casefold() for f in formats}
    return 1.0 if lowered & _RELIABLE_FORMATS else 0.5


def _weighted(terms: list[tuple[float, float]]) -> float:
    """Combine (weight, value) pairs, renormalising over the ones present.

    Callers omit a term entirely when there is nothing to compare, so a missing
    value neither helps nor hurts: the score is what it would have been had
    that term scored full marks. That is the "missing duration is neutral,
    never a penalty" rule, expressed once.
    """
    total = sum(w for w, _ in terms)
    if total <= 0:
        return 0.0
    return sum(w * v for w, v in terms) / total


def score_candidate(query: TrackQuery, candidate: Candidate) -> float:
    """Rank a search result, before its tracklist has been read.

    Only what a search response carries is available here: the release artist,
    the release title and the format. The track itself is scored later by
    :func:`score_track`, once the release has been fetched.
    """
    terms: list[tuple[float, float]] = [
        (_W_ARTIST, artist_similarity(query.artist, candidate.artist)),
        (_W_FORMAT, _format_reliability(candidate.formats)),
    ]
    # Only compare albums when the file claims one. An untagged album is not
    # evidence against a release.
    if query.album.strip() and candidate.album:
        terms.append((_W_ALBUM, similarity(query.album, candidate.album)))
    score = _weighted(terms)
    # A release that belongs to a master is a known record rather than an
    # orphan submission; a small nudge, never enough to outrank a better name
    # match.
    if candidate.master_id:
        score = min(1.0, score + 0.03)
    return round(score, 4)


def score_track(
    query: TrackQuery,
    entry: TrackEntry,
    release_artist: str = "",
) -> float:
    """Rank one tracklist row against the file.

    The per-track artist wins over the release artist when it is set — that is
    exactly how compilations are represented, where the release artist is
    "Various" and the real one is on the row.
    """
    terms: list[tuple[float, float]] = [
        (_W_TRACK_TITLE, similarity(query.title, entry.title)),
    ]
    credited = entry.artist or release_artist
    if query.artist.strip() and credited and credited.strip().casefold() != "various":
        terms.append((_W_TRACK_ARTIST, artist_similarity(query.artist, credited)))
    if query.duration and entry.duration:
        delta = abs(query.duration - entry.duration)
        terms.append((_W_TRACK_DURATION, 1.0 if delta <= DURATION_TOLERANCE_S else 0.0))
    return round(_weighted(terms), 4)


def pick_track(
    query: TrackQuery,
    tracklist: list[TrackEntry],
    release_artist: str = "",
) -> tuple[TrackEntry | None, float]:
    """The best row of a tracklist for this file, and its score.

    Returns ``(None, 0.0)`` for an empty tracklist. The caller decides what to
    do with a score below :data:`MATCH_FLOOR`; this function does not silently
    refuse, because the review dialog shows a weak match as a weak match rather
    than as nothing at all.
    """
    best: TrackEntry | None = None
    best_score = 0.0
    for entry in tracklist:
        score = score_track(query, entry, release_artist)
        if score > best_score:
            best, best_score = entry, score
    return best, best_score


def collapse_masters(candidates: list[Candidate]) -> list[Candidate]:
    """Keep one candidate per master, the best-scoring, preserving order.

    Without this, searching for an album that has been repressed twenty times
    gives twenty rows that differ only in a catalogue number. Orphan releases
    (no ``master_id``) are all kept — they have nothing to collapse onto.

    The survivor inherits the **earliest year** seen in its group. Every
    pressing of a record shares an original release year, and the earliest one
    in the results is a free approximation of the master's year, which
    otherwise costs an extra request per file.
    """
    # master_id -> where its survivor sits in `ordered`. A position, not the
    # candidate itself: dataclass equality would make list.index() find some
    # other identical row.
    slot_by_master: dict[int, int] = {}
    ordered: list[Candidate] = []
    for cand in candidates:
        if not cand.master_id:
            ordered.append(cand)
            continue
        slot = slot_by_master.get(cand.master_id)
        if slot is None:
            slot_by_master[cand.master_id] = len(ordered)
            ordered.append(cand)
            continue
        current = ordered[slot]
        earliest = _earliest_year(current.year, cand.year)
        winner = cand if cand.score > current.score else current
        winner.year = earliest
        ordered[slot] = winner
    return ordered


def _earliest_year(a: int | None, b: int | None) -> int | None:
    """The earlier of two years, tolerating either being unknown."""
    years = [y for y in (a, b) if y]
    return min(years) if years else None


def rank_candidates(query: TrackQuery, candidates: list[Candidate]) -> list[Candidate]:
    """Score, filter and order search results — the whole search-side pipeline.

    Drops bootlegs and results sharing no artist word with ours, scores what is
    left, collapses the repress flood, and returns highest first. Scores are
    written onto the candidates, so the caller can show them.
    """
    kept: list[Candidate] = []
    for cand in candidates:
        if is_unofficial(cand.formats):
            continue
        if not shares_artist_token(query.artist, cand.artist):
            continue
        cand.score = score_candidate(query, cand)
        kept.append(cand)
    kept.sort(key=lambda c: c.score, reverse=True)
    return collapse_masters(kept)


# --- Filename fallback ------------------------------------------------------
#
# When a file has no artist/title tags, its name is the only identity we have.
# The shapes below are the app's own rename formats (Settings > File Naming)
# first — "128 8A - Name", "Name - 8A 128" and friends — because a file this
# app renamed is the likeliest one to be missing tags. What is left after
# stripping them is parsed as "Artist - Title".

# A BPM (2-3 digits) or a key, in any of the three notations the app writes,
# optionally bracketed. Key codes are "1A".."12B"; open key is "1d".."12m";
# traditional is a note name with an optional minor "m".
_AFFIX_TOKEN_RE = re.compile(
    r"""^(?:
        \[\s*(?P<sq>[^\]]{1,12})\s*\]     # [128]
      | \(\s*(?P<rd>[^\)]{1,12})\s*\)     # (128)
      | (?P<bare>[^\s\-]{1,12})           # 128
    )$""",
    re.VERBOSE,
)
_BPM_RE = re.compile(r"^\d{2,3}(?:\.\d+)?$")
_KEYCODE_RE = re.compile(r"^(?:[1-9]|1[0-2])[ABab]$")
_OPEN_KEY_RE = re.compile(r"^(?:[1-9]|1[0-2])[dm]$")
_TRADITIONAL_KEY_RE = re.compile(r"^[A-G][#b]?m?$")
# A leading track number: "01", "01." or "1-".
_TRACK_NUMBER_RE = re.compile(r"^\d{1,3}[.\-]?$")


def _is_affix_token(token: str) -> bool:
    """True if a whitespace-separated token is analysis noise, not a name."""
    match = _AFFIX_TOKEN_RE.match(token.strip())
    if not match:
        return False
    value = (match.group("sq") or match.group("rd") or match.group("bare") or "").strip()
    if not value:
        return False
    return bool(
        _BPM_RE.match(value)
        or _KEYCODE_RE.match(value)
        or _OPEN_KEY_RE.match(value)
        or _TRADITIONAL_KEY_RE.match(value)
    )


def _strip_affix(part: str) -> str:
    """Remove leading/trailing BPM and key tokens from one dash-separated part."""
    words = part.split()
    while words and _is_affix_token(words[0]):
        words.pop(0)
    while words and _is_affix_token(words[-1]):
        words.pop()
    if words and _TRACK_NUMBER_RE.match(words[0]) and len(words) > 1:
        words.pop(0)
    return " ".join(words)


def parse_filename(stem: str) -> tuple[str, str]:
    """Best-effort ``(artist, title)`` from a filename stem.

    Returns ``("", "")`` when there is no separator to work with — a bare
    "track01" tells us nothing, and inventing an artist from it would put a
    confident wrong query on the wire.

    Underscores are treated as spaces (the app's own renames preserve whatever
    the source used, and underscore-separated names are endemic to DJ pools).
    """
    text = stem.replace("_", " ").strip()
    if not text:
        return "", ""
    # Split on hyphens that are surrounded by space — a hyphen inside a word
    # ("Hi-Fi", "K-Klass") is part of a name, not a separator.
    parts = [p.strip() for p in re.split(r"\s+-\s+|\s+–\s+", text) if p.strip()]
    if len(parts) < 2:
        return "", ""
    # Drop whole parts that are nothing but analysis affixes ("128 8A").
    parts = [p for p in parts if _strip_affix(p)] or parts
    if len(parts) < 2:
        return "", ""
    artist = _strip_affix(parts[0])
    title = _strip_affix(" - ".join(parts[1:]))
    if not artist or not title:
        return "", ""
    return artist, title


def build_query(
    artist: str | None,
    title: str | None,
    album: str | None = None,
    duration: float | None = None,
    filename_stem: str = "",
) -> TrackQuery:
    """Assemble the query for one file, falling back to its name when untagged.

    The fallback is all-or-nothing per field: a file with an artist tag and no
    title takes only the title from the filename. A parse that finds nothing
    leaves the fields empty, and :meth:`TrackQuery.is_usable` then reports the
    file as un-searchable rather than searching for a filename.
    """
    artist = (artist or "").strip()
    title = (title or "").strip()
    if (not artist or not title) and filename_stem:
        parsed_artist, parsed_title = parse_filename(filename_stem)
        artist = artist or parsed_artist
        title = title or parsed_title
    return TrackQuery(
        artist=artist,
        title=title,
        album=(album or "").strip(),
        duration=duration,
    )
