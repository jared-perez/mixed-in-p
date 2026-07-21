"""Tests for the reveal-in-file-manager helper."""

import subprocess

import pytest

from src.utils import reveal
from src.utils.reveal import reveal_in_file_manager


@pytest.fixture
def captured(monkeypatch):
    """Capture subprocess.run calls instead of launching a file manager."""
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append((a, k)))
    return calls


class TestMissingFile:
    def test_returns_false_when_file_absent(self, tmp_path, captured):
        gone = tmp_path / "moved.aiff"
        assert reveal_in_file_manager(str(gone)) is False
        assert captured == []  # nothing launched

    def test_returns_false_for_empty_path(self, captured):
        assert reveal_in_file_manager("") is False
        assert captured == []


class TestExistingFile:
    def test_macos_uses_open_dash_r(self, tmp_path, captured, monkeypatch):
        monkeypatch.setattr(reveal.sys, "platform", "darwin")
        f = tmp_path / "track.aiff"
        f.write_bytes(b"x")
        assert reveal_in_file_manager(str(f)) is True
        (args, _), = captured
        assert args[0] == ["open", "-R", str(f)]

    def test_windows_uses_explorer_select(self, tmp_path, captured, monkeypatch):
        monkeypatch.setattr(reveal.sys, "platform", "win32")
        f = tmp_path / "track.aiff"
        f.write_bytes(b"x")
        assert reveal_in_file_manager(str(f)) is True
        (args, _), = captured
        assert args[0][0] == "explorer"
        assert args[0][1] == "/select,"

    def test_other_platform_opens_parent_folder(self, tmp_path, captured, monkeypatch):
        monkeypatch.setattr(reveal.sys, "platform", "linux")
        f = tmp_path / "track.aiff"
        f.write_bytes(b"x")
        assert reveal_in_file_manager(str(f)) is True
        (args, _), = captured
        assert args[0] == ["xdg-open", str(tmp_path)]


class TestLaunchFailure:
    def test_oserror_reported_as_false(self, tmp_path, monkeypatch):
        """A launch that raises is swallowed and reported, not crashed."""
        def boom(*a, **k):
            raise OSError("no file manager")

        monkeypatch.setattr(subprocess, "run", boom)
        f = tmp_path / "track.aiff"
        f.write_bytes(b"x")
        assert reveal_in_file_manager(str(f)) is False
