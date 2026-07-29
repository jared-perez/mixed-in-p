"""Playlist file writers: .m3u8 / .m3u / .txt (§5, §6).

The rules that DJ software actually depends on: UTF-8 and CRLF everywhere
(anything else imports as an empty crate in Serato), relative paths only
when they can genuinely resolve, and playlist names that survive becoming
filenames.
"""

from pathlib import Path

import pytest

from src.library.playlist_export import (
    ExportTrack,
    safe_filename,
    unique_path,
    write_playlist,
)


def make_tracks(directory, *names, **kwargs):
    tracks = []
    for name in names:
        f = Path(directory) / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"audio")
        tracks.append(ExportTrack(path=str(f), **kwargs))
    return tracks


def read(path):
    """Raw text, CRLFs intact (newline="" defeats universal-newline translation)."""
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


class TestEncoding:
    def test_always_crlf_never_bare_lf(self, tmp_path):
        tracks = make_tracks(tmp_path, "a.wav", "b.wav")
        out = tmp_path / "set.m3u8"
        write_playlist(out, tracks)
        raw = read(out)
        assert raw.endswith("\r\n")
        assert "\n" not in raw.replace("\r\n", "")

    def test_utf8_even_for_plain_m3u(self, tmp_path):
        # The old convention said .m3u is system-codepage; every current
        # player reads UTF-8, and the alternative mangles artist names.
        tracks = make_tracks(tmp_path, "t.wav")
        tracks = [ExportTrack(tracks[0].path, artist="Björk", title="Jóga")]
        out = tmp_path / "set.m3u"
        write_playlist(out, tracks)
        assert "Björk - Jóga" in read(out)
        assert out.read_bytes().startswith(b"#EXTM3U")  # no BOM

    def test_txt_is_utf8_and_crlf_too(self, tmp_path):
        tracks = [ExportTrack("/x/a.wav", artist="Éric", title="Wave")]
        out = tmp_path / "set.txt"
        write_playlist(out, tracks, title="Set")
        assert read(out) == "Set\r\n\r\n01. Éric - Wave\r\n"


class TestM3U:
    def test_extinf_carries_duration_and_label(self, tmp_path):
        tracks = make_tracks(tmp_path, "a.wav")
        tracks = [ExportTrack(tracks[0].path, artist="DJ", title="Track", duration=245.6)]
        out = tmp_path / "set.m3u8"
        assert write_playlist(out, tracks) == 1
        lines = read(out).split("\r\n")
        assert lines[0] == "#EXTM3U"
        assert lines[1] == "#EXTINF:246,DJ - Track"

    def test_unknown_duration_is_minus_one(self, tmp_path):
        tracks = make_tracks(tmp_path, "a.wav")
        write_playlist(tmp_path / "set.m3u8", tracks)
        assert "#EXTINF:-1," in read(tmp_path / "set.m3u8")

    def test_untagged_track_labels_by_filename(self, tmp_path):
        tracks = make_tracks(tmp_path, "Some Track.wav")
        write_playlist(tmp_path / "set.m3u8", tracks)
        assert "#EXTINF:-1,Some Track" in read(tmp_path / "set.m3u8")

    def test_duplicates_are_written_once_per_entry(self, tmp_path):
        (track,) = make_tracks(tmp_path, "a.wav")
        out = tmp_path / "set.m3u8"
        assert write_playlist(out, [track, track, track]) == 3
        assert read(out).count("a.wav") == 3

    def test_empty_playlist_writes_just_the_header(self, tmp_path):
        out = tmp_path / "empty.m3u8"
        assert write_playlist(out, []) == 0
        assert read(out) == "#EXTM3U\r\n"

    def test_unknown_format_is_refused(self, tmp_path):
        with pytest.raises(ValueError):
            write_playlist(tmp_path / "set.pls", [])


class TestPathRule:
    def test_tracks_beside_the_playlist_go_relative(self, tmp_path):
        tracks = make_tracks(tmp_path, "a.wav", "b.wav")
        out = tmp_path / "set.m3u8"
        write_playlist(out, tracks)
        body = read(out)
        assert "\r\na.wav\r\n" in body
        assert str(tmp_path) not in body  # nothing machine-specific survives

    def test_tracks_in_a_subfolder_stay_relative(self, tmp_path):
        tracks = make_tracks(tmp_path, "House/a.wav", "House/b.wav")
        out = tmp_path / "set.m3u8"
        write_playlist(out, tracks)
        assert "\r\nHouse/a.wav\r\n" in read(out)

    def test_relative_lines_use_forward_slashes(self, tmp_path):
        tracks = make_tracks(tmp_path, "House/Deep/a.wav")
        out = tmp_path / "set.m3u8"
        write_playlist(out, tracks)
        assert "House/Deep/a.wav" in read(out)
        assert "\\" not in read(out)

    def test_tracks_elsewhere_go_absolute(self, tmp_path):
        # A playlist saved to the Desktop pointing at ~/Music cannot use
        # relative paths — the player would look next to the playlist.
        audio = tmp_path / "Music"
        tracks = make_tracks(audio, "a.wav")
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        out = desktop / "set.m3u8"
        write_playlist(out, tracks)
        assert str(audio.resolve() / "a.wav") in read(out)

    def test_one_stray_track_forces_the_whole_file_absolute(self, tmp_path):
        near = make_tracks(tmp_path, "a.wav")
        far = make_tracks(tmp_path.parent / "elsewhere", "b.wav")
        out = tmp_path / "set.m3u8"
        write_playlist(out, near + far)
        body = read(out)
        assert str(Path(near[0].path).resolve()) in body
        assert str(Path(far[0].path).resolve()) in body

    def test_absolute_override_wins_over_the_rule(self, tmp_path):
        tracks = make_tracks(tmp_path, "a.wav")
        out = tmp_path / "set.m3u8"
        write_playlist(out, tracks, absolute=True)
        assert str(tmp_path) in read(out)

    def test_missing_files_still_export(self, tmp_path):
        # A playlist pointing at an unplugged drive must still write; the
        # relocate flow is what fixes those, not the exporter.
        ghost = ExportTrack(path=str(tmp_path / "gone.wav"), title="Gone")
        out = tmp_path / "set.m3u8"
        assert write_playlist(out, [ghost]) == 1
        assert "gone.wav" in read(out)


class TestTxt:
    def test_numbered_running_order_with_a_title(self, tmp_path):
        tracks = [
            ExportTrack("/m/1.wav", artist="A", title="One"),
            ExportTrack("/m/2.wav", artist="B", title="Two"),
        ]
        write_playlist(tmp_path / "set.txt", tracks, title="Peak Time")
        assert read(tmp_path / "set.txt").split("\r\n") == [
            "Peak Time",
            "",
            "01. A - One",
            "02. B - Two",
            "",
        ]

    def test_numbering_widens_past_ninety_nine(self, tmp_path):
        tracks = [ExportTrack(f"/m/{i}.wav", title=f"T{i}") for i in range(1, 101)]
        write_playlist(tmp_path / "set.txt", tracks)
        lines = read(tmp_path / "set.txt").strip().split("\r\n")
        assert lines[0] == "001. T1"
        assert lines[-1] == "100. T100"

    def test_txt_carries_no_paths(self, tmp_path):
        tracks = [ExportTrack("/private/music/secret.wav", artist="A", title="One")]
        write_playlist(tmp_path / "set.txt", tracks)
        assert "/private" not in read(tmp_path / "set.txt")


class TestFilenames:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("House / Techno", "House _ Techno"),
            ("AC/DC: Live", "AC_DC_ Live"),
            ("Set *2*", "Set _2_"),
            ("trailing dots...", "trailing dots"),
            ("  padded  ", "padded"),
        ],
    )
    def test_illegal_characters_are_replaced(self, name, expected):
        assert safe_filename(name) == expected

    def test_empty_and_reserved_names_get_a_fallback(self):
        assert safe_filename("") == "Playlist"
        assert safe_filename("///") == "___"  # sanitized, but still a usable name
        assert safe_filename("CON").startswith("Playlist")
        assert safe_filename("con.m3u8").startswith("Playlist")

    def test_unicode_names_are_kept(self):
        assert safe_filename("Été 2026 · Ibiza") == "Été 2026 · Ibiza"

    def test_absurdly_long_names_are_truncated(self):
        assert len(safe_filename("x" * 500)) == 120

    def test_unique_path_disambiguates_collisions(self, tmp_path):
        first = unique_path(tmp_path, "Set", ".m3u8")
        assert first.name == "Set.m3u8"
        first.write_text("")
        second = unique_path(tmp_path, "Set", ".m3u8")
        assert second.name == "Set (2).m3u8"
        second.write_text("")
        assert unique_path(tmp_path, "Set", ".m3u8").name == "Set (3).m3u8"


class TestExportTree:
    """Folder export and §7d's Export all — one directory mirroring the tree."""

    @pytest.fixture
    def lib(self, tmp_path):
        from src.library import Library

        library = Library(tmp_path / "library.db")
        yield library
        library.close()

    def build(self, lib, tmp_path):
        from src.library import SCRATCH_NODE_ID

        audio = tmp_path / "audio"
        tracks = make_tracks(audio, "a.wav", "b.wav")
        ids = [lib.add_track(t.path, artist="DJ", title=Path(t.path).stem) for t in tracks]

        crates = lib.create_folder("Crates")
        nested = lib.create_folder("2026", crates)
        lib.set_items(lib.create_playlist("Peak", nested), ids)
        lib.set_items(lib.create_playlist("Warm", crates), ids[:1])
        lib.set_items(lib.create_playlist("Top"), ids)
        lib.create_folder("Empty")
        lib.set_items(SCRATCH_NODE_ID, ids[:1])
        return ids

    def test_mirrors_folders_as_directories(self, lib, tmp_path):
        from src.library.playlist_export import export_tree

        self.build(lib, tmp_path)
        out = tmp_path / "out"
        out.mkdir()
        playlists, tracks = export_tree(lib, out)

        assert playlists == 3
        assert tracks == 5
        assert (out / "Top.m3u8").exists()
        assert (out / "Crates" / "Warm.m3u8").exists()
        assert (out / "Crates" / "2026" / "Peak.m3u8").exists()
        assert (out / "Empty").is_dir()  # structure is part of the export

    def test_scratch_is_opt_in(self, lib, tmp_path):
        from src.library.playlist_export import export_tree

        self.build(lib, tmp_path)
        without = tmp_path / "a"
        without.mkdir()
        export_tree(lib, without)
        assert not (without / "Scratch.m3u8").exists()

        with_scratch = tmp_path / "b"
        with_scratch.mkdir()
        playlists, _ = export_tree(lib, with_scratch, include_scratch=True)
        assert (with_scratch / "Scratch.m3u8").exists()
        assert playlists == 4

    def test_subtree_export_starts_at_a_folder(self, lib, tmp_path):
        from src.library.playlist_export import export_tree

        self.build(lib, tmp_path)
        crates = next(n for n in lib.get_children(None) if n.name == "Crates")
        out = tmp_path / "out"
        out.mkdir()
        playlists, _ = export_tree(lib, out, parent_id=crates.id)

        assert playlists == 2
        assert (out / "Warm.m3u8").exists()
        assert (out / "2026" / "Peak.m3u8").exists()
        assert not (out / "Top.m3u8").exists()  # outside the chosen folder

    def test_same_named_playlists_do_not_overwrite(self, lib, tmp_path):
        from src.library.playlist_export import export_tree

        ids = self.build(lib, tmp_path)
        lib.set_items(lib.create_playlist("Top"), ids)  # a second "Top" at the root
        out = tmp_path / "out"
        out.mkdir()
        playlists, _ = export_tree(lib, out)

        assert playlists == 4
        assert (out / "Top.m3u8").exists()
        assert (out / "Top (2).m3u8").exists()

    def test_exported_paths_are_absolute_when_audio_lives_elsewhere(self, lib, tmp_path):
        from src.library.playlist_export import export_tree

        self.build(lib, tmp_path)
        out = tmp_path / "out"
        out.mkdir()
        export_tree(lib, out)
        assert str((tmp_path / "audio").resolve()) in read(out / "Top.m3u8")

    def test_format_applies_to_every_file(self, lib, tmp_path):
        from src.library.playlist_export import export_tree

        self.build(lib, tmp_path)
        out = tmp_path / "out"
        out.mkdir()
        export_tree(lib, out, fmt="txt")
        assert (out / "Top.txt").exists()
        assert read(out / "Top.txt").startswith("Top\r\n\r\n01. DJ - a")


class TestCopyTracks:
    """"Export and copy tracks" — the zip-and-send folder (§5)."""

    def test_copies_files_and_rewrites_paths(self, tmp_path):
        from src.library.playlist_export import copy_playlist_tracks

        tracks = make_tracks(tmp_path / "src", "a.wav", "b.wav")
        out = tmp_path / "Summer Set"
        out.mkdir()
        copied, missing = copy_playlist_tracks(tracks, out)

        assert missing == []
        assert [Path(t.path).name for t in copied] == ["a.wav", "b.wav"]
        assert (out / "a.wav").read_bytes() == b"audio"
        assert Path(copied[0].path).parent == out

    def test_the_result_writes_a_relative_playlist(self, tmp_path):
        from src.library.playlist_export import copy_playlist_tracks

        tracks = make_tracks(tmp_path / "src", "a.wav")
        out = tmp_path / "Summer Set"
        out.mkdir()
        copied, _ = copy_playlist_tracks(tracks, out)
        write_playlist(out / "Summer Set.m3u8", copied)

        body = read(out / "Summer Set.m3u8")
        assert "\r\na.wav\r\n" in body
        assert str(tmp_path) not in body  # portable to another machine

    def test_metadata_survives_the_copy(self, tmp_path):
        from src.library.playlist_export import copy_playlist_tracks

        (track,) = make_tracks(tmp_path / "src", "a.wav")
        track = ExportTrack(track.path, artist="DJ", title="One", duration=200.0)
        out = tmp_path / "out"
        out.mkdir()
        (copied,), _ = copy_playlist_tracks([track], out)
        assert (copied.artist, copied.title, copied.duration) == ("DJ", "One", 200.0)

    def test_a_repeated_track_is_copied_once(self, tmp_path):
        from src.library.playlist_export import copy_playlist_tracks

        (track,) = make_tracks(tmp_path / "src", "a.wav")
        out = tmp_path / "out"
        out.mkdir()
        copied, _ = copy_playlist_tracks([track, track, track], out)

        assert len(copied) == 3
        assert len({t.path for t in copied}) == 1
        assert list(out.iterdir()) == [out / "a.wav"]

    def test_same_name_from_different_folders_both_survive(self, tmp_path):
        from src.library.playlist_export import copy_playlist_tracks

        first = make_tracks(tmp_path / "one", "track.wav")
        second = make_tracks(tmp_path / "two", "track.wav")
        out = tmp_path / "out"
        out.mkdir()
        copied, _ = copy_playlist_tracks(first + second, out)

        assert [Path(t.path).name for t in copied] == ["track.wav", "track (2).wav"]

    def test_missing_sources_are_skipped_and_reported(self, tmp_path):
        from src.library.playlist_export import copy_playlist_tracks

        real = make_tracks(tmp_path / "src", "a.wav")
        ghost = ExportTrack(path=str(tmp_path / "src" / "gone.wav"), title="Gone")
        out = tmp_path / "out"
        out.mkdir()
        copied, missing = copy_playlist_tracks(real + [ghost], out)

        # Keeping the ghost would force the whole playlist absolute and cost
        # every other track its portability.
        assert [Path(t.path).name for t in copied] == ["a.wav"]
        assert missing == [ghost.path]

    def test_progress_reports_every_file_then_completion(self, tmp_path):
        from src.library.playlist_export import copy_playlist_tracks

        tracks = make_tracks(tmp_path / "src", "a.wav", "b.wav")
        out = tmp_path / "out"
        out.mkdir()
        seen = []
        copy_playlist_tracks(tracks, out, on_progress=lambda *a: seen.append(a))

        assert seen == [(0, 2, "a.wav"), (1, 2, "b.wav"), (2, 2, "")]

    def test_cancel_stops_between_files(self, tmp_path):
        from src.library.playlist_export import copy_playlist_tracks

        tracks = make_tracks(tmp_path / "src", "a.wav", "b.wav", "c.wav")
        out = tmp_path / "out"
        out.mkdir()
        calls = []
        copied, _ = copy_playlist_tracks(
            tracks, out, is_cancelled=lambda: bool(calls) or calls.append(1)
        )
        assert len(copied) == 1  # the first file went, then cancel took effect
