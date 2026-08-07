"""parse_audio_args: what a command line from the OS actually yields.

Plus ``shell_sorted``, which answers the other half of the same question —
the order to show them in, once they have all arrived.
"""

from __future__ import annotations

import os

import pytest

from src.utils.args import parse_audio_args, shell_sorted
from src.utils.paths import normalize_track_path


def make(tmp_path, name: str) -> str:
    p = tmp_path / name
    p.write_bytes(b"")
    return str(p)


def test_the_program_name_is_never_a_file(tmp_path):
    """argv[0] is the executable, and on a frozen build it is a real path."""
    exe = make(tmp_path, "MixedInP.mp3")  # worst case: it even looks playable
    assert parse_audio_args([exe]) == []


def test_a_plain_audio_file_comes_through_normalized(tmp_path):
    track = make(tmp_path, "track.mp3")
    assert parse_audio_args(["prog", track]) == [normalize_track_path(track)]


def test_spaces_survive(tmp_path):
    """Windows delivers 'with spaces.mp3' as one argument; keep it one file."""
    track = make(tmp_path, "with spaces.mp3")
    assert parse_audio_args(["prog", track]) == [normalize_track_path(track)]


def test_non_ascii_survives(tmp_path):
    """Verified on a frozen Windows build: no mojibake, so no workaround."""
    track = make(tmp_path, "café-日本.mp3")
    assert parse_audio_args(["prog", track]) == [normalize_track_path(track)]


def test_flags_are_not_files(tmp_path):
    """--cli must not be mistaken for a path, or CLI mode would open a window."""
    track = make(tmp_path, "track.mp3")
    assert parse_audio_args(["prog", "--cli", track, "-v"]) == [
        normalize_track_path(track)
    ]


def test_unsupported_extensions_are_dropped(tmp_path):
    """A mixed selection adds the audio and quietly ignores the rest."""
    track = make(tmp_path, "track.flac")
    make(tmp_path, "cover.jpg")
    make(tmp_path, "notes.txt")
    argv = ["prog", str(tmp_path / "cover.jpg"), track, str(tmp_path / "notes.txt")]
    assert parse_audio_args(argv) == [normalize_track_path(track)]


def test_extension_matching_ignores_case(tmp_path):
    """Windows hands back whatever case the file has; .MP3 is still an mp3."""
    track = make(tmp_path, "SHOUTY.MP3")
    assert parse_audio_args(["prog", track]) == [normalize_track_path(track)]


def test_a_missing_file_is_dropped(tmp_path):
    """It would otherwise become a dead library row only relocate can clear."""
    gone = str(tmp_path / "moved-since.mp3")
    assert parse_audio_args(["prog", gone]) == []


def test_a_directory_is_not_a_track(tmp_path):
    """Even one named like a file — the extension check alone would pass it."""
    d = tmp_path / "album.mp3"
    d.mkdir()
    assert parse_audio_args(["prog", str(d)]) == []


def test_order_is_preserved_and_not_sorted(tmp_path):
    """One invocation's argument order is the order given (verified on Windows).

    Deliberately NOT sorted here: a Windows multi-select arrives as one
    process *per file*, so there is no list at this level whose order could
    mean anything. Ordering is decided once, on the assembled batch, by
    ``shell_sorted``.
    """
    b = make(tmp_path, "b.mp3")
    a = make(tmp_path, "a.mp3")
    c = make(tmp_path, "c.mp3")
    assert parse_audio_args(["prog", b, a, c]) == [
        normalize_track_path(p) for p in (b, a, c)
    ]


def test_one_file_named_twice_lands_once(tmp_path):
    """Not the duplicate-policy question — just that one argv means one add."""
    track = make(tmp_path, "track.mp3")
    assert parse_audio_args(["prog", track, track]) == [normalize_track_path(track)]


@pytest.mark.skipif(os.name != "nt", reason="Windows-only path spelling")
def test_a_windows_backslash_path_normalizes_like_a_qt_one(tmp_path):
    """argv gives backslashes, Qt gives forward slashes — one file, one row.

    This is the exact trap that produced two library rows for one file the
    first time playlists ran on Windows; Open With would reintroduce it
    through the front door without the normalize step.
    """
    track = make(tmp_path, "track.mp3")
    from_argv = parse_audio_args(["prog", track.replace("/", "\\")])
    from_qt = parse_audio_args(["prog", track.replace("\\", "/")])
    assert from_argv == from_qt != []


def test_an_empty_command_line_is_not_an_error():
    """The ordinary launch: no files, no complaints."""
    assert parse_audio_args(["prog"]) == []
    assert parse_audio_args([]) == []


# ── shell_sorted ────────────────────────────────────────────────


class TestShellSorted:
    """The order a file manager would have shown them in."""

    def test_it_sorts_by_name(self):
        assert shell_sorted(["/m/c.mp3", "/m/a.mp3", "/m/b.mp3"]) == [
            "/m/a.mp3",
            "/m/b.mp3",
            "/m/c.mp3",
        ]

    def test_digits_compare_as_numbers(self):
        """``Track 10`` after ``Track 2``, as both Explorer and Finder show it.

        Plain string order puts 10 first, which for a DJ opening a numbered
        set is visibly wrong in the only case where the numbering matters.
        """
        got = shell_sorted(["/m/Track 10.mp3", "/m/Track 2.mp3", "/m/Track 1.mp3"])
        assert got == ["/m/Track 1.mp3", "/m/Track 2.mp3", "/m/Track 10.mp3"]

    def test_case_does_not_split_the_list(self):
        """Both shells are case-insensitive; sorting by codepoint would put
        every capital ahead of every lowercase."""
        assert shell_sorted(["/m/beta.mp3", "/m/Alpha.mp3", "/m/Gamma.mp3"]) == [
            "/m/Alpha.mp3",
            "/m/beta.mp3",
            "/m/Gamma.mp3",
        ]

    def test_the_folder_is_not_part_of_the_comparison(self):
        """The user was reading filenames, not paths."""
        assert shell_sorted(["/zzz/a.mp3", "/aaa/b.mp3"]) == ["/zzz/a.mp3", "/aaa/b.mp3"]

    def test_the_same_name_twice_falls_back_to_the_path(self):
        """Otherwise a tie leaves the result depending on arrival order, which
        is the exact nondeterminism this function exists to remove."""
        first = shell_sorted(["/b/x.mp3", "/a/x.mp3"])
        second = shell_sorted(["/a/x.mp3", "/b/x.mp3"])
        assert first == second == ["/a/x.mp3", "/b/x.mp3"]

    def test_non_ascii_names_sort_without_blowing_up(self):
        """`explorer five café.wav` is a real fixture on the Windows machine."""
        assert shell_sorted(["/m/café.wav", "/m/apple.wav"]) == [
            "/m/apple.wav",
            "/m/café.wav",
        ]

    def test_a_name_that_is_all_digits_is_fine(self):
        assert shell_sorted(["/m/10.mp3", "/m/9.mp3"]) == ["/m/9.mp3", "/m/10.mp3"]

    def test_empty_in_empty_out(self):
        assert shell_sorted([]) == []
