"""Schema v8: the stream's bit depth, so the Player's column is free to draw.

One column, and it is the same shape as v5's four: keyed on
`PRAGMA table_info` rather than on `user_version`, and **forward-only** — the
number lives in the file, and a migration that opened every file in a large
library at first launch is not something a user should have to sit through.

What is different from v5's four is where the value comes from and therefore
who fills it in. Year, track number and label are tags, so any tag read
carries them along. A bit depth is not a tag at all: it is a property of the
stream, so a fully-tagged row would never be opened for one, and the Player
asks for it deliberately — once, for lossless files whose depth it does not
already hold, storing what it read (see `test_player_format_columns.py`).

It is nonetheless a member of `_TAG_COLUMNS`, which is really "columns a
caller may write", the same way `bitrate` and `duration` are: that is what
makes `update_track_tags(id, bit_depth=…)` the one door, and what keeps a
later tag edit from dropping it.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.library import Library
from src.library.library import _FTS_COLUMNS, _SCHEMA_VERSION, _TAG_COLUMNS

COLUMN = "bit_depth"


def roll_back_to_v7(db) -> None:
    """Take a freshly created v8 database back to the shape v7 shipped.

    Built by undoing the current schema rather than by hand, so the fixture
    cannot drift away from what `_SCHEMA` actually says.
    """
    con = sqlite3.connect(db)
    con.execute(f"ALTER TABLE tracks DROP COLUMN {COLUMN}")
    con.execute("PRAGMA user_version=7")
    con.commit()
    con.close()


@pytest.fixture
def v7_db(tmp_path):
    db = tmp_path / "library.db"
    with Library(db):
        pass
    roll_back_to_v7(db)
    return db


def add_v7_row(db, path: str) -> int:
    """Insert a row the way v7 would have, bypassing the v8 code entirely."""
    con = sqlite3.connect(db)
    cur = con.execute(
        "INSERT INTO tracks (path, filename, added_at) VALUES (?, ?, 'then')",
        (path, path.rsplit("/", 1)[-1]),
    )
    con.commit()
    track_id = cur.lastrowid
    con.close()
    return track_id


class TestTheUpgrade:
    def test_a_v7_database_gains_the_column(self, v7_db):
        with Library(v7_db) as lib:
            columns = {r["name"] for r in lib._con.execute("PRAGMA table_info(tracks)")}
        assert COLUMN in columns

    def test_an_existing_row_survives_with_no_depth(self, v7_db, tmp_path):
        track_id = add_v7_row(v7_db, str(tmp_path / "one.aiff"))
        with Library(v7_db) as lib:
            assert lib.get_track(track_id).bit_depth is None

    def test_it_is_idempotent(self, v7_db, tmp_path):
        track_id = add_v7_row(v7_db, str(tmp_path / "one.aiff"))
        for _ in range(3):
            with Library(v7_db) as lib:
                lib.update_track_tags(track_id, bit_depth=24)
                assert lib.get_track(track_id).bit_depth == 24

    def test_the_migration_opens_no_files(self, v7_db, tmp_path):
        """Forward-only means exactly this: a first launch after an upgrade
        must not read a whole library's worth of audio to fill a column in."""
        missing = str(tmp_path / "nowhere" / "gone.aiff")
        track_id = add_v7_row(v7_db, missing)

        with Library(v7_db) as lib:  # no FileNotFoundError, no stall
            assert lib.get_track(track_id).bit_depth is None

    def test_a_fresh_database_is_stamped_with_the_current_version(self, tmp_path):
        db = tmp_path / "library.db"
        with Library(db) as lib:
            (version,) = lib._con.execute("PRAGMA user_version").fetchone()
        assert version == _SCHEMA_VERSION

    def test_the_version_moved(self):
        assert _SCHEMA_VERSION >= 8


class TestTheColumnItself:
    def test_a_caller_may_write_it_and_read_it_back(self, tmp_path):
        with Library(tmp_path / "library.db") as lib:
            track_id = lib.add_track(str(tmp_path / "one.aiff"), bit_depth=24)
            assert lib.get_track(track_id).bit_depth == 24

    def test_none_leaves_a_known_depth_alone(self, tmp_path):
        """`add_track`'s rule for every field: only non-None overwrites, so a
        caller with partial information never blanks out what is known."""
        with Library(tmp_path / "library.db") as lib:
            path = str(tmp_path / "one.aiff")
            track_id = lib.add_track(path, bit_depth=24)
            lib.add_track(path, artist="Photek")
            track = lib.get_track(track_id)
        assert track.artist == "Photek"
        assert track.bit_depth == 24

    def test_a_later_tag_edit_does_not_forget_it(self, tmp_path):
        with Library(tmp_path / "library.db") as lib:
            track_id = lib.add_track(str(tmp_path / "one.aiff"), bit_depth=16)
            lib.update_track_tags(track_id, artist="Photek")
            track = lib.get_track(track_id)
        assert track.artist == "Photek"
        assert track.bit_depth == 16

    def test_it_is_writable_but_not_searchable(self):
        """A number nobody would type into a search box, and one whose column
        in `tracks_fts` would cost an index rebuild for nothing."""
        assert COLUMN in _TAG_COLUMNS
        assert COLUMN not in _FTS_COLUMNS

    def test_setting_it_leaves_the_search_blob_alone(self, tmp_path):
        with Library(tmp_path / "library.db") as lib:
            track_id = lib.add_track(
                str(tmp_path / "one.aiff"), artist="Photek", title="Ni Ten Ichi Ryu"
            )
            before = lib._con.execute(
                "SELECT search_blob FROM tracks WHERE id=?", (track_id,)
            ).fetchone()[0]
            lib.update_track_tags(track_id, bit_depth=24)
            after = lib._con.execute(
                "SELECT search_blob FROM tracks WHERE id=?", (track_id,)
            ).fetchone()[0]
        assert before == after and before
