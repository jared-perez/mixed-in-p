"""Ranking for the Compatible Tracks panel.

The SQL side of the question ("which library rows are in a compatible key,
at a workable tempo") lives on ``Library.compatible_tracks``; everything
here is the pure part — how close a candidate actually is, and in what
order a DJ wants to see them. Kept separate so the ordering can be tested
without a database, and so the panel has one place to read the relation
names it renders.

Three ideas, in the order they break ties:

* **Key relation** — the four codes ``get_compatible_keys`` returns are not
  equally good. The same code is the same key; the relative major/minor
  shares every note; ±1 moves one accidental. Same > relative > adjacent.
* **Tempo relation** — a candidate tagged at half or double the seed's
  tempo mixes perfectly well (64 under 128), so those count, but they rank
  below an honest same-tempo match even when the arithmetic distance is
  smaller. A track with no BPM at all is ranked last rather than dropped:
  the library is full of files nobody has analysed yet.
* **Energy distance** — the tiebreak, and the thing Rekordbox's equivalent
  panel doesn't have. Only meaningful when the seed itself has an energy;
  a candidate missing one sits at the end of its tier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.library.library import Track

# Key relations, best first. Values are stable identifiers, not UI copy —
# the panel translates them at the point it draws them.
KEY_SAME = "same"
KEY_RELATIVE = "relative"
KEY_ADJACENT = "adjacent"

# Tempo relations. "half"/"double" describe the *candidate*: a 64 BPM track
# under a 128 BPM seed is "half".
TEMPO_SAME = "same"
TEMPO_HALF = "half"
TEMPO_DOUBLE = "double"
TEMPO_UNKNOWN = "unknown"

_KEY_ORDER = {KEY_SAME: 0, KEY_RELATIVE: 1, KEY_ADJACENT: 2}
_TEMPO_ORDER = {TEMPO_SAME: 0, TEMPO_HALF: 1, TEMPO_DOUBLE: 1, TEMPO_UNKNOWN: 2}

# ±8% is the DJ-practice default (decided 2026-08-12): roughly the range a
# CDJ's tempo fader covers without the pitch reading as an effect.
DEFAULT_BPM_TOLERANCE = 0.08

# The ranked list is computed whole and then capped — the query is
# milliseconds even at 50k rows, so lazy loading would save nothing.
DEFAULT_LIMIT = 200


@dataclass(frozen=True)
class CompatibleMatch:
    """One row of the Compatible Tracks panel, with why it is there."""

    track: Track
    key_relation: str
    tempo_relation: str
    # Distance in BPM *after* the half/double factor is applied, so a 64 BPM
    # candidate under a 128 BPM seed is 0.0 away, not 64.
    bpm_delta: float | None
    energy_delta: int | None


def key_relation(seed_keycode: str, candidate_keycode: str) -> str | None:
    """How ``candidate_keycode`` relates to ``seed_keycode``, or None.

    None means "not compatible" — including either code being unparseable,
    which is what an empty ``keycode`` column reads as.
    """
    seed = _parse_keycode(seed_keycode)
    candidate = _parse_keycode(candidate_keycode)
    if seed is None or candidate is None:
        return None
    seed_number, seed_letter = seed
    number, letter = candidate
    if letter == seed_letter:
        if number == seed_number:
            return KEY_SAME
        if (number - seed_number) % 12 in (1, 11):
            return KEY_ADJACENT
        return None
    return KEY_RELATIVE if number == seed_number else None


def tempo_relation(
    seed_bpm: float | None,
    candidate_bpm: float | None,
    tolerance: float = DEFAULT_BPM_TOLERANCE,
) -> tuple[str, float | None] | None:
    """``(relation, delta)`` for a candidate tempo, or None if out of range.

    A missing tempo on either side is not a rejection — it is
    ``(TEMPO_UNKNOWN, None)``, which the ranking puts last. Both directions
    of the half/double reading are accepted, and the closest reading wins,
    with a same-tempo match preferred on a tie.
    """
    if not seed_bpm or not candidate_bpm or seed_bpm <= 0 or candidate_bpm <= 0:
        return TEMPO_UNKNOWN, None
    low = seed_bpm * (1.0 - tolerance)
    high = seed_bpm * (1.0 + tolerance)
    best: tuple[str, float] | None = None
    for relation, factor in (
        (TEMPO_SAME, 1.0),
        (TEMPO_HALF, 2.0),
        (TEMPO_DOUBLE, 0.5),
    ):
        effective = candidate_bpm * factor
        if not low <= effective <= high:
            continue
        delta = abs(effective - seed_bpm)
        if best is None or delta < best[1]:
            best = (relation, delta)
    return best


def rank_matches(
    seed: Track,
    candidates: Iterable[Track],
    *,
    bpm_tolerance: float = DEFAULT_BPM_TOLERANCE,
    limit: int | None = DEFAULT_LIMIT,
) -> list[CompatibleMatch]:
    """Score, drop the incompatible, order, and cap.

    Safe to hand the whole table: a candidate that fails either test is
    filtered here, so callers that pre-filter in SQL and callers that don't
    get the same answer.
    """
    matches: list[CompatibleMatch] = []
    for track in candidates:
        if track.id == seed.id:
            continue
        relation = key_relation(seed.keycode, track.keycode)
        if relation is None:
            continue
        tempo = tempo_relation(seed.bpm, track.bpm, bpm_tolerance)
        if tempo is None:
            continue
        matches.append(
            CompatibleMatch(
                track=track,
                key_relation=relation,
                tempo_relation=tempo[0],
                bpm_delta=tempo[1],
                energy_delta=_energy_delta(seed.energy, track.energy),
            )
        )
    matches.sort(key=_sort_key)
    return matches if limit is None else matches[:limit]


def _sort_key(match: CompatibleMatch) -> tuple:
    track = match.track
    return (
        _KEY_ORDER[match.key_relation],
        _TEMPO_ORDER[match.tempo_relation],
        match.bpm_delta if match.bpm_delta is not None else 0.0,
        1 if match.energy_delta is None else 0,
        match.energy_delta if match.energy_delta is not None else 0,
        (track.artist or "").lower(),
        (track.title or track.filename or "").lower(),
        track.id,
    )


def _energy_delta(seed_energy: int | None, candidate_energy: int | None) -> int | None:
    """None when the comparison is meaningless — which is not the same as 0.

    A seed with no energy can't rank anything by energy, so every candidate
    ties; a candidate with no energy under a seed that has one goes last.
    """
    if seed_energy is None or candidate_energy is None:
        return None
    return abs(candidate_energy - seed_energy)


def _parse_keycode(keycode: str) -> tuple[int, str] | None:
    code = (keycode or "").upper().strip()
    if len(code) < 2 or code[-1] not in ("A", "B"):
        return None
    try:
        number = int(code[:-1])
    except ValueError:
        return None
    return (number, code[-1]) if 1 <= number <= 12 else None


def bpm_window(bpm: float, tolerance: float = DEFAULT_BPM_TOLERANCE) -> tuple[float, float]:
    """The (low, high) tempo window a seed accepts, before half/double."""
    return bpm * (1.0 - tolerance), bpm * (1.0 + tolerance)


__all__: Sequence[str] = (
    "CompatibleMatch",
    "DEFAULT_BPM_TOLERANCE",
    "DEFAULT_LIMIT",
    "KEY_ADJACENT",
    "KEY_RELATIVE",
    "KEY_SAME",
    "TEMPO_DOUBLE",
    "TEMPO_HALF",
    "TEMPO_SAME",
    "TEMPO_UNKNOWN",
    "bpm_window",
    "key_relation",
    "rank_matches",
    "tempo_relation",
)
