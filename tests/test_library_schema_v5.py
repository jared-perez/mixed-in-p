"""Schema v5: the derived keycode, four forward-only columns, two backfills.

One migration serving three plans, so the rules it follows matter more than
the columns it adds:

* **Columns** are keyed on `PRAGMA table_info`, **recomputes** on
  `user_version` — the two triggers, for the reasons in CLAUDE.md.
* `keycode` is *derived*. It is not a tag column and no caller may set one;
  it follows `key` wherever `key` is written, so the two cannot drift.
* `year`, `track_number`, `label` and `bitrate` are **forward-only**. They
  live in the files' tags, and a migration that opened every file in a large
  library at first launch is not something a user should have to sit through.
  Old rows stay blank until something touches them.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.library import Library

V5_COLUMNS = ("keycode", "year", "track_number", "label", "bitrate")


def make_files(tmp_path, *names):
    paths = []
    for name in names:
        f = tmp_path / name
        f.write_bytes(b"audio-" + name.encode())
        paths.append(str(f))
    return paths


def roll_back_to_v4(db) -> None:
    """Take a freshly created v5 database back to the shape v1.4.0 shipped.

    The same trick the pre-v3 test uses: build the current schema, then undo
    it, so the fixture can't drift away from what is actually in `_SCHEMA`.
    """
    con = sqlite3.connect(db)
    for column in V5_COLUMNS:
        con.execute(f"ALTER TABLE tracks DROP COLUMN {column}")
    con.execute("PRAGMA user_version=4")
    con.commit()
    con.close()


@pytest.fixture
def v4_db(tmp_path):
    """A v4 database with a row in it, ready to be upgraded."""
    db = tmp_path / "library.db"
    with Library(db):
        pass
    roll_back_to_v4(db)
    return db


def add_v4_row(db, path: str, *, key: str = "", comment: str = "", energy=None) -> int:
    """Insert a row the way v4 would have, bypassing the v5 code entirely."""
    con = sqlite3.connect(db)
    cur = con.execute(
        'INSERT INTO tracks (path, filename, "key", comment, energy, added_at)'
        " VALUES (?, ?, ?, ?, ?, 'then')",
        (path, path.rsplit("/", 1)[-1], key, comment, energy),
    )
    con.commit()
    track_id = cur.lastrowid
    con.close()
    return track_id


def read_row(db, track_id: int) -> dict:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
    con.close()
    return dict(row)


class TestTheUpgrade:
    def test_a_v4_database_gains_every_column(self, v4_db):
        with Library(v4_db) as lib:
            columns = {
                r["name"] for r in lib._con.execute("PRAGMA table_info(tracks)")
            }
        assert set(V5_COLUMNS) <= columns

    def test_it_is_idempotent(self, v4_db, tmp_path):
        (path,) = make_files(tmp_path, "one.aiff")
        track_id = add_v4_row(v4_db, path, key="Am")
        for _ in range(3):
            with Library(v4_db) as lib:
                assert lib.get_track(track_id).keycode == "8A"

    def test_a_fresh_database_is_stamped_v5(self, tmp_path):
        db = tmp_path / "library.db"
        with Library(db) as lib:
            (version,) = lib._con.execute("PRAGMA user_version").fetchone()
        assert version == 5


class TestKeycodeBackfill:
    def test_a_note_name_becomes_a_code(self, v4_db, tmp_path):
        (path,) = make_files(tmp_path, "one.aiff")
        track_id = add_v4_row(v4_db, path, key="Am")

        with Library(v4_db) as lib:
            assert lib.get_track(track_id).keycode == "8A"

    def test_a_key_that_is_already_a_code_survives(self, v4_db, tmp_path):
        """The case the real library was full of, and the reason
        key_to_keycode had to learn to accept one: before, this raised and
        the row was left with no keycode at all."""
        (path,) = make_files(tmp_path, "one.aiff")
        track_id = add_v4_row(v4_db, path, key="12a")

        with Library(v4_db) as lib:
            assert lib.get_track(track_id).keycode == "12A"

    def test_a_wordy_spelling_is_understood(self, v4_db, tmp_path):
        (path,) = make_files(tmp_path, "one.aiff")
        track_id = add_v4_row(v4_db, path, key="F# minor")

        with Library(v4_db) as lib:
            assert lib.get_track(track_id).keycode == "11A"

    def test_an_unparseable_key_is_left_blank_not_guessed(self, v4_db, tmp_path):
        (path,) = make_files(tmp_path, "one.aiff")
        track_id = add_v4_row(v4_db, path, key="Ionian-ish")

        with Library(v4_db) as lib:
            track = lib.get_track(track_id)
        assert track.keycode == ""
        assert track.key == "Ionian-ish"  # the original is never rewritten


class TestEnergyBackfill:
    """Only what this app itself wrote, and only where the read is certain."""

    def _energy_after_migration(self, db, tmp_path, comment, name="one.aiff"):
        (path,) = make_files(tmp_path, name)
        track_id = add_v4_row(db, path, comment=comment)
        with Library(db) as lib:
            return lib.get_track(track_id).energy

    def test_the_labelled_format_is_unmistakable(self, v4_db, tmp_path):
        assert self._energy_after_migration(
            v4_db, tmp_path, "Energy 7 - 8A - visit my webpage"
        ) == 7

    def test_a_bare_number_counts_when_a_key_sits_beside_it(self, v4_db, tmp_path):
        """The app's own default format: '<energy> - <key> - <existing>'."""
        assert self._energy_after_migration(
            v4_db, tmp_path, "6 - 8A - visit my webpage"
        ) == 6

    def test_the_key_may_come_first(self, v4_db, tmp_path):
        """energy_written_first=False writes '<key> - <energy>'."""
        assert self._energy_after_migration(v4_db, tmp_path, "8A - 6 - notes") == 6

    def test_append_mode_puts_it_at_the_end(self, v4_db, tmp_path):
        assert self._energy_after_migration(v4_db, tmp_path, "notes - 6 - 8A") == 6

    def test_a_lone_bare_number_stays_unknown(self, v4_db, tmp_path):
        """'7 - Heaven' is a real comment, not an energy of 7. A wrong energy
        is worse than none: the compatible-tracks ranking would order by it."""
        assert self._energy_after_migration(v4_db, tmp_path, "7 - Heaven") is None

    def test_a_comment_that_is_only_a_number_stays_unknown(self, v4_db, tmp_path):
        """Found in the real library. Ambiguous with a rating or a crate
        number, so it is left for the next analysis to fill in."""
        assert self._energy_after_migration(v4_db, tmp_path, "4") is None

    def test_a_number_out_of_range_is_not_an_energy(self, v4_db, tmp_path):
        assert self._energy_after_migration(v4_db, tmp_path, "12 - 8A") is None

    def test_an_existing_energy_is_never_overwritten(self, v4_db, tmp_path):
        (path,) = make_files(tmp_path, "one.aiff")
        track_id = add_v4_row(v4_db, path, comment="Energy 7 - 8A", energy=3)

        with Library(v4_db) as lib:
            assert lib.get_track(track_id).energy == 3

    def test_it_runs_once_and_not_again(self, v4_db, tmp_path):
        """Keyed on user_version precisely so a user who clears an energy
        doesn't find it restored at the next launch."""
        (path,) = make_files(tmp_path, "one.aiff")
        track_id = add_v4_row(v4_db, path, comment="Energy 7 - 8A")
        with Library(v4_db) as lib:
            assert lib.get_track(track_id).energy == 7
            lib._con.execute("UPDATE tracks SET energy=NULL WHERE id=?", (track_id,))
            lib._con.commit()

        with Library(v4_db) as lib:
            assert lib.get_track(track_id).energy is None


class TestForwardOnlyColumns:
    def test_the_migration_opens_no_files(self, v4_db, tmp_path):
        """A real, tagged file on an upgrading row still comes back blank.

        This is the decided behaviour, not a shortcoming: reading thousands
        of files at first launch is not something a migration may do. The
        fields fill in as tracks are added, reloaded or analysed.
        """
        sf = pytest.importorskip("soundfile")
        np = pytest.importorskip("numpy")
        path = tmp_path / "tagged.flac"
        sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
        from src.metadata.tags import TrackMetadata, write_metadata

        write_metadata(str(path), TrackMetadata(year=1998, label="Metalheadz"))
        track_id = add_v4_row(v4_db, str(path))

        with Library(v4_db) as lib:
            track = lib.get_track(track_id)

        assert track.year is None
        assert track.label is None
        assert track.bitrate is None

    def test_they_round_trip_when_a_caller_supplies_them(self, tmp_path):
        db = tmp_path / "library.db"
        (path,) = make_files(tmp_path, "one.aiff")
        with Library(db) as lib:
            track_id = lib.add_track(
                path, year="1998", track_number="3", label="Metalheadz", bitrate=320
            )
            track = lib.get_track(track_id)

        assert (track.year, track.track_number, track.label, track.bitrate) == (
            "1998",
            "3",
            "Metalheadz",
            320,
        )

    def test_they_can_be_updated_later(self, tmp_path):
        db = tmp_path / "library.db"
        (path,) = make_files(tmp_path, "one.aiff")
        with Library(db) as lib:
            track_id = lib.add_track(path)
            lib.update_track_tags(track_id, label="Hospital", bitrate=192)
            track = lib.get_track(track_id)

        assert track.label == "Hospital"
        assert track.bitrate == 192


class TestKeycodeIsDerivedNotStored:
    def test_adding_a_track_derives_it(self, tmp_path):
        db = tmp_path / "library.db"
        (path,) = make_files(tmp_path, "one.aiff")
        with Library(db) as lib:
            track_id = lib.add_track(path, key="Gm")
            assert lib.get_track(track_id).keycode == "6A"

    def test_updating_the_key_moves_the_code_with_it(self, tmp_path):
        """The reason this lives inside update_track_tags: a call site that
        wrote one without the other would leave the query matching a key the
        track no longer has."""
        db = tmp_path / "library.db"
        (path,) = make_files(tmp_path, "one.aiff")
        with Library(db) as lib:
            track_id = lib.add_track(path, key="Gm")
            lib.update_track_tags(track_id, key="Am")
            assert lib.get_track(track_id).keycode == "8A"

    def test_clearing_the_key_clears_the_code(self, tmp_path):
        db = tmp_path / "library.db"
        (path,) = make_files(tmp_path, "one.aiff")
        with Library(db) as lib:
            track_id = lib.add_track(path, key="Gm")
            lib.update_track_tags(track_id, key="")
            assert lib.get_track(track_id).keycode == ""

    def test_an_unrelated_update_leaves_it_alone(self, tmp_path):
        db = tmp_path / "library.db"
        (path,) = make_files(tmp_path, "one.aiff")
        with Library(db) as lib:
            track_id = lib.add_track(path, key="Gm")
            lib.update_track_tags(track_id, artist="Photek")
            assert lib.get_track(track_id).keycode == "6A"

    def test_no_caller_may_set_one_directly(self, tmp_path):
        db = tmp_path / "library.db"
        (path,) = make_files(tmp_path, "one.aiff")
        with Library(db) as lib:
            track_id = lib.add_track(path)
            with pytest.raises(ValueError):
                lib.update_track_tags(track_id, keycode="8A")


class TestSearchIsUntouched:
    def test_no_new_field_became_searchable(self, tmp_path):
        """Decided: making label searchable is the FTS + search_blob migration,
        and it belongs to the Discogs work, where label data starts arriving."""
        from src.library.library import _FTS_COLUMNS

        assert _FTS_COLUMNS == ("artist", "title", "album", "filename", "comment", "key")

    def test_a_label_is_stored_but_not_found_by_search(self, tmp_path):
        db = tmp_path / "library.db"
        (path,) = make_files(tmp_path, "one.aiff")
        with Library(db) as lib:
            if not lib.has_fts:
                pytest.skip("FTS5 unavailable in this Python build")
            track_id = lib.add_track(path, artist="Anz", label="Metalheadz")
            assert lib.get_track(track_id).label == "Metalheadz"
            assert lib.search("Metalheadz") == []
