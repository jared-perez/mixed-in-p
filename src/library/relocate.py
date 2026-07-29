"""Missing-file relocate: find where files went, and re-point library rows.

Qt-free and free of app state, like ``playlist_export`` — the matching is
the part worth unit-testing, and the dialog is just a face on it.

The design comes from §1 of the plan doc. A file that moves *inside* the
app never reaches here (the rename hook updates the row); this is for the
file the user moved in Finder, on a drive that got reorganised, or on a
USB stick that came back mounted somewhere else.

Two matchers, in order:

* **content** — stored ``size`` + ``content_id`` (blake2b of the first
  64 KB). Cheap because size is checked first from ``stat``, and the hash
  is only computed for candidates whose size some missing track wants.
  This is what makes "one dialog fixes a whole moved folder" work.
* **filename** — same name stem, case-insensitive, and only when exactly
  one unclaimed candidate carries that stem. Covers the file that was
  re-encoded rather than moved (new bytes, so the fingerprint can't
  match), while the uniqueness rule keeps a folder full of same-named
  files from producing confident nonsense.

A candidate file is claimed by at most one track, so two library rows that
point at identical copies never both relink onto the one surviving file.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .library import Library, Track, compute_content_id

logger = logging.getLogger(__name__)

# Extensions a folder scan considers. Kept local rather than imported from
# the GUI's drop_zone so this module stays Qt-free.
AUDIO_EXTENSIONS = {".wav", ".flac", ".aiff", ".aif", ".aifc", ".mp3", ".m4a", ".ogg"}

# How a track was matched to its new file.
BY_CONTENT = "content"
BY_FILENAME = "filename"


@dataclass(frozen=True)
class RelocateMatch:
    """One missing track and the file the scan believes it is now."""

    track: Track
    new_path: str
    matched_by: str


@dataclass(frozen=True)
class RelocateResult:
    """Outcome of a folder scan."""

    matches: list[RelocateMatch]
    unmatched: list[Track]
    scanned: int

    @property
    def matched_count(self) -> int:
        return len(self.matches)


def missing_tracks(
    library: Library, tracks: Iterable[Track] | None = None
) -> list[Track]:
    """Library rows whose file is not on disk right now.

    Pass *tracks* to test a subset; the default checks the whole library.
    An unmounted volume legitimately reports all of its tracks missing —
    that is the case the relocate flow exists for.
    """
    rows = library.all_tracks() if tracks is None else list(tracks)
    return [t for t in rows if not Path(t.path).is_file()]


def scan_folder(
    folder: str | Path,
    *,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[Path]:
    """Every audio file under *folder*, recursively and in a stable order.

    Hidden directories are pruned: ``.Trashes``, ``.Spotlight-V100`` and
    friends sit on exactly the external drives this flow is aimed at.
    """
    found: list[Path] = []
    for root, dirs, files in os.walk(folder):
        if is_cancelled is not None and is_cancelled():
            break
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if Path(name).suffix.lower() in AUDIO_EXTENSIONS:
                found.append(Path(root) / name)
    return found


def find_matches(
    missing: Sequence[Track],
    folder: str | Path,
    *,
    on_progress: Callable[[int, int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> RelocateResult:
    """Scan *folder* for the files behind *missing*, without touching the DB.

    Returns matches for the caller to apply (or discard, on cancel).
    """
    candidates = scan_folder(folder, is_cancelled=is_cancelled)
    total = len(candidates)

    # size → the missing tracks that would accept a file of that size. The
    # size check is a stat; the hash only runs when a size is wanted.
    by_size: dict[int, list[Track]] = {}
    for track in missing:
        if track.size and track.content_id:
            by_size.setdefault(track.size, []).append(track)

    claimed_tracks: dict[int, RelocateMatch] = {}
    unclaimed: list[Path] = []

    for index, candidate in enumerate(candidates):
        if is_cancelled is not None and is_cancelled():
            break
        if on_progress is not None:
            on_progress(index, total, candidate.name)
        wanted = _wanted_for(candidate, by_size)
        hit = None
        if wanted:
            content_id = compute_content_id(candidate)
            hit = next(
                (
                    t
                    for t in wanted
                    if t.content_id == content_id and t.id not in claimed_tracks
                ),
                None,
            )
        if hit is None:
            unclaimed.append(candidate)
            continue
        claimed_tracks[hit.id] = RelocateMatch(hit, str(candidate), BY_CONTENT)

    if on_progress is not None:
        on_progress(total, total, "")

    _match_by_filename(missing, unclaimed, claimed_tracks)

    matches = [claimed_tracks[t.id] for t in missing if t.id in claimed_tracks]
    unmatched = [t for t in missing if t.id not in claimed_tracks]
    return RelocateResult(matches=matches, unmatched=unmatched, scanned=total)


def apply_matches(library: Library, matches: Iterable[RelocateMatch]) -> int:
    """Re-point each matched row at its new file. Returns rows relinked.

    A row that vanished between the scan and here (the library is shared
    with the running app) is skipped rather than aborting the batch — the
    rest of a folder's worth of relinks is still worth landing.
    """
    relinked = 0
    for match in matches:
        try:
            library.relink_track(match.track.id, match.new_path)
        except (ValueError, OSError) as exc:
            logger.warning(
                "Could not relink '%s' to '%s': %s",
                match.track.path,
                match.new_path,
                exc,
            )
            continue
        relinked += 1
    return relinked


def _wanted_for(candidate: Path, by_size: dict[int, list[Track]]) -> list[Track]:
    """Missing tracks whose stored size matches this file's, if any."""
    try:
        size = candidate.stat().st_size
    except OSError:
        return []
    return by_size.get(size, [])


def _match_by_filename(
    missing: Sequence[Track],
    unclaimed: list[Path],
    claimed_tracks: dict[int, RelocateMatch],
) -> None:
    """Fill in the fingerprint's misses by name stem, uniqueness required."""
    still_missing = [t for t in missing if t.id not in claimed_tracks]
    if not still_missing:
        return
    by_stem: dict[str, list[Path]] = {}
    for candidate in unclaimed:
        by_stem.setdefault(candidate.stem.lower(), []).append(candidate)
    used: set[str] = set()
    for track in still_missing:
        options = [
            p
            for p in by_stem.get(Path(track.path).stem.lower(), [])
            if str(p) not in used
        ]
        # Exactly one, or the guess isn't safe to make silently.
        if len(options) != 1:
            continue
        chosen = options[0]
        used.add(str(chosen))
        claimed_tracks[track.id] = RelocateMatch(track, str(chosen), BY_FILENAME)
