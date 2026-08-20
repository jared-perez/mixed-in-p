"""Schema v6: the approved Discogs release, remembered as an identity.

One column, and the three rules it has to follow:

* it is keyed on `PRAGMA table_info`, like every other column — a version
  check would skip a database touched by a build predating the bump, and
  re-adding a column is the one error there is no way back from;
* it is **not a tag**, so it is absent from `_TAG_COLUMNS` (which would reject
  it anyway) and from `_FTS_COLUMNS`, and never travels the merge/blob path;
* it stores an **identity, not content**. Nothing about the release itself is
  kept, which is what leaves the provider's freshness rule intact.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.library import Library
from src.library.library import _FTS_COLUMNS, _SCHEMA_VERSION, _TAG_COLUMNS

COLUMN = "discogs_release_id"


def roll_back_to_v5(db) -> None:
    """Take a freshly created v6 database back to the shape v5 shipped.

    Built by undoing the current schema rather than by hand, so the fixture
    cannot drift away from what `_SCHEMA` actually says.
    """
    con = sqlite3.connect(db)
    con.execute(f"ALTER TABLE tracks DROP COLUMN {COLUMN}")
    con.execute("PRAGMA user_version=5")
    con.commit()
    con.close()


@pytest.fixture
def v5_db(tmp_path):
    db = tmp_path / "library.db"
    with Library(db):
        pass
    roll_back_to_v5(db)
    return db


def add_v5_row(db, path: str) -> int:
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
    def test_a_v5_database_gains_the_column(self, v5_db):
        with Library(v5_db) as lib:
            columns = {r["name"] for r in lib._con.execute("PRAGMA table_info(tracks)")}
        assert COLUMN in columns

    def test_an_existing_row_survives_with_no_release(self, v5_db, tmp_path):
        track_id = add_v5_row(v5_db, str(tmp_path / "one.aiff"))
        with Library(v5_db) as lib:
            assert lib.get_track(track_id).discogs_release_id is None

    def test_it_is_idempotent(self, v5_db, tmp_path):
        track_id = add_v5_row(v5_db, str(tmp_path / "one.aiff"))
        for _ in range(3):
            with Library(v5_db) as lib:
                lib.set_release_id(track_id, 249504)
                assert lib.get_track(track_id).discogs_release_id == 249504

    def test_the_version_moved(self):
        # v5 shipped in 1.4.0; a database at 5 must be recognised as older.
        assert _SCHEMA_VERSION >= 6


class TestItIsNotATag:
    def test_it_is_in_neither_column_tuple(self):
        assert COLUMN not in _TAG_COLUMNS
        assert COLUMN not in _FTS_COLUMNS

    def test_update_track_tags_refuses_it(self, tmp_path):
        with Library(tmp_path / "library.db") as lib:
            track_id = lib.add_track(str(tmp_path / "one.aiff"))
            with pytest.raises(ValueError):
                lib.update_track_tags(track_id, discogs_release_id=1)

    def test_remembering_a_release_leaves_the_search_blob_alone(self, tmp_path):
        with Library(tmp_path / "library.db") as lib:
            track_id = lib.add_track(
                str(tmp_path / "one.aiff"), artist="Underworld", title="Born Slippy"
            )
            before = lib._con.execute(
                "SELECT search_blob FROM tracks WHERE id=?", (track_id,)
            ).fetchone()[0]
            lib.set_release_id(track_id, 249504)
            after = lib._con.execute(
                "SELECT search_blob FROM tracks WHERE id=?", (track_id,)
            ).fetchone()[0]
        assert before == after and before


class TestSetReleaseId:
    def test_it_round_trips_and_can_be_cleared(self, tmp_path):
        with Library(tmp_path / "library.db") as lib:
            track_id = lib.add_track(str(tmp_path / "one.aiff"))
            lib.set_release_id(track_id, 249504)
            assert lib.get_track(track_id).discogs_release_id == 249504
            lib.set_release_id(track_id, None)
            assert lib.get_track(track_id).discogs_release_id is None

    def test_a_later_tag_edit_does_not_forget_it(self, tmp_path):
        # update_track_tags rebuilds the row from _TAG_COLUMNS; a column it has
        # never heard of must survive that untouched.
        with Library(tmp_path / "library.db") as lib:
            track_id = lib.add_track(str(tmp_path / "one.aiff"))
            lib.set_release_id(track_id, 249504)
            lib.update_track_tags(track_id, artist="Underworld")
            track = lib.get_track(track_id)
        assert track.artist == "Underworld"
        assert track.discogs_release_id == 249504
