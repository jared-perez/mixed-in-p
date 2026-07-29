"""Missing-file relocate: detection, matching, and relinking (step 10)."""

from pathlib import Path

import pytest

from src.library import SCRATCH_NODE_ID, Library, compute_content_id
from src.library.relocate import (
    BY_CONTENT,
    BY_FILENAME,
    apply_matches,
    find_matches,
    missing_tracks,
    scan_folder,
)


@pytest.fixture(params=["fts", "like"])
def lib(request, tmp_path):
    """A fresh library, run once with FTS5 and once on the LIKE fallback.

    Relinking rewrites the filename in both the FTS index and the
    search_blob, so both halves need the round trip.
    """
    library = Library(tmp_path / "library.db", enable_fts=request.param == "fts")
    yield library
    library.close()


def write(path, payload=b"audio-bytes"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def add(lib, path, node_id=SCRATCH_NODE_ID, **tags):
    """Add a file to the library and put it in a playlist."""
    track_id = lib.add_track(str(path), **tags)
    lib.add_items(node_id, [track_id])
    return track_id


class TestMissingTracks:
    def test_reports_only_files_that_are_gone(self, lib, tmp_path):
        here = write(tmp_path / "here.wav")
        gone = write(tmp_path / "gone.wav", b"other-bytes")
        add(lib, here)
        add(lib, gone)
        gone.unlink()

        missing = missing_tracks(lib)
        assert [t.path for t in missing] == [str(gone)]

    def test_empty_library_is_not_missing_anything(self, lib):
        assert missing_tracks(lib) == []

    def test_accepts_a_subset(self, lib, tmp_path):
        a = write(tmp_path / "a.wav", b"aaa")
        b = write(tmp_path / "b.wav", b"bbb")
        add(lib, a)
        add(lib, b)
        a.unlink()
        b.unlink()

        subset = [lib.get_track_by_path(str(b))]
        assert [t.path for t in missing_tracks(lib, subset)] == [str(b)]


class TestScanFolder:
    def test_finds_audio_recursively_and_skips_the_rest(self, tmp_path):
        write(tmp_path / "a.wav")
        write(tmp_path / "deep" / "b.mp3")
        write(tmp_path / "notes.txt")

        found = {p.name for p in scan_folder(tmp_path)}
        assert found == {"a.wav", "b.mp3"}

    def test_prunes_hidden_directories(self, tmp_path):
        write(tmp_path / "keep.wav")
        write(tmp_path / ".Trashes" / "deleted.wav")

        assert {p.name for p in scan_folder(tmp_path)} == {"keep.wav"}

    def test_stops_when_cancelled(self, tmp_path):
        write(tmp_path / "a.wav")
        assert scan_folder(tmp_path, is_cancelled=lambda: True) == []


class TestRelinkTrack:
    def test_moves_the_row_and_keeps_membership(self, lib, tmp_path):
        original = write(tmp_path / "old" / "song.wav")
        track_id = add(lib, original)
        moved = write(tmp_path / "new" / "song.wav")
        original.unlink()

        assert lib.relink_track(track_id, moved) == track_id
        track = lib.get_track(track_id)
        assert track.path == str(moved)
        assert track.filename == "song.wav"
        assert [t.id for t in lib.get_items(SCRATCH_NODE_ID)] == [track_id]

    def test_recomputes_the_fingerprint(self, lib, tmp_path):
        original = write(tmp_path / "song.wav", b"first-encoding")
        track_id = add(lib, original)
        # A re-encode is a different file, and the row must describe the
        # file it now points at — not the one it used to.
        replacement = write(tmp_path / "re" / "song.wav", b"second-encoding-x")
        original.unlink()

        lib.relink_track(track_id, replacement)
        track = lib.get_track(track_id)
        assert track.content_id == compute_content_id(replacement)
        assert track.size == replacement.stat().st_size

    def test_merges_when_the_target_is_already_in_the_library(self, lib, tmp_path):
        moved = write(tmp_path / "new" / "song.wav")
        gone = write(tmp_path / "old" / "song.wav", b"different")
        keeper = add(lib, moved)
        stale = add(lib, gone)
        gone.unlink()

        survivor = lib.relink_track(stale, moved)
        assert survivor == keeper
        assert lib.get_track(stale) is None
        # The playlist held both rows, so it now holds the survivor twice —
        # duplicates within a playlist are allowed by design.
        assert [t.id for t in lib.get_items(SCRATCH_NODE_ID)] == [keeper, keeper]

    def test_unknown_track_raises(self, lib, tmp_path):
        with pytest.raises(ValueError):
            lib.relink_track(999, write(tmp_path / "x.wav"))

    def test_relinked_row_is_searchable_under_its_new_name(self, lib, tmp_path):
        original = write(tmp_path / "oldname.wav")
        track_id = add(lib, original)
        moved = write(tmp_path / "newname.wav")
        original.unlink()

        lib.relink_track(track_id, moved)
        assert lib.search("newname") == [track_id]


class TestFindMatches:
    def test_matches_a_whole_moved_folder_by_content(self, lib, tmp_path):
        source = tmp_path / "source"
        a = write(source / "a.wav", b"aaaaaaaa")
        b = write(source / "b.wav", b"bbbbbbbbbb")
        add(lib, a)
        add(lib, b)
        # The folder moved wholesale, and the names changed on the way.
        destination = tmp_path / "moved"
        write(destination / "renamed-a.wav", b"aaaaaaaa")
        write(destination / "sub" / "renamed-b.wav", b"bbbbbbbbbb")
        a.unlink()
        b.unlink()

        result = find_matches(missing_tracks(lib), destination)
        assert result.unmatched == []
        assert {m.matched_by for m in result.matches} == {BY_CONTENT}
        assert {Path(m.new_path).name for m in result.matches} == {
            "renamed-a.wav",
            "renamed-b.wav",
        }

    def test_falls_back_to_a_unique_filename(self, lib, tmp_path):
        original = write(tmp_path / "song.wav", b"original-bytes")
        add(lib, original)
        original.unlink()
        # Re-encoded: same name, different bytes, so only the name can match.
        replacement = write(tmp_path / "converted" / "song.mp3", b"re-encoded")

        result = find_matches(missing_tracks(lib), tmp_path / "converted")
        assert [(m.new_path, m.matched_by) for m in result.matches] == [
            (str(replacement), BY_FILENAME)
        ]

    def test_ambiguous_filenames_are_left_alone(self, lib, tmp_path):
        original = write(tmp_path / "song.wav", b"original-bytes")
        add(lib, original)
        original.unlink()
        write(tmp_path / "candidates" / "one" / "song.wav", b"guess-one")
        write(tmp_path / "candidates" / "two" / "song.wav", b"guess-two")

        result = find_matches(missing_tracks(lib), tmp_path / "candidates")
        assert result.matches == []
        assert len(result.unmatched) == 1

    def test_one_candidate_is_claimed_by_one_track(self, lib, tmp_path):
        # Two library rows, identical contents, one surviving copy: relinking
        # both onto it would violate the path UNIQUE constraint.
        first = write(tmp_path / "one" / "same.wav", b"identical")
        second = write(tmp_path / "two" / "same.wav", b"identical")
        add(lib, first)
        add(lib, second)
        first.unlink()
        second.unlink()
        survivor = write(tmp_path / "kept" / "same.wav", b"identical")

        result = find_matches(missing_tracks(lib), tmp_path / "kept")
        assert [m.new_path for m in result.matches] == [str(survivor)]
        assert len(result.unmatched) == 1

    def test_reports_progress_and_scan_size(self, lib, tmp_path):
        gone = write(tmp_path / "gone.wav", b"zzz")
        add(lib, gone)
        gone.unlink()
        write(tmp_path / "pool" / "found.wav", b"zzz")
        write(tmp_path / "pool" / "other.wav", b"qqq")

        seen = []
        result = find_matches(
            missing_tracks(lib),
            tmp_path / "pool",
            on_progress=lambda done, total, name: seen.append((done, total)),
        )
        assert result.scanned == 2
        assert seen[-1] == (2, 2)  # always ends at 100%

    def test_cancelled_scan_matches_nothing(self, lib, tmp_path):
        gone = write(tmp_path / "gone.wav", b"zzz")
        add(lib, gone)
        gone.unlink()
        write(tmp_path / "pool" / "found.wav", b"zzz")

        result = find_matches(
            missing_tracks(lib), tmp_path / "pool", is_cancelled=lambda: True
        )
        assert result.matches == []


class TestApplyMatches:
    def test_relinks_every_match(self, lib, tmp_path):
        a = write(tmp_path / "src" / "a.wav", b"aaaa")
        b = write(tmp_path / "src" / "b.wav", b"bbbb")
        add(lib, a)
        add(lib, b)
        write(tmp_path / "dst" / "a.wav", b"aaaa")
        write(tmp_path / "dst" / "b.wav", b"bbbb")
        a.unlink()
        b.unlink()

        result = find_matches(missing_tracks(lib), tmp_path / "dst")
        assert apply_matches(lib, result.matches) == 2
        assert missing_tracks(lib) == []
        assert [t.path for t in lib.get_items(SCRATCH_NODE_ID)] == [
            str(tmp_path / "dst" / "a.wav"),
            str(tmp_path / "dst" / "b.wav"),
        ]

    def test_a_row_that_vanished_does_not_abort_the_batch(self, lib, tmp_path):
        a = write(tmp_path / "src" / "a.wav", b"aaaa")
        b = write(tmp_path / "src" / "b.wav", b"bbbb")
        add(lib, a)
        track_b = add(lib, b)
        write(tmp_path / "dst" / "a.wav", b"aaaa")
        write(tmp_path / "dst" / "b.wav", b"bbbb")
        a.unlink()
        b.unlink()

        result = find_matches(missing_tracks(lib), tmp_path / "dst")
        # Simulate the shared library changing under the scan.
        lib.set_items(SCRATCH_NODE_ID, [t.id for t in lib.get_items(SCRATCH_NODE_ID) if t.id != track_b])
        assert lib.get_track(track_b) is None

        assert apply_matches(lib, result.matches) == 1
