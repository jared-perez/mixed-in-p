"""The one-time import of rename history from the app's old ``~/.musickey``.

The interesting case is not the import itself — it is what happens on the
*second* call, and on every call after a user deletes something.

``Path.home()`` is redirected per test rather than trusted: the real one holds
the developer's own ``~/.musickey`` if they have ever run an old build, which
would make these pass or fail depending on whose machine they ran on. That is
the same trap ``isolated_app_data`` exists to close for the app data dir.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.renamer.history import (
    _MIGRATED_MARKER,
    RenameSession,
    delete_session,
    get_history_dir,
    list_sessions,
)


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """A throwaway ``~`` so the real one cannot decide the outcome."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return home


def old_session(home: Path, session_id: str = "abc123") -> Path:
    """A session file sitting in the pre-rename ``~/.musickey`` location."""
    old_dir = home / ".musickey" / "history"
    old_dir.mkdir(parents=True, exist_ok=True)
    session = RenameSession(
        session_id=session_id, records=[], timestamp="2026-01-01T00:00:00"
    )
    f = old_dir / f"session_{session_id}.json"
    f.write_text(json.dumps(session.to_dict()))
    return f


class TestTheImport:
    def test_an_old_session_is_brought_over(self, fake_home):
        old_session(fake_home)

        history_dir = get_history_dir()

        assert (history_dir / "session_abc123.json").exists()

    def test_a_deleted_session_stays_deleted(self, fake_home):
        """The bug this file exists for.

        The import used to re-run on every call and decide what to copy with
        ``if not dest.exists()`` — which after the first run means "the user
        deleted it", not "it has not been imported yet". Every history
        operation goes through ``get_history_dir``, so Delete in the History
        panel unlinked the file and the panel's own refresh copied it straight
        back, inside the same click.
        """
        old_session(fake_home)
        get_history_dir()  # first call: imports it

        assert delete_session("abc123") is True

        # The refresh the panel does immediately afterwards. This is the call
        # that used to undo the delete.
        assert list_sessions() == []
        assert not (get_history_dir() / "session_abc123.json").exists()

    def test_the_marker_is_written_even_with_nothing_to_import(self, fake_home):
        """The ordinary case — a fresh install has no ~/.musickey at all — so
        the check settles to one exists() rather than a glob per operation."""
        assert not (fake_home / ".musickey").exists()

        history_dir = get_history_dir()

        assert (history_dir / _MIGRATED_MARKER).exists()

    def test_a_later_old_file_is_not_picked_up(self, fake_home):
        """Once done, it is done. A file appearing in the old directory
        afterwards is not a migration, and re-importing it would resurrect
        whatever the user had already cleared."""
        get_history_dir()
        old_session(fake_home, "late")

        assert list_sessions() == []

    def test_the_marker_is_not_mistaken_for_a_session(self, fake_home):
        """It lives in the same directory the panel lists."""
        old_session(fake_home)

        sessions = list_sessions()

        assert [s.session_id for s in sessions] == ["abc123"]

    def test_the_import_is_a_copy_so_an_older_build_keeps_its_history(
        self, fake_home
    ):
        source = old_session(fake_home)

        get_history_dir()

        assert source.exists()
