"""Playlist file writers: ``.m3u8``, ``.m3u``, and a readable ``.txt``.

Qt-free and free of app state, like ``src/utils/export.py``, so the formats
are unit-testable on their own and reusable from the CLI later.

Two format decisions come from research into what DJ software actually
accepts (§6 of the plan doc), both from reports of Serato importing empty
crates:

* **UTF-8**, always — including for ``.m3u``. The old convention was that
  ``.m3u`` is a system-codepage file and only ``.m3u8`` is UTF-8, but every
  current player reads UTF-8 either way, and the alternative is mangling
  every non-ASCII artist name.
* **CRLF line endings**, always. Old-Mac ``\\r``-only endings produce a
  crate that imports as blank.

The third decision is §5's: paths go in **relative** when the tracks sit
under the playlist file's own folder (the zip-and-send case — the playlist
works on someone else's machine), and **absolute** otherwise, since a
scattered playlist has no sensible "relative to" point. See ``_line_paths``
for why that is phrased in terms of the playlist's folder rather than §5's
"common parent".
"""

from __future__ import annotations

import shutil
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Sequence

#: Formats offered in the export dialog. Extension → filter label stem.
M3U8 = "m3u8"
M3U = "m3u"
TXT = "txt"
FORMATS = (M3U8, M3U, TXT)

#: Characters no mainstream filesystem accepts in a name, plus the ones
#: Windows reserves. Playlist names are free text, so any name that becomes
#: a filename has to survive this.
_ILLEGAL = '<>:"/\\|?*'
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass(frozen=True)
class ExportTrack:
    """One line's worth of a playlist, decoupled from the library's Track.

    Keeps the writers usable for anything that can name a file and,
    optionally, describe it — the copy-tracks flow rewrites ``path`` after
    copying and reuses the rest.
    """

    path: str
    artist: str = ""
    title: str = ""
    duration: float | None = None

    @property
    def label(self) -> str:
        """"Artist - Title", falling back to the filename when untagged."""
        if self.artist and self.title:
            return f"{self.artist} - {self.title}"
        return self.title or self.artist or Path(self.path).stem


def safe_filename(name: str, fallback: str = "Playlist") -> str:
    """Turn a playlist or folder name into a portable filename stem.

    Exports mirror the tree, so a playlist called ``House / Techno`` must not
    silently become a directory separator. Trailing dots and spaces are
    stripped because Windows drops them anyway, which would otherwise make
    two distinct names collide.
    """
    cleaned = "".join("_" if ch in _ILLEGAL else ch for ch in name)
    cleaned = "".join(ch for ch in cleaned if unicodedata.category(ch)[0] != "C")
    cleaned = cleaned.strip(" .")
    if not cleaned or cleaned.upper().split(".")[0] in _RESERVED:
        cleaned = f"{fallback}{'_' + cleaned if cleaned else ''}"
    return cleaned[:120]


def unique_path(directory: str | Path, stem: str, suffix: str) -> Path:
    """``directory/stem.suffix``, with " (2)", " (3)"… appended if taken.

    Two playlists may legitimately share a name (different folders in the
    tree), and an export that mirrors the tree into one flat directory has
    to keep both.
    """
    directory = Path(directory)
    candidate = directory / f"{stem}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate


def _line_paths(tracks: Sequence[ExportTrack], target: Path, absolute: bool) -> list[str]:
    """The path text for each track: relative to *target*'s own folder, or absolute.

    §5 phrases the rule as "every track under one common parent → relative",
    which is the zip-and-send case where the playlist file sits in that
    parent. Generalised here to the condition that actually makes a relative
    path resolve: every track lives **under the playlist file's own
    directory**, at any depth. Tracks sharing a parent somewhere else on the
    disk get absolute paths, because a relative line would send the player
    looking next to the playlist and find nothing.

    Forward slashes throughout — Windows players accept them, and a
    backslash line breaks on macOS and Linux.
    """
    if not absolute:
        base = target.parent.resolve()
        try:
            return [
                Path(t.path).resolve().relative_to(base).as_posix() for t in tracks
            ]
        except ValueError:
            pass  # at least one track lives outside (or off the drive of) that folder
    return [str(Path(t.path)) for t in tracks]


def write_playlist(
    path: str | Path,
    tracks: Iterable[ExportTrack],
    *,
    fmt: str | None = None,
    absolute: bool = False,
    title: str = "",
) -> int:
    """Write *tracks* to *path*. Returns the number of entries written.

    *fmt* defaults to the file's own extension. *absolute* forces absolute
    paths even when the tracks would qualify for relative ones (the Settings
    escape hatch for people who keep playlists away from their audio).
    """
    path = Path(path)
    tracks = list(tracks)
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    if fmt not in FORMATS:
        raise ValueError(f"Unsupported playlist format: {fmt!r}")

    if fmt == TXT:
        body = _txt_lines(tracks, title)
    else:
        body = _m3u_lines(tracks, _line_paths(tracks, path, absolute))

    # newline="" keeps Python from translating the explicit CRLFs we write.
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write("".join(f"{line}\r\n" for line in body))
    return len(tracks)


def copy_playlist_tracks(
    tracks: Sequence[ExportTrack],
    directory: str | Path,
    *,
    on_progress=None,
    is_cancelled=None,
) -> tuple[list[ExportTrack], list[str]]:
    """Copy each track's audio file into *directory*.

    Returns ``(copied_tracks, missing_paths)`` — the copied tracks carry
    their new paths, so writing a playlist beside them produces relative
    lines and the whole folder is zip-and-send ready (§5).

    Behaviours worth knowing:

    * A track that appears twice in the playlist is copied **once**; both
      entries point at the same file, since a playlist may repeat a track on
      purpose and duplicating the audio would be waste.
    * Two different sources sharing a filename both survive, the second as
      ``name (2).ext``.
    * A missing source is **skipped**, not copied as a broken entry: keeping
      it would force the entire playlist onto absolute paths and cost the
      other tracks their portability. The caller reports the count.

    *on_progress* is called as ``(completed, total, filename)``;
    *is_cancelled* is polled between files so a long copy can be stopped.
    """
    directory = Path(directory)
    copied: list[ExportTrack] = []
    missing: list[str] = []
    seen: dict[str, Path] = {}
    for index, track in enumerate(tracks):
        if is_cancelled is not None and is_cancelled():
            break
        source = Path(track.path)
        if on_progress is not None:
            on_progress(index, len(tracks), source.name)
        already = seen.get(str(source))
        if already is not None:
            copied.append(replace(track, path=str(already)))
            continue
        if not source.is_file():
            missing.append(track.path)
            continue
        destination = unique_path(directory, source.stem, source.suffix)
        shutil.copy2(source, destination)  # copy2 keeps mtime, which DJ apps show
        seen[str(source)] = destination
        copied.append(replace(track, path=str(destination)))
    if on_progress is not None:
        on_progress(len(tracks), len(tracks), "")
    return copied, missing


def export_tracks(library, node_id: int) -> list[ExportTrack]:
    """A playlist node's items as export rows, in order (duplicates kept)."""
    return [
        ExportTrack(path=t.path, artist=t.artist, title=t.title, duration=t.duration)
        for t in library.get_items(node_id)
    ]


def export_tree(
    library,
    directory: str | Path,
    *,
    parent_id: int | None = None,
    fmt: str = M3U8,
    absolute: bool = False,
    include_scratch: bool = False,
) -> tuple[int, int]:
    """Write every playlist under *parent_id* into *directory*, mirroring folders.

    Returns ``(playlists_written, tracks_written)``. Backs both "export this
    folder" and §7d's *Export all playlists…*, which is the backup story:
    a directory of plain playlist files is something any tool can read, and
    it needs no restore-from-proprietary-blob path.

    Empty folders are still created — the shape of the tree is part of what
    is being exported.
    """
    directory = Path(directory)
    playlists = tracks = 0
    if include_scratch:
        from src.library.library import SCRATCH_NODE_ID

        scratch = library.get_node(SCRATCH_NODE_ID)
        if scratch is not None and library.item_count(SCRATCH_NODE_ID):
            target = unique_path(directory, safe_filename(scratch.name), f".{fmt}")
            tracks += write_playlist(
                target,
                export_tracks(library, SCRATCH_NODE_ID),
                fmt=fmt,
                absolute=absolute,
                title=scratch.name,
            )
            playlists += 1
    for node in library.get_children(parent_id):
        if node.kind == "folder":
            sub = unique_path(directory, safe_filename(node.name), "")
            sub.mkdir(parents=True, exist_ok=True)
            sub_playlists, sub_tracks = export_tree(
                library, sub, parent_id=node.id, fmt=fmt, absolute=absolute
            )
            playlists += sub_playlists
            tracks += sub_tracks
        elif node.kind == "playlist":
            target = unique_path(directory, safe_filename(node.name), f".{fmt}")
            tracks += write_playlist(
                target,
                export_tracks(library, node.id),
                fmt=fmt,
                absolute=absolute,
                title=node.name,
            )
            playlists += 1
    return playlists, tracks


def _m3u_lines(tracks: Sequence[ExportTrack], paths: Sequence[str]) -> list[str]:
    """Extended M3U: a header, then #EXTINF/path pairs.

    #EXTINF duration is whole seconds, -1 when unknown — the convention
    every player understands.
    """
    lines = ["#EXTM3U"]
    for track, line_path in zip(tracks, paths):
        seconds = int(round(track.duration)) if track.duration else -1
        lines.append(f"#EXTINF:{seconds},{track.label}")
        lines.append(line_path)
    return lines


def _txt_lines(tracks: Sequence[ExportTrack], title: str) -> list[str]:
    """A readable set list — for pasting into a post, not for importing.

    Numbered so it reads as a running order, which is what the playlist
    means; the importable formats are the other two.
    """
    lines = []
    if title:
        lines += [title, ""]
    width = max(2, len(str(len(tracks))))
    for i, track in enumerate(tracks, 1):
        lines.append(f"{str(i).zfill(width)}. {track.label}")
    return lines
