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

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from hashlib import blake2b
from pathlib import Path
from typing import Iterable

# Reserved node id for the Player's pinned working list ("Scratch").
SCRATCH_NODE_ID = 1

_CONTENT_ID_BYTES = 64 * 1024
_SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    artist TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    album TEXT NOT NULL DEFAULT '',
    genre TEXT NOT NULL DEFAULT '',
    bpm REAL,
    "key" TEXT NOT NULL DEFAULT '',
    energy INTEGER,
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

_TAG_COLUMNS = ("artist", "title", "album", "genre", "bpm", "key", "energy", "duration")


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
    bpm: float | None
    key: str
    energy: int | None
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


def _make_search_blob(artist: str, title: str, album: str, filename: str) -> str:
    return " ".join(part for part in (artist, title, album, filename) if part).lower()


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
                self._con.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts"
                    " USING fts5(artist, title, album, filename)"
                )
                self._sync_fts()
            self._con.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    def _migrate(self) -> None:
        """Bring an older database up to `_SCHEMA_VERSION`.

        ``CREATE TABLE IF NOT EXISTS`` leaves an existing table exactly as it
        was, so every column added after v1 needs an ALTER here. Keyed on the
        columns actually present rather than on ``user_version``: a database
        touched by a build that pre-dates the pragma bump would otherwise be
        skipped, and re-adding a column is the one error we can't recover from.
        """
        columns = {
            row["name"] for row in self._con.execute("PRAGMA table_info(nodes)")
        }
        if "expanded" not in columns:  # v2 — remembered folder expansion
            self._con.execute(
                "ALTER TABLE nodes ADD COLUMN expanded INTEGER NOT NULL DEFAULT 0"
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
            self._con.execute(
                "INSERT INTO tracks_fts (rowid, artist, title, album, filename)"
                " SELECT id, artist, title, album, filename FROM tracks"
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
        bpm: float | None = None,
        key: str | None = None,
        energy: int | None = None,
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
            "bpm": bpm,
            "key": key,
            "energy": energy,
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
        blob = _make_search_blob(tags["artist"] or "", tags["title"] or "", tags["album"] or "", filename)
        with self._con:
            cur = self._con.execute(
                """
                INSERT INTO tracks
                    (path, filename, artist, title, album, genre, bpm, "key",
                     energy, duration, size, mtime, content_id, search_blob, added_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    path,
                    filename,
                    tags["artist"] or "",
                    tags["title"] or "",
                    tags["album"] or "",
                    tags["genre"] or "",
                    tags["bpm"],
                    tags["key"] or "",
                    tags["energy"],
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
                self._con.execute(
                    "INSERT INTO tracks_fts (rowid, artist, title, album, filename)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (track_id, tags["artist"] or "", tags["title"] or "", tags["album"] or "", filename),
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
        """Update tag columns (artist/title/album/genre/bpm/key/energy/duration)."""
        unknown = set(fields) - set(_TAG_COLUMNS)
        if unknown:
            raise ValueError(f"Unknown tag column(s): {sorted(unknown)}")
        if not fields:
            return
        row = self._con.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
        if row is None:
            raise ValueError(f"No track with id {track_id}")
        merged = {c: fields.get(c, row[c]) for c in _TAG_COLUMNS}
        blob = _make_search_blob(
            str(merged["artist"]), str(merged["title"]), str(merged["album"]), row["filename"]
        )
        assignments = ", ".join(f'"{c}"=?' for c in fields)
        with self._con:
            self._con.execute(
                f"UPDATE tracks SET {assignments}, search_blob=? WHERE id=?",
                [*fields.values(), blob, track_id],
            )
            if self._has_fts:
                self._con.execute(
                    "UPDATE tracks_fts SET artist=?, title=?, album=? WHERE rowid=?",
                    (merged["artist"], merged["title"], merged["album"], track_id),
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
                    "SELECT id, artist, title, album FROM tracks WHERE path=?",
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
                blob = _make_search_blob(row["artist"], row["title"], row["album"], filename)
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
            blob = _make_search_blob(
                row["artist"], row["title"], row["album"], filename
            )
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
                    bpm=t.bpm,
                    key=t.key,
                    energy=t.energy,
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
        bpm=row["bpm"],
        key=row["key"],
        energy=row["energy"],
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
