"""Schema v7: the release *description*, and a memory for files with no row.

v6 stored an identity and nothing else, which meant a file whose release was
perfectly well known could still only be shown a release number. Two tables:

* ``discogs_releases`` — what a provider said, cached per release, so a panel
  can describe it on load. JSON rather than columns, because the field set is
  Discogs' to change and nothing queries it;
* ``discogs_path_releases`` — which release a *file* was tagged from when that
  file has no ``tracks`` row, which is the ordinary case for one dropped
  straight onto the Metadata panel.

The second one only earns its place if it cannot drift from the column it
duplicates, so most of what is tested here is the precedence rule.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.library import Library
from src.library.library import _SCHEMA_VERSION


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "library.db")
    yield library
    library.close()


def roll_back_to_v6(db) -> None:
    """A freshly created v7 database, taken back to the shape v6 shipped.

    Built by undoing the current schema rather than by hand, so the fixture
    cannot drift away from what `_SCHEMA` says.
    """
    con = sqlite3.connect(db)
    con.execute("DROP TABLE discogs_releases")
    con.execute("DROP TABLE discogs_path_releases")
    con.execute("PRAGMA user_version=6")
    con.commit()
    con.close()


class TestTheUpgrade:
    def test_a_v6_database_gains_both_tables_on_open(self, tmp_path):
        """Whole tables, so `CREATE TABLE IF NOT EXISTS` in _SCHEMA is the
        whole migration — an ALTER is only ever needed for a new *column*."""
        db = tmp_path / "library.db"
        with Library(db):
            pass
        roll_back_to_v6(db)

        with Library(db) as lib:
            names = {
                row[0]
                for row in lib._con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        assert {"discogs_releases", "discogs_path_releases"} <= names

    def test_the_version_is_stamped(self, tmp_path):
        """Against the constant, not a literal — what this guards is that a
        new database is stamped at all rather than left at 0. The `>= 7` is
        the part that is about v7: it shipped, so anything below it is older.
        Written as `== 7` at first, which turned the next schema bump into a
        failing test about nothing."""
        with Library(tmp_path / "library.db") as lib:
            (version,) = lib._con.execute("PRAGMA user_version").fetchone()
        assert version == _SCHEMA_VERSION >= 7

    def test_a_v6_release_id_still_answers_after_the_upgrade(self, tmp_path):
        """The column v6 shipped is still the answer where it has one."""
        db = tmp_path / "library.db"
        with Library(db) as lib:
            track_id = lib.add_track("/music/a.flac")
            lib.set_release_id(track_id, 249504)
        roll_back_to_v6(db)

        with Library(db) as lib:
            assert lib.release_for_path("/music/a.flac") == 249504


class TestReleaseMemory:
    def test_a_file_with_no_row_is_remembered(self, lib):
        """The bug this table exists for: the Metadata panel takes a file
        without importing it, so a lookup was applied and forgotten at once."""
        lib.remember_release_for_path("/elsewhere/b.flac", 1722954)

        assert lib.release_for_path("/elsewhere/b.flac") == 1722954

    def test_a_file_with_a_row_is_remembered_on_the_row(self, lib):
        lib.add_track("/music/a.flac")
        lib.remember_release_for_path("/music/a.flac", 249504)

        assert lib.get_track_by_path("/music/a.flac").discogs_release_id == 249504
        stored = lib._con.execute(
            "SELECT COUNT(*) FROM discogs_path_releases"
        ).fetchone()[0]
        # Never both: two records of one fact is how they drift.
        assert stored == 0

    def test_the_row_wins_when_both_could_answer(self, lib):
        lib.remember_release_for_path("/music/a.flac", 111)
        lib.add_track("/music/a.flac")
        lib.set_release_id(lib.get_track_by_path("/music/a.flac").id, 222)

        assert lib.release_for_path("/music/a.flac") == 222

    def test_joining_the_library_promotes_the_memory(self, lib):
        """Without this, a release approved before the file was imported is
        answered forever by the weaker record — and adding it to a playlist
        would silently lose it."""
        lib.remember_release_for_path("/music/a.flac", 1722954)
        lib.add_track("/music/a.flac")  # no release of its own

        assert lib.release_for_path("/music/a.flac") == 1722954
        # Promoted onto the row, and the weaker record dropped.
        assert lib.get_track_by_path("/music/a.flac").discogs_release_id == 1722954
        assert lib._con.execute(
            "SELECT COUNT(*) FROM discogs_path_releases"
        ).fetchone()[0] == 0

    def test_forgetting_clears_whichever_record_exists(self, lib):
        """"No release" is an answer: a stale one would seed the next lookup
        with a release the user has just rejected."""
        lib.remember_release_for_path("/elsewhere/b.flac", 1)
        lib.remember_release_for_path("/elsewhere/b.flac", None)
        assert lib.release_for_path("/elsewhere/b.flac") is None

        lib.add_track("/music/a.flac")
        lib.remember_release_for_path("/music/a.flac", 2)
        lib.remember_release_for_path("/music/a.flac", None)
        assert lib.release_for_path("/music/a.flac") is None

    def test_an_unknown_file_answers_none(self, lib):
        assert lib.release_for_path("/nowhere/c.flac") is None


class TestReleaseCache:
    def test_what_goes_in_comes_back(self, lib):
        lib.cache_release(249504, {"album": "Second Toughest", "year": 1996})
        facts, fetched_at = lib.cached_release(249504)

        assert facts["album"] == "Second Toughest"
        assert fetched_at

    def test_a_second_read_replaces_rather_than_merges(self, lib):
        """Refresh means "read it again". A merge would let a field the release
        no longer carries outlive the reading that dropped it."""
        lib.cache_release(249504, {"album": "A", "country": "UK"})
        lib.cache_release(249504, {"album": "A"})

        facts, _ = lib.cached_release(249504)
        assert "country" not in facts

    def test_an_uncached_release_is_none_not_an_error(self, lib):
        assert lib.cached_release(999) is None
        assert lib.cached_release(0) is None

    def test_unreadable_json_reads_as_absent(self, lib):
        """A cache whose row is truncated must not raise in the middle of a
        panel load: the recovery is to fetch again."""
        lib.cache_release(1, {"album": "A"})
        with lib._con:
            lib._con.execute("UPDATE discogs_releases SET facts='{not json'")

        assert lib.cached_release(1) is None
