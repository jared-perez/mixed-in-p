"""The `rename` CLI subcommand's order of operations.

--replace edits the file's own name only. It used to run after
--add-prefix/--add-suffix and rewrite the text they had just added:
`--add-prefix "Artist " --replace Artist Band` gave `Band 01 - Band - …`.
Plain text ops never read the audio, so empty files stand in for tracks.
History lands in the suite's isolated app data (tests/conftest.py).
"""

from src import cli


def _track(tmp_path, name="01 - Artist - Deep Cut.wav"):
    path = tmp_path / name
    path.write_bytes(b"")
    return path


def test_replace_leaves_an_added_prefix_and_suffix_as_typed(tmp_path):
    _track(tmp_path)
    cli.main([
        "rename", str(tmp_path),
        "--add-prefix", "Artist ", "--add-suffix", " (Artist Edit)",
        "--replace", "Artist", "Band",
    ])
    assert [p.name for p in tmp_path.iterdir()] == [
        "Artist 01 - Band - Deep Cut (Artist Edit).wav"
    ]


def test_trim_counts_the_name_before_the_replace(tmp_path):
    """Trims come first, so their counts are of the name as the user sees it."""
    _track(tmp_path)
    cli.main(["rename", str(tmp_path), "--trim-start", "5",
              "--replace", "Artist", "The Artist"])
    assert [p.name for p in tmp_path.iterdir()] == ["The Artist - Deep Cut.wav"]


def test_the_preview_shows_the_same_order(tmp_path, capsys):
    track = _track(tmp_path)
    cli.main(["rename", str(tmp_path), "--add-prefix", "Artist ",
              "--replace", "Artist", "Band", "--preview"])
    assert "Artist 01 - Band - Deep Cut.wav" in capsys.readouterr().out
    assert track.exists()  # a preview renames nothing
