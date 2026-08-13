"""SQLite data layer for the playlist library.

Design rules (settled in the playlist feature research, 2026-07-26):

- Tracks are identified by an integer ``track_id``; the file path is a
  mutable column. Playlists reference ``track_id``, so in-app renames and
  path updates never break playlist membership.
- The library only holds tracks that belong to at least one playlist
  (including Scratch). Tracks with no remaining memberships are garbage
  collected.
- Duplicate tracks within a playlist are allowed: ``playlist_items`` is
  keyed on ``(node_id, position)``, not on the track.
- Sibling order in the tree is the stored ``nodes.position`` — never a
  sort. New nodes are inserted at position 0 (top).
- Search uses FTS5 when the runtime supports it (probed per connection),
  falling back to ``LIKE`` on the lowercased ``search_blob`` column.
  The FTS index is maintained from Python, not triggers, so a database
  touched by a build without FTS5 stays usable and is resynced on the
  next FTS-capable open.
- WAL journal mode, one connection per thread: each worker thread must
  construct its own ``Library`` instance.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from hashlib import blake2b
from pathlib import Path
from typing import Iterable

# Reserved node id for the Player's pinned working list ("Scratch").
SCRATCH_NODE_ID = 1

_CONTENT_ID_BYTES = 64 * 1024
_SCHEMA_VERSION = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    artist TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    album TEXT NOT NULL DEFAULT '',
    genre TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    bpm REAL,
    "key" TEXT NOT NULL DEFAULT '',
    -- Derived from "key", never set by a caller: the canonical key code the
    -- compatible-tracks query matches on, so "8A", "Am" and "A min" are one
    -- thing without an IN-list of every spelling. Empty when unparseable.
    keycode TEXT NOT NULL DEFAULT '',
    energy INTEGER,
    year TEXT,
    track_number TEXT,
    label TEXT,
    bitrate INTEGER,
    duration REAL,
    size INTEGER,
    mtime REAL,
    content_id TEXT,
    search_blob TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracks_artist_title ON tracks(artist, title);
CREATE INDEX IF NOT EXISTS idx_tracks_size_content ON tracks(size, content_id);

CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY,
    parent_id INTEGER REFERENCES nodes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('folder', 'playlist', 'scratch')),
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    expanded INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id);

CREATE TABLE IF NOT EXISTS playlist_items (
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    PRIMARY KEY (node_id, position)
);
CREATE INDEX IF NOT EXISTS idx_items_track ON playlist_items(track_id);
"""

_TAG_COLUMNS = (
    "artist",
    "title",
    "album",
    "genre",
    "comment",
    "bpm",
    "key",
    "energy",
    "year",
    "track_number",
    "label",
    "bitrate",
    "duration",
)

# `keycode` is deliberately NOT a tag column: it is derived from "key" inside
# add_track/update_track_tags so no call site can write one without the other,
# or write a spelling of it the query would miss.

# Indexed search fields, in the order the FTS table declares them. Every name
# is also a `tracks` column, so the index statements are generated from this
# list rather than spelled out — adding a field here is the whole change.
# Changing it rebuilds tracks_fts (see _ensure_fts_schema) and, on the next
# open, every row's search_blob (see _migrate).
_FTS_COLUMNS = ("artist", "title", "album", "filename", "comment", "key")


@dataclass(frozen=True)
class Track:
    """A library track row."""

    id: int
    path: str
    filename: str
    artist: str
    title: str
    album: str
    genre: str
    comment: str
    bpm: float | None
    key: str
    keycode: str
    energy: int | None
    year: str | None
    track_number: str | None
    label: str | None
    bitrate: int | None
    duration: float | None
    size: int | None
    mtime: float | None
    content_id: str | None
    added_at: str


@dataclass(frozen=True)
class Node:
    """A tree node: folder, playlist, or the reserved Scratch node."""

    id: int
    parent_id: int | None
    kind: str
    name: str
    position: int
    created_at: str
    # Folders only: whether the tree was showing this one's children. Stored
    # so the shape the user left the tree in comes back next session.
    expanded: bool = False


def default_db_path() -> Path:
    """The library database location (next to the rename history)."""
    from src.utils.app_dirs import get_app_data_dir

    return get_app_data_dir() / "library.db"


def compute_content_id(path: str | Path) -> str | None:
    """Content fingerprint: blake2b of the first 64 KB, or None if unreadable.

    Used together with the stored file size to re-link files that were
    moved or renamed outside the app.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(_CONTENT_ID_BYTES)
    except OSError:
        return None
    return blake2b(head, digest_size=16).hexdigest()


def update_paths(
    pairs: Iterable[tuple[str, str]],
    db_path: str | Path | None = None,
) -> int:
    """Best-effort (old_path, new_path) update hook for rename/undo workers.

    A no-op when the library database doesn't exist yet — there is nothing
    to keep in sync, and the hook must never create the database as a side
    effect of renaming files.
    """
    path = Path(db_path) if db_path is not None else default_db_path()
    if not path.exists():
        return 0
    with Library(path) as lib:
        return lib.update_paths(pairs)


def _probe_fts5(con: sqlite3.Connection) -> bool:
    """Runtime FTS5 capability check (~0.2 ms once per connection)."""
    try:
        con.execute("CREATE VIRTUAL TABLE temp.__fts5probe USING fts5(x)")
        con.execute("DROP TABLE temp.__fts5probe")
        return True
    except sqlite3.OperationalError:
        return False


def _make_search_blob(**fields: str) -> str:
    """The LIKE-fallback haystack: every indexed field, lowercased.

    Takes the same field names as the FTS index (`_FTS_COLUMNS`) so the two
    search paths can never drift apart; a field left out defaults to empty.
    """
    return " ".join(
        part for part in (fields.get(c) or "" for c in _FTS_COLUMNS) if part
    ).lower()


def _indexed_from_row(row: sqlite3.Row, **overrides: str) -> dict[str, str]:
    """Indexed field values read off a `tracks` row, with optional overrides.

    Used by every path that rewrites `search_blob` from what is already
    stored (a rename, a relink, an upgrade) — the row must therefore have
    been selected with `_quoted(_FTS_COLUMNS)`, or `SELECT *`.
    """
    fields = {c: row[c] or "" for c in _FTS_COLUMNS}
    fields.update(overrides)
    return fields


def _fts_values(**fields: str) -> tuple[str, ...]:
    """Indexed field values in `_FTS_COLUMNS` order, for the index statements."""
    return tuple(fields.get(c) or "" for c in _FTS_COLUMNS)


def _derive_keycode(key: object) -> str:
    """The canonical key code for a stored key, or '' if it isn't one.

    Accepts every spelling the app and other DJ tools produce — 'Am',
    'A min', 'a minor', and a code such as '8a' — because the stored key is
    whatever a file's tag happened to say.
    """
    if not key:
        return ""
    from src.analysis.keycode import key_to_keycode

    try:
        return key_to_keycode(str(key))
    except ValueError:
        return ""


_ENERGY_LABELLED = re.compile(r"^energy\s*(10|[1-9])$", re.IGNORECASE)
_ENERGY_BARE = re.compile(r"^(10|[1-9])$")


def _energy_from_comment(comment: str) -> int | None:
    """The energy this app wrote into a comment, when it can be read safely.

    ``update_comment_with_energy`` writes a " - "-joined prefix (or suffix) of
    the energy and/or the key, in either order: "6 - 8A - visit my webpage",
    "Energy 6 - 8A - …", "8A - 6 - …". So only the two segments at each end
    can hold it.

    Deliberately conservative, because the bare-number format is genuinely
    ambiguous — "7 - Heaven" is a real comment, not an energy of 7. A labelled
    "Energy 7" is unmistakable and always taken; a bare number counts only
    when the segment beside it parses as a key, which is the shape this app
    writes. Anything else reads as "no energy recorded" and stays NULL.
    """
    segments = [s.strip() for s in comment.split(" - ")]
    if not segments:
        return None
    edges = {0, 1, len(segments) - 2, len(segments) - 1}
    for i in sorted(e for e in edges if 0 <= e < len(segments)):
        segment = segments[i]
        labelled = _ENERGY_LABELLED.match(segment)
        if labelled:
            return int(labelled.group(1))
        bare = _ENERGY_BARE.match(segment)
        if bare and any(
            _derive_keycode(segments[j])
            for j in (i - 1, i + 1)
            if 0 <= j < len(segments)
        ):
            return int(bare.group(1))
    return None


def _quoted(columns: tuple[str, ...]) -> str:
    """Column list for SQL. Quoted because "key" is a keyword in places."""
    return ", ".join(f'"{c}"' for c in columns)


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Library:
    """One thread's handle on the library database.

    Connections are not shareable across threads (sqlite3.threadsafety == 1),
    so each QThread worker must construct its own instance.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        enable_fts: bool | None = None,
    ) -> None:
        """Open (creating if needed) the library database.

        Args:
            db_path: Database file; defaults to the app data directory.
            enable_fts: Force FTS on/off; None probes the runtime. Passing
                False exercises the LIKE fallback (used by tests).
        """
        self._db_path = Path(db_path) if db_path is not None else default_db_path()
        con = sqlite3.connect(self._db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA synchronous=NORMAL")
        self._con = con
        self._has_fts = _probe_fts5(con) if enable_fts is None else bool(enable_fts) and _probe_fts5(con)
        self._init_schema()

    # ------------------------------------------------------------------ setup

    def _init_schema(self) -> None:
        with self._con:
            self._con.executescript(_SCHEMA)
            self._migrate()
            self._con.execute(
                """
                INSERT OR IGNORE INTO nodes (id, parent_id, kind, name, position, created_at)
                VALUES (?, NULL, 'scratch', 'Scratch', -1, ?)
                """,
                (SCRATCH_NODE_ID, _now()),
            )
            if self._has_fts:
                self._ensure_fts_schema()
                self._sync_fts()
            self._con.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    def _migrate(self) -> None:
        """Bring an older database up to `_SCHEMA_VERSION`.

        ``CREATE TABLE IF NOT EXISTS`` leaves an existing table exactly as it
        was, so every column added after v1 needs an ALTER here.

        Two different triggers, deliberately: a **column** is keyed on the
        columns actually present, because a database touched by a build that
        pre-dates the pragma bump would be skipped by a version check, and
        re-adding a column is the one error we can't recover from. **Stored
        data** that needs recomputing has no such tell, so it is keyed on
        ``user_version`` — which also keeps it one-shot instead of running on
        every open.
        """
        nodes = {row["name"] for row in self._con.execute("PRAGMA table_info(nodes)")}
        if "expanded" not in nodes:  # v2 — remembered folder expansion
            self._con.execute(
                "ALTER TABLE nodes ADD COLUMN expanded INTEGER NOT NULL DEFAULT 0"
            )
        tracks = {row["name"] for row in self._con.execute("PRAGMA table_info(tracks)")}
        if "comment" not in tracks:  # v3 — comment is a searchable field
            self._con.execute(
                "ALTER TABLE tracks ADD COLUMN comment TEXT NOT NULL DEFAULT ''"
            )
            # No blob rebuild needed for this one on its own: the blob skips
            # empty parts, so every existing blob already equals what it would
            # be with a blank comment. The comments themselves arrive with the
            # tag reads that adding, loading, or editing a track performs.
        # v5 — the consolidated migration: a derived keycode for the
        # compatible-tracks query, and four columns the Player can show as
        # optional table columns. None of them is searchable, so _FTS_COLUMNS
        # and the search blobs are untouched.
        for column, decl in (
            ("keycode", "TEXT NOT NULL DEFAULT ''"),
            ("year", "TEXT"),
            ("track_number", "TEXT"),
            ("label", "TEXT"),
            ("bitrate", "INTEGER"),
        ):
            if column not in tracks:
                self._con.execute(f"ALTER TABLE tracks ADD COLUMN {column} {decl}")

        (version,) = self._con.execute("PRAGMA user_version").fetchone()
        if version and version < 4:  # v4 — the key became a searchable field
            # Here a rebuild IS required: existing rows have a stored key that
            # their blob doesn't include, so the LIKE fallback would miss it
            # forever. (The FTS index needs no equivalent — _ensure_fts_schema
            # notices its column list changed and repopulates from `tracks`.)
            self._rebuild_search_blobs()
        if version and version < 5:
            # Recomputes, so keyed on the version rather than on the columns:
            # both read data the database already holds, and both must run
            # exactly once. Year, track number, label and bitrate get NO
            # backfill on purpose — they live only in the files' tags, and
            # reading thousands of files during a migration is not something
            # a first launch may do. They populate forward, as files are
            # added, reloaded or analysed.
            self._backfill_keycodes()
            self._backfill_energy_from_comments()

    def _backfill_keycodes(self) -> None:
        """Fill `keycode` for rows that already carry a key. Cheap: the data
        is in the row, so this is a parse, not a file read."""
        rows = self._con.execute(
            "SELECT id, \"key\" FROM tracks WHERE \"key\" != '' AND keycode = ''"
        ).fetchall()
        updates = [
            (code, row["id"])
            for row in rows
            if (code := _derive_keycode(row["key"]))
        ]
        self._con.executemany(
            "UPDATE tracks SET keycode=? WHERE id=?", updates
        )

    def _backfill_energy_from_comments(self) -> None:
        """Recover the energy this app itself wrote into the comment tag.

        Only rows with no energy yet, and only where the read is unambiguous
        (see `_energy_from_comment`) — a wrong energy is worse than a blank
        one here, because the compatible-tracks ranking would quietly order
        by it.
        """
        rows = self._con.execute(
            "SELECT id, comment FROM tracks WHERE energy IS NULL AND comment != ''"
        ).fetchall()
        updates = [
            (energy, row["id"])
            for row in rows
            if (energy := _energy_from_comment(row["comment"])) is not None
        ]
        self._con.executemany(
            "UPDATE tracks SET energy=? WHERE id=?", updates
        )

    def _rebuild_search_blobs(self) -> None:
        """Recompute every row's LIKE haystack from the columns it indexes."""
        rows = self._con.execute(
            f"SELECT id, {_quoted(_FTS_COLUMNS)} FROM tracks"
        ).fetchall()
        self._con.executemany(
            "UPDATE tracks SET search_blob=? WHERE id=?",
            [
                (_make_search_blob(**_indexed_from_row(row)), row["id"])
                for row in rows
            ],
        )

    def _ensure_fts_schema(self) -> None:
        """Create tracks_fts, rebuilding it if its columns are out of date.

        An FTS5 table's columns are fixed at creation, so adding a searchable
        field means dropping and recreating it. Cheap: it is a pure index over
        `tracks`, and `_sync_fts` repopulates it from there straight after.
        """
        existing = [
            row["name"] for row in self._con.execute("PRAGMA table_info(tracks_fts)")
        ]
        if existing and tuple(existing) != _FTS_COLUMNS:
            self._con.execute("DROP TABLE tracks_fts")
            existing = []
        if not existing:
            self._con.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts"
                f" USING fts5({_quoted(_FTS_COLUMNS)})"
            )

    def _sync_fts(self) -> None:
        """Rebuild the FTS index if it disagrees with the tracks table.

        Happens after the database was modified by a build without FTS5
        (the LIKE-fallback path maintains search_blob but not tracks_fts).
        """
        (n_tracks,) = self._con.execute("SELECT count(*) FROM tracks").fetchone()
        (n_fts,) = self._con.execute("SELECT count(*) FROM tracks_fts").fetchone()
        if n_tracks != n_fts:
            self._con.execute("DELETE FROM tracks_fts")
            columns = _quoted(_FTS_COLUMNS)
            self._con.execute(
                f"INSERT INTO tracks_fts (rowid, {columns})"
                f" SELECT id, {columns} FROM tracks"
            )

    @property
    def has_fts(self) -> bool:
        return self._has_fts

    @property
    def db_path(self) -> Path:
        return self._db_path

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> Library:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ----------------------------------------------------------------- tracks

    def add_track(
        self,
        path: str | Path,
        *,
        artist: str | None = None,
        title: str | None = None,
        album: str | None = None,
        genre: str | None = None,
        comment: str | None = None,
        bpm: float | None = None,
        key: str | None = None,
        energy: int | None = None,
        year: str | None = None,
        track_number: str | None = None,
        label: str | None = None,
        bitrate: int | None = None,
        duration: float | None = None,
    ) -> int:
        """Insert a track, or update the existing row for the same path.

        Only fields passed as non-None overwrite an existing row's tags,
        so callers with partial information never blank out known values.
        Returns the track id.
        """
        path = str(path)
        tags = {
            "artist": artist,
            "title": title,
            "album": album,
            "genre": genre,
            "comment": comment,
            "bpm": bpm,
            "key": key,
            "energy": energy,
            "year": year,
            "track_number": track_number,
            "label": label,
            "bitrate": bitrate,
            "duration": duration,
        }
        existing = self._con.execute(
            "SELECT id FROM tracks WHERE path=?", (path,)
        ).fetchone()
        if existing:
            provided = {k: v for k, v in tags.items() if v is not None}
            if provided:
                self.update_track_tags(existing["id"], **provided)
            return existing["id"]

        size, mtime = _stat(path)
        filename = Path(path).name
        indexed = {c: tags.get(c) or "" for c in _FTS_COLUMNS}
        indexed["filename"] = filename
        blob = _make_search_blob(**indexed)
        with self._con:
            cur = self._con.execute(
                """
                INSERT INTO tracks
                    (path, filename, artist, title, album, genre, comment, bpm,
                     "key", keycode, energy, year, track_number, label, bitrate,
                     duration, size, mtime, content_id, search_blob,
                     added_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    path,
                    filename,
                    tags["artist"] or "",
                    tags["title"] or "",
                    tags["album"] or "",
                    tags["genre"] or "",
                    tags["comment"] or "",
                    tags["bpm"],
                    tags["key"] or "",
                    _derive_keycode(tags["key"]),
                    tags["energy"],
                    tags["year"],
                    tags["track_number"],
                    tags["label"],
                    tags["bitrate"],
                    tags["duration"],
                    size,
                    mtime,
                    compute_content_id(path),
                    blob,
                    _now(),
                ),
            )
            track_id = cur.lastrowid
            if self._has_fts:
                marks = ", ".join("?" * len(_FTS_COLUMNS))
                self._con.execute(
                    f"INSERT INTO tracks_fts (rowid, {_quoted(_FTS_COLUMNS)})"
                    f" VALUES (?, {marks})",
                    (track_id, *_fts_values(**indexed)),
                )
        return track_id

    def get_track(self, track_id: int) -> Track | None:
        row = self._con.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
        return _track(row) if row else None

    def get_track_by_path(self, path: str | Path) -> Track | None:
        row = self._con.execute(
            "SELECT * FROM tracks WHERE path=?", (str(path),)
        ).fetchone()
        return _track(row) if row else None

    def get_tracks(self, track_ids: Iterable[int]) -> list[Track]:
        """Fetch tracks by id, preserving the input order (skips unknown ids)."""
        ids = list(track_ids)
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = self._con.execute(
            f"SELECT * FROM tracks WHERE id IN ({marks})", ids
        ).fetchall()
        by_id = {row["id"]: _track(row) for row in rows}
        return [by_id[i] for i in ids if i in by_id]

    def track_count(self) -> int:
        (n,) = self._con.execute("SELECT count(*) FROM tracks").fetchone()
        return n

    def track_ids(self) -> list[int]:
        """All track ids ordered for display (artist, title) — feeds the lazy model."""
        rows = self._con.execute(
            "SELECT id FROM tracks ORDER BY artist, title, id"
        ).fetchall()
        return [row["id"] for row in rows]

    def all_tracks(self) -> list[Track]:
        """Every track row, display-ordered — the relocate scan's input."""
        rows = self._con.execute(
            "SELECT * FROM tracks ORDER BY artist, title, id"
        ).fetchall()
        return [_track(row) for row in rows]

    def update_track_tags(self, track_id: int, **fields: object) -> None:
        """Update tag columns (see `_TAG_COLUMNS`)."""
        unknown = set(fields) - set(_TAG_COLUMNS)
        if unknown:
            raise ValueError(f"Unknown tag column(s): {sorted(unknown)}")
        if not fields:
            return
        row = self._con.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
        if row is None:
            raise ValueError(f"No track with id {track_id}")
        merged = {c: fields.get(c, row[c]) for c in _TAG_COLUMNS}
        indexed = {c: merged.get(c, row[c]) for c in _FTS_COLUMNS}
        indexed = {c: "" if v is None else str(v) for c, v in indexed.items()}
        blob = _make_search_blob(**indexed)
        # The key never moves without its derived code following it — doing
        # this here rather than at the call sites is what keeps the two from
        # drifting apart on whichever path someone forgets.
        writes = dict(fields)
        if "key" in writes:
            writes["keycode"] = _derive_keycode(writes["key"])
        assignments = ", ".join(f'"{c}"=?' for c in writes)
        with self._con:
            self._con.execute(
                f"UPDATE tracks SET {assignments}, search_blob=? WHERE id=?",
                [*writes.values(), blob, track_id],
            )
            if self._has_fts:
                assignments = ", ".join(f'"{c}"=?' for c in _FTS_COLUMNS)
                self._con.execute(
                    f"UPDATE tracks_fts SET {assignments} WHERE rowid=?",
                    (*_fts_values(**indexed), track_id),
                )

    def update_paths(self, pairs: Iterable[tuple[str, str]]) -> int:
        """Point library rows at renamed files; the rename/undo worker hook.

        Pairs whose old path isn't in the library are ignored, as is any
        pair whose new path already belongs to a different row (the UNIQUE
        constraint must never abort the whole batch). Returns the number
        of rows updated.
        """
        updated = 0
        with self._con:
            for old_path, new_path in pairs:
                row = self._con.execute(
                    f"SELECT id, {_quoted(_FTS_COLUMNS)} FROM tracks WHERE path=?",
                    (str(old_path),),
                ).fetchone()
                if row is None:
                    continue
                clash = self._con.execute(
                    "SELECT id FROM tracks WHERE path=? AND id!=?",
                    (str(new_path), row["id"]),
                ).fetchone()
                if clash:
                    continue
                filename = Path(new_path).name
                blob = _make_search_blob(**_indexed_from_row(row, filename=filename))
                size, mtime = _stat(new_path)
                self._con.execute(
                    "UPDATE tracks SET path=?, filename=?, search_blob=?, size=?, mtime=?"
                    " WHERE id=?",
                    (str(new_path), filename, blob, size, mtime, row["id"]),
                )
                if self._has_fts:
                    self._con.execute(
                        "UPDATE tracks_fts SET filename=? WHERE rowid=?",
                        (filename, row["id"]),
                    )
                updated += 1
        return updated

    def relink_track(self, track_id: int, new_path: str | Path) -> int:
        """Point a track row at a file that moved *outside* the app (§1).

        Unlike :meth:`update_paths` (the in-app rename hook), this
        recomputes the fingerprint from the new file: a relocated file is
        the authority for what it now contains, since the fallback match
        also covers a file that was re-encoded rather than merely moved.

        If another row already owns *new_path* the two rows describe one
        file, so they are merged — memberships move to the surviving row
        and the relinked row is dropped. Returns the surviving track id,
        which is *not* ``track_id`` in the merge case.
        """
        new_path = str(new_path)
        row = self._con.execute(
            "SELECT * FROM tracks WHERE id=?", (track_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"No track with id {track_id}")
        clash = self._con.execute(
            "SELECT id FROM tracks WHERE path=? AND id!=?", (new_path, track_id)
        ).fetchone()
        with self._con:
            if clash:
                # playlist_items is keyed on (node_id, position), so a
                # playlist that held both rows simply ends up holding the
                # survivor twice — duplicates are allowed by design.
                survivor = int(clash["id"])
                self._con.execute(
                    "UPDATE playlist_items SET track_id=? WHERE track_id=?",
                    (survivor, track_id),
                )
                if self._has_fts:
                    self._con.execute(
                        "DELETE FROM tracks_fts WHERE rowid=?", (track_id,)
                    )
                self._con.execute("DELETE FROM tracks WHERE id=?", (track_id,))
                return survivor
            filename = Path(new_path).name
            blob = _make_search_blob(**_indexed_from_row(row, filename=filename))
            size, mtime = _stat(new_path)
            self._con.execute(
                "UPDATE tracks SET path=?, filename=?, search_blob=?, size=?,"
                " mtime=?, content_id=? WHERE id=?",
                (
                    new_path,
                    filename,
                    blob,
                    size,
                    mtime,
                    compute_content_id(new_path),
                    track_id,
                ),
            )
            if self._has_fts:
                self._con.execute(
                    "UPDATE tracks_fts SET filename=? WHERE rowid=?",
                    (filename, track_id),
                )
        return track_id

    # ------------------------------------------------------------------ nodes

    def get_node(self, node_id: int) -> Node | None:
        row = self._con.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return _node(row) if row else None

    def get_children(self, parent_id: int | None = None) -> list[Node]:
        """Folders and playlists under a parent (root = None), in stored order.

        Scratch is excluded — the UI pins it above the tree.
        """
        rows = self._con.execute(
            "SELECT * FROM nodes WHERE parent_id IS ? AND kind != 'scratch'"
            " ORDER BY position, id",
            (parent_id,),
        ).fetchall()
        return [_node(row) for row in rows]

    def create_folder(self, name: str, parent_id: int | None = None) -> int:
        return self._create_node("folder", name, parent_id)

    def create_playlist(self, name: str, parent_id: int | None = None) -> int:
        return self._create_node("playlist", name, parent_id)

    def _create_node(self, kind: str, name: str, parent_id: int | None) -> int:
        self._require_folder_or_root(parent_id)
        with self._con:
            # Newest node goes to the top; the user reorders from there and
            # nodes.position stays authoritative (never sorted).
            self._con.execute(
                "UPDATE nodes SET position = position + 1"
                " WHERE parent_id IS ? AND kind != 'scratch'",
                (parent_id,),
            )
            cur = self._con.execute(
                "INSERT INTO nodes (parent_id, kind, name, position, created_at)"
                " VALUES (?, ?, ?, 0, ?)",
                (parent_id, kind, name, _now()),
            )
        return cur.lastrowid

    def rename_node(self, node_id: int, name: str) -> None:
        node = self._require_node(node_id)
        if node.kind == "scratch":
            raise ValueError("Scratch cannot be renamed")
        with self._con:
            self._con.execute("UPDATE nodes SET name=? WHERE id=?", (name, node_id))

    def delete_node(self, node_id: int) -> None:
        """Delete a folder or playlist. Folders cascade to all descendants."""
        node = self._require_node(node_id)
        if node.kind == "scratch":
            raise ValueError("Scratch cannot be deleted")
        with self._con:
            # Collect the subtree's tracks before the cascade removes the
            # membership rows we need for the orphan check.
            candidates = {
                row["track_id"]
                for row in self._con.execute(
                    """
                    WITH RECURSIVE sub(id) AS (
                        SELECT ? UNION ALL
                        SELECT n.id FROM nodes n JOIN sub ON n.parent_id = sub.id
                    )
                    SELECT DISTINCT track_id FROM playlist_items
                    WHERE node_id IN (SELECT id FROM sub)
                    """,
                    (node_id,),
                ).fetchall()
            }
            self._con.execute("DELETE FROM nodes WHERE id=?", (node_id,))
            self._renumber_children(node.parent_id)
            self._gc_tracks(candidates)

    def move_node(
        self,
        node_id: int,
        new_parent_id: int | None = None,
        position: int = 0,
    ) -> None:
        """Reparent and/or reposition a node among its siblings."""
        node = self._require_node(node_id)
        if node.kind == "scratch":
            raise ValueError("Scratch cannot be moved")
        self._require_folder_or_root(new_parent_id)
        if new_parent_id is not None:
            if new_parent_id == node_id or node_id in self.ancestor_ids(new_parent_id):
                raise ValueError("Cannot move a node into its own subtree")
        siblings = [n.id for n in self.get_children(new_parent_id) if n.id != node_id]
        position = max(0, min(position, len(siblings)))
        siblings.insert(position, node_id)
        with self._con:
            self._con.execute(
                "UPDATE nodes SET parent_id=? WHERE id=?", (new_parent_id, node_id)
            )
            self._con.executemany(
                "UPDATE nodes SET position=? WHERE id=?",
                [(i, nid) for i, nid in enumerate(siblings)],
            )
            if node.parent_id != new_parent_id:
                self._renumber_children(node.parent_id)

    def set_child_order(self, parent_id: int | None, ordered_ids: list[int]) -> None:
        """Persist a full reorder of one parent's children (drag-reorder)."""
        current = [n.id for n in self.get_children(parent_id)]
        if sorted(current) != sorted(ordered_ids):
            raise ValueError("ordered_ids must be a permutation of the current children")
        with self._con:
            self._con.executemany(
                "UPDATE nodes SET position=? WHERE id=?",
                [(i, nid) for i, nid in enumerate(ordered_ids)],
            )

    def set_node_expanded(self, node_id: int, expanded: bool) -> None:
        """Remember whether a folder is showing its children.

        Deliberately unvalidated and outside a `_require_node` check: this is
        view state written on every expand/collapse, including ones that race
        a delete, and a folder that vanished simply updates nothing.
        """
        with self._con:
            self._con.execute(
                "UPDATE nodes SET expanded=? WHERE id=?", (int(bool(expanded)), node_id)
            )

    def expanded_node_ids(self) -> set[int]:
        """Folders the tree should open on load."""
        rows = self._con.execute("SELECT id FROM nodes WHERE expanded=1").fetchall()
        return {row["id"] for row in rows}

    def ancestor_ids(self, node_id: int) -> list[int]:
        """Ancestors of a node, nearest first (for cycle checks and the
        highlight-trail roll-up)."""
        rows = self._con.execute(
            """
            WITH RECURSIVE up(id, parent_id) AS (
                SELECT id, parent_id FROM nodes WHERE id=?
                UNION ALL
                SELECT n.id, n.parent_id FROM nodes n JOIN up ON n.id = up.parent_id
            )
            SELECT id FROM up WHERE id != ?
            """,
            (node_id, node_id),
        ).fetchall()
        return [row["id"] for row in rows]

    def _renumber_children(self, parent_id: int | None) -> None:
        rows = self._con.execute(
            "SELECT id FROM nodes WHERE parent_id IS ? AND kind != 'scratch'"
            " ORDER BY position, id",
            (parent_id,),
        ).fetchall()
        self._con.executemany(
            "UPDATE nodes SET position=? WHERE id=?",
            [(i, row["id"]) for i, row in enumerate(rows)],
        )

    def _require_node(self, node_id: int) -> Node:
        node = self.get_node(node_id)
        if node is None:
            raise ValueError(f"No node with id {node_id}")
        return node

    def _require_folder_or_root(self, parent_id: int | None) -> None:
        if parent_id is None:
            return
        parent = self._require_node(parent_id)
        if parent.kind != "folder":
            raise ValueError("Parent must be a folder")

    # ------------------------------------------------------------------ items

    def get_item_track_ids(self, node_id: int) -> list[int]:
        rows = self._con.execute(
            "SELECT track_id FROM playlist_items WHERE node_id=? ORDER BY position",
            (node_id,),
        ).fetchall()
        return [row["track_id"] for row in rows]

    def get_items(self, node_id: int) -> list[Track]:
        """A playlist's tracks in order (duplicates appear once per position)."""
        rows = self._con.execute(
            "SELECT t.* FROM playlist_items pi JOIN tracks t ON t.id = pi.track_id"
            " WHERE pi.node_id=? ORDER BY pi.position",
            (node_id,),
        ).fetchall()
        return [_track(row) for row in rows]

    def item_count(self, node_id: int) -> int:
        (n,) = self._con.execute(
            "SELECT count(*) FROM playlist_items WHERE node_id=?", (node_id,)
        ).fetchone()
        return n

    def set_items(self, node_id: int, track_ids: list[int]) -> None:
        """Replace a playlist's contents wholesale.

        The primitive behind add/remove/reorder: rewriting even a
        2,000-item list measures ~1 ms, and delete-then-insert avoids
        transient (node_id, position) key collisions.
        """
        node = self._require_node(node_id)
        if node.kind not in ("playlist", "scratch"):
            raise ValueError("Only playlists (or Scratch) hold tracks")
        if track_ids:
            marks = ",".join("?" * len(set(track_ids)))
            (found,) = self._con.execute(
                f"SELECT count(*) FROM tracks WHERE id IN ({marks})",
                list(set(track_ids)),
            ).fetchone()
            if found != len(set(track_ids)):
                raise ValueError("track_ids contains unknown track id(s)")
        removed = set(self.get_item_track_ids(node_id)) - set(track_ids)
        with self._con:
            self._con.execute("DELETE FROM playlist_items WHERE node_id=?", (node_id,))
            self._con.executemany(
                "INSERT INTO playlist_items (node_id, track_id, position) VALUES (?, ?, ?)",
                [(node_id, tid, i) for i, tid in enumerate(track_ids)],
            )
            self._gc_tracks(removed)

    def add_items(
        self,
        node_id: int,
        track_ids: list[int],
        position: int | None = None,
    ) -> None:
        """Insert tracks at a position (default: append). Duplicates allowed."""
        items = self.get_item_track_ids(node_id)
        if position is None:
            position = len(items)
        position = max(0, min(position, len(items)))
        self.set_items(node_id, items[:position] + list(track_ids) + items[position:])

    def remove_items(self, node_id: int, positions: Iterable[int]) -> None:
        """Remove items by position (not by track id — duplicates are distinct)."""
        drop = set(positions)
        items = self.get_item_track_ids(node_id)
        self.set_items(node_id, [t for i, t in enumerate(items) if i not in drop])

    def move_item(self, node_id: int, from_pos: int, to_pos: int) -> None:
        items = self.get_item_track_ids(node_id)
        if not 0 <= from_pos < len(items):
            raise ValueError(f"from_pos {from_pos} out of range")
        track = items.pop(from_pos)
        items.insert(max(0, min(to_pos, len(items))), track)
        self.set_items(node_id, items)

    def _gc_tracks(self, candidate_ids: set[int]) -> None:
        """Drop candidate tracks that no longer belong to any playlist.

        Keeps the invariant that the library *is* "tracks in your
        playlists". Only tracks touched by the current operation are
        candidates — a track added via add_track() but not yet placed in
        a playlist must survive until its add_items() call lands.
        """
        if not candidate_ids:
            return
        marks = ",".join("?" * len(candidate_ids))
        rows = self._con.execute(
            f"SELECT id FROM tracks WHERE id IN ({marks}) AND id NOT IN"
            f" (SELECT DISTINCT track_id FROM playlist_items)",
            list(candidate_ids),
        ).fetchall()
        ids = [(row["id"],) for row in rows]
        if self._has_fts:
            self._con.executemany("DELETE FROM tracks_fts WHERE rowid=?", ids)
        self._con.executemany("DELETE FROM tracks WHERE id=?", ids)

    # ------------------------------------------------------------------- undo

    def snapshot_items(self, node_id: int) -> list[Track]:
        """Capture a playlist's contents for the session undo stack (§11).

        Full ``Track`` rows rather than ids, because ids are not stable
        across the operation being undone — see :meth:`restore_items`.
        """
        return self.get_items(node_id)

    def restore_items(self, node_id: int, tracks: list[Track]) -> None:
        """Put a playlist back to a :meth:`snapshot_items` capture.

        Resolves each track by **path**, not by id: removing a track's last
        membership garbage-collects its row (:meth:`_gc_tracks`), so a
        snapshot's ids may name rows that no longer exist. A surviving row
        is reused as-is — its tags may have been edited since the snapshot
        (via another playlist, or the metadata panel) and undoing a
        *playlist* edit must never roll back *file* tags (§11). Only a row
        that really vanished is recreated, from the snapshot's fields.
        """
        track_ids = []
        for t in tracks:
            live = self.get_track_by_path(t.path)
            track_ids.append(
                live.id
                if live is not None
                else self.add_track(
                    t.path,
                    artist=t.artist,
                    title=t.title,
                    album=t.album,
                    genre=t.genre,
                    comment=t.comment,
                    bpm=t.bpm,
                    key=t.key,
                    energy=t.energy,
                    year=t.year,
                    track_number=t.track_number,
                    label=t.label,
                    bitrate=t.bitrate,
                    duration=t.duration,
                )
            )
        self.set_items(node_id, track_ids)

    def snapshot_subtree(self, node_id: int) -> dict:
        """Capture a node, its descendants, and their contents.

        The undo token for a delete, which cascades
        (``nodes.parent_id … ON DELETE CASCADE``). Nodes come back
        parents-first so :meth:`restore_subtree` can remap ids as it walks.
        """
        node = self._require_node(node_id)
        if node.kind == "scratch":
            raise ValueError("Scratch cannot be snapshotted")
        rows = self._con.execute(
            """
            WITH RECURSIVE sub(id) AS (
                SELECT ? UNION ALL
                SELECT n.id FROM nodes n JOIN sub ON n.parent_id = sub.id
            )
            SELECT * FROM nodes WHERE id IN (SELECT id FROM sub)
            """,
            (node_id,),
        ).fetchall()
        # Order parents before children so restore always has its parent's
        # new id in hand (the CTE's own order is not contractual).
        nodes = [_node(row) for row in rows]
        by_depth = {n.id: len(self.ancestor_ids(n.id)) for n in nodes}
        nodes.sort(key=lambda n: (by_depth[n.id], n.position, n.id))
        return {
            "root_id": node_id,
            "nodes": nodes,
            "items": {
                n.id: self.get_items(n.id) for n in nodes if n.kind == "playlist"
            },
        }

    def restore_subtree(self, snapshot: dict) -> int:
        """Re-create a :meth:`snapshot_subtree` capture. Returns the root's id.

        Original ids are kept when still free, so a restored playlist keeps
        its identity for anything holding an id (the Player's loaded node,
        the tree's highlight trail). SQLite reuses ``max(id)+1``, so an id
        can have been claimed since the delete — those nodes come back with
        a fresh id and their children are remapped onto it.
        """
        id_map: dict[int, int] = {}
        for node in snapshot["nodes"]:
            parent_id = id_map.get(node.parent_id, node.parent_id)
            if parent_id is not None and self.get_node(parent_id) is None:
                parent_id = None  # the old parent is gone too — restore at the root
            id_map[node.id] = self._restore_node(node, parent_id)
        for old_id, tracks in snapshot["items"].items():
            self.restore_items(id_map[old_id], tracks)
        return id_map[snapshot["root_id"]]

    def _restore_node(self, node: Node, parent_id: int | None) -> int:
        """Re-insert one node at its recorded slot among its siblings."""
        with self._con:
            self._con.execute(
                "UPDATE nodes SET position = position + 1 WHERE parent_id IS ?"
                " AND kind != 'scratch' AND position >= ?",
                (parent_id, node.position),
            )
            taken = self._con.execute(
                "SELECT 1 FROM nodes WHERE id=?", (node.id,)
            ).fetchone()
            columns = "parent_id, kind, name, position, created_at, expanded"
            values = (
                parent_id,
                node.kind,
                node.name,
                node.position,
                node.created_at,
                int(node.expanded),
            )
            if taken:
                cur = self._con.execute(
                    f"INSERT INTO nodes ({columns}) VALUES (?, ?, ?, ?, ?, ?)", values
                )
            else:
                cur = self._con.execute(
                    f"INSERT INTO nodes (id, {columns}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (node.id, *values),
                )
            new_id = cur.lastrowid
            self._renumber_children(parent_id)
        return new_id

    # ----------------------------------------------------------------- search

    def search(self, text: str, limit: int = 500) -> list[int]:
        """Track ids matching every word in ``text`` (prefix match), ordered
        by artist/title. Empty input returns no results."""
        tokens = text.split()
        if not tokens:
            return []
        if self._has_fts:
            query = " ".join('"{}"*'.format(t.replace('"', '""')) for t in tokens)
            try:
                rows = self._con.execute(
                    "SELECT t.id FROM tracks_fts f JOIN tracks t ON t.id = f.rowid"
                    " WHERE tracks_fts MATCH ? ORDER BY t.artist, t.title, t.id LIMIT ?",
                    (query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = self._search_like(tokens, limit)
        else:
            rows = self._search_like(tokens, limit)
        return [row["id"] for row in rows]

    def _search_like(self, tokens: list[str], limit: int) -> list[sqlite3.Row]:
        clauses = " AND ".join(
            "search_blob LIKE ? ESCAPE '\\'" for _ in tokens
        )
        params = [f"%{_escape_like(t.lower())}%" for t in tokens]
        return self._con.execute(
            f"SELECT id FROM tracks WHERE {clauses} ORDER BY artist, title, id LIMIT ?",
            [*params, limit],
        ).fetchall()

    # --------------------------------------------------- reverse lookup

    def playlists_containing(self, track_id: int) -> list[Node]:
        """Saved playlists holding a track (Scratch excluded), by name."""
        rows = self._con.execute(
            "SELECT DISTINCT n.* FROM playlist_items pi"
            " JOIN nodes n ON n.id = pi.node_id"
            " WHERE pi.track_id=? AND n.kind='playlist' ORDER BY n.name, n.id",
            (track_id,),
        ).fetchall()
        return [_node(row) for row in rows]

    def membership_counts(self, track_ids: Iterable[int]) -> dict[int, int]:
        """How many saved playlists each track is in — one query per result
        page (feeds the "Playlists" column). Tracks in none are omitted."""
        ids = list(track_ids)
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self._con.execute(
            f"SELECT pi.track_id, count(DISTINCT pi.node_id) AS n"
            f" FROM playlist_items pi JOIN nodes nd ON nd.id = pi.node_id"
            f" WHERE nd.kind='playlist' AND pi.track_id IN ({marks})"
            f" GROUP BY pi.track_id",
            ids,
        ).fetchall()
        return {row["track_id"]: row["n"] for row in rows}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _stat(path: str | Path) -> tuple[int | None, float | None]:
    try:
        st = Path(path).stat()
    except OSError:
        return None, None
    return st.st_size, st.st_mtime


def _track(row: sqlite3.Row) -> Track:
    return Track(
        id=row["id"],
        path=row["path"],
        filename=row["filename"],
        artist=row["artist"],
        title=row["title"],
        album=row["album"],
        genre=row["genre"],
        comment=row["comment"],
        bpm=row["bpm"],
        key=row["key"],
        keycode=row["keycode"],
        energy=row["energy"],
        year=row["year"],
        track_number=row["track_number"],
        label=row["label"],
        bitrate=row["bitrate"],
        duration=row["duration"],
        size=row["size"],
        mtime=row["mtime"],
        content_id=row["content_id"],
        added_at=row["added_at"],
    )


def _node(row: sqlite3.Row) -> Node:
    return Node(
        id=row["id"],
        parent_id=row["parent_id"],
        kind=row["kind"],
        name=row["name"],
        position=row["position"],
        created_at=row["created_at"],
        expanded=bool(row["expanded"]),
    )
