"""One spelling per file — see src/utils/paths.py.

The library keys tracks on the literal path string, so the value of this
helper is that every add route hands it the same file and gets back the same
string. These tests state that as a property rather than as a table of
expected strings, because the canonical form is platform-specific.

**Known coverage gap: symlink collapsing is unverified on Windows.**
``test_a_symlinked_directory_collapses`` skips there, because ``symlink_to``
needs Developer Mode or an elevated shell. That matters more than it looks:
resolving symlinks is *why* ``normalize_track_path`` calls ``resolve()``
rather than just rebuilding through ``Path``, so on Windows the reason for
the design choice is the one property not being checked. The separator and
dot-segment properties are covered on both platforms. Running the suite from
an elevated Windows shell would close the gap.
"""

import sys
from pathlib import Path

import pytest

from src.utils.paths import normalize_track_path


class TestNormalizeTrackPath:
    def test_a_relative_path_becomes_absolute(self, tmp_path, monkeypatch):
        (tmp_path / "a.wav").write_bytes(b"audio")
        monkeypatch.chdir(tmp_path)

        assert Path(normalize_track_path("a.wav")).is_absolute()

    def test_dot_segments_collapse(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "a.wav").write_bytes(b"audio")
        detour = tmp_path / "sub" / ".." / "a.wav"

        assert normalize_track_path(detour) == str(tmp_path / "a.wav")

    def test_it_is_idempotent(self, tmp_path):
        (tmp_path / "a.wav").write_bytes(b"audio")
        once = normalize_track_path(tmp_path / "a.wav")

        assert normalize_track_path(once) == once

    def test_a_missing_file_still_normalizes(self, tmp_path):
        """A track can go missing between being added and being dragged."""
        (tmp_path / "sub").mkdir()
        gone = tmp_path / "sub" / ".." / "gone.wav"

        assert normalize_track_path(gone) == str(tmp_path / "gone.wav")

    def test_a_symlinked_directory_collapses(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        (real / "a.wav").write_bytes(b"audio")
        link = tmp_path / "link"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            # Windows needs Developer Mode or an elevated shell for this.
            pytest.skip("symlinks not available on this machine")

        assert normalize_track_path(link / "a.wav") == str(real / "a.wav")

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows separators")
    def test_forward_slashes_become_native(self):
        """The actual Windows bug: Qt hands back "C:/music/a.mp3"."""
        assert normalize_track_path("C:/music/a.mp3").endswith(r"music\a.mp3")

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows separators")
    def test_both_qt_and_native_spellings_agree(self):
        assert normalize_track_path("C:/music/a.mp3") == normalize_track_path(
            r"C:\music\a.mp3"
        )
