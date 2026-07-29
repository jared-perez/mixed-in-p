"""Export from the tree: dialogs, the copy-tracks worker, and Settings.

The file formats themselves are covered by tests/test_playlist_export.py.
What's under test here is the wiring: what the menu offers, what happens
when a dialog is cancelled, and that a failed or cancelled copy never leaves
a half-built folder behind.
"""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from src.gui.widgets.playlist_tree import PlaylistTreePanel, _with_playlist_suffix
from src.gui.widgets.settings_panel import SettingsPanel
from src.library import SCRATCH_NODE_ID, Library
from src.utils.config import AppConfig


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "library.db")
    yield library
    library.close()


@pytest.fixture
def tree(qtbot, lib):
    panel = PlaylistTreePanel()
    qtbot.addWidget(panel)
    panel.set_library(lib)
    panel.ensure_loaded()
    return panel.tree


@pytest.fixture
def audio(tmp_path):
    directory = tmp_path / "audio"
    directory.mkdir()
    paths = []
    for name in ("a.wav", "b.wav"):
        f = directory / name
        f.write_bytes(b"audio-" + name.encode())
        paths.append(str(f))
    return paths


def silence_dialogs(monkeypatch):
    """Swallow the result boxes so tests don't block, capturing their text.

    Covers both shapes in use: the static helpers, and the constructed
    QMessageBox the success path builds so it can carry informative text.
    """
    seen = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: seen.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: seen.append(a[2]))

    def fake_exec(box):
        seen.append("\n\n".join(t for t in (box.text(), box.informativeText()) if t))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    return seen


def read(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


class TestSuffixHandling:
    """Non-native dialogs don't append the filter's extension; we must."""

    def test_typed_extension_is_respected(self):
        assert _with_playlist_suffix("/x/Set.m3u", "Playlist (*.m3u8)") == "/x/Set.m3u"
        assert _with_playlist_suffix("/x/Set.TXT", "Playlist (*.m3u8)") == "/x/Set.TXT"

    def test_missing_extension_comes_from_the_chosen_filter(self):
        assert _with_playlist_suffix("/x/Set", "Tracklist (*.txt)") == "/x/Set.txt"
        assert _with_playlist_suffix("/x/Set", "Playlist (*.m3u)") == "/x/Set.m3u"

    def test_unrecognised_filter_falls_back_to_m3u8(self):
        assert _with_playlist_suffix("/x/Set", "") == "/x/Set.m3u8"

    def test_a_dotted_playlist_name_still_gets_a_suffix(self):
        # "Live @ 3.0" has a suffix of ".0" — not a format, so append.
        assert _with_playlist_suffix("/x/Live @ 3.0", "Playlist (*.m3u8)") == (
            "/x/Live @ 3.0.m3u8"
        )


class TestExportPlaylist:
    def test_writes_the_chosen_file(self, tree, lib, audio, tmp_path, monkeypatch):
        pl = lib.create_playlist("Peak Time")
        lib.set_items(pl, [lib.add_track(p, artist="DJ", title=Path(p).stem) for p in audio])
        tree.refresh()

        out = tmp_path / "Peak Time.m3u8"
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), "Playlist (*.m3u8)")
        )
        seen = silence_dialogs(monkeypatch)

        tree._export_playlist(pl)
        assert out.exists()
        assert read(out).startswith("#EXTM3U\r\n#EXTINF:-1,DJ - a\r\n")
        assert "Exported 2 tracks" in seen[0]

    def test_the_import_hint_appears_for_m3u_but_not_txt(
        self, tree, lib, audio, tmp_path, monkeypatch
    ):
        # §6: Rekordbox's import menu is buried, so the export tells you.
        pl = lib.create_playlist("Set")
        lib.set_items(pl, [lib.add_track(audio[0])])
        tree.refresh()
        seen = silence_dialogs(monkeypatch)

        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *a, **k: (str(tmp_path / "s.m3u8"), "Playlist (*.m3u8)"),
        )
        tree._export_playlist(pl)
        assert "Rekordbox" in seen[-1]

        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            lambda *a, **k: (str(tmp_path / "s.txt"), "Tracklist (*.txt)"),
        )
        tree._export_playlist(pl)
        assert "Rekordbox" not in seen[-1]

    def test_each_import_route_gets_its_own_line(self, tree):
        # As one sentence the three routes wrapped into each other in the
        # dialog and read as a single run-on instruction.
        lines = tree._import_hint().splitlines()
        assert len(lines) == 3
        assert [line.split(" — ")[0] for line in lines] == [
            "Serato",
            "Rekordbox",
            "Traktor",
        ]
        assert all(len(line) < 50 for line in lines)  # short enough not to wrap

    def test_cancelling_the_dialog_writes_nothing(self, tree, lib, audio, tmp_path, monkeypatch):
        pl = lib.create_playlist("Set")
        lib.set_items(pl, [lib.add_track(audio[0])])
        tree.refresh()
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
        silence_dialogs(monkeypatch)

        tree._export_playlist(pl)
        assert list(tmp_path.glob("*.m3u8")) == []

    def test_an_empty_playlist_says_so_instead_of_writing(self, tree, lib, monkeypatch):
        pl = lib.create_playlist("Empty")
        tree.refresh()
        seen = silence_dialogs(monkeypatch)
        called = []
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", lambda *a, **k: called.append(1) or ("", "")
        )

        tree._export_playlist(pl)
        assert not called  # never even asks where to put it
        assert "empty" in seen[0]

    def test_scratch_exports_like_any_playlist(self, tree, lib, audio, tmp_path, monkeypatch):
        lib.set_items(SCRATCH_NODE_ID, [lib.add_track(audio[0])])
        out = tmp_path / "Scratch.m3u8"
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), "Playlist (*.m3u8)")
        )
        silence_dialogs(monkeypatch)

        tree._export_playlist(SCRATCH_NODE_ID)
        assert out.exists()

    def test_the_settings_override_forces_full_paths(
        self, tree, lib, audio, tmp_path, monkeypatch
    ):
        pl = lib.create_playlist("Set")
        lib.set_items(pl, [lib.add_track(audio[0])])
        tree.refresh()
        # Export next to the audio, where the rule would choose relative.
        out = Path(audio[0]).parent / "Set.m3u8"
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), "Playlist (*.m3u8)")
        )
        silence_dialogs(monkeypatch)
        monkeypatch.setattr(
            "src.gui.widgets.playlist_tree.load_config",
            lambda: AppConfig(export_absolute_paths=True),
        )

        tree._export_playlist(pl)
        assert str(Path(audio[0]).resolve()) in read(out)


class TestExportFolder:
    def test_mirrors_the_subtree_into_a_folder_of_its_own(
        self, tree, lib, audio, tmp_path, monkeypatch
    ):
        crates = lib.create_folder("Crates")
        inner = lib.create_folder("2026", crates)
        lib.set_items(lib.create_playlist("Peak", inner), [lib.add_track(audio[0])])
        lib.set_items(lib.create_playlist("Warm", crates), [lib.add_track(audio[1])])
        tree.refresh()

        dest = tmp_path / "dest"
        dest.mkdir()
        monkeypatch.setattr(
            QFileDialog, "getExistingDirectory", lambda *a, **k: str(dest)
        )
        seen = silence_dialogs(monkeypatch)

        tree._export_folder(crates)
        assert (dest / "Crates" / "Warm.m3u8").exists()
        assert (dest / "Crates" / "2026" / "Peak.m3u8").exists()
        assert "Exported 2 playlists" in seen[0]

    def test_cancelling_creates_nothing(self, tree, lib, tmp_path, monkeypatch):
        crates = lib.create_folder("Crates")
        tree.refresh()
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: "")
        silence_dialogs(monkeypatch)

        tree._export_folder(crates)
        assert list(tmp_path.glob("Crates*")) == []


class TestCopyTracksFlow:
    def _run(self, tree, qtbot, node_id, dest, monkeypatch):
        monkeypatch.setattr(
            QFileDialog, "getExistingDirectory", lambda *a, **k: str(dest)
        )
        tree._export_with_tracks(node_id)
        # Wait for the result to be *handled*, not merely for the thread to
        # stop: the completion signal is queued onto this thread, and
        # _copy_thread is cleared by the handler that runs after it lands.
        qtbot.waitUntil(lambda: tree._copy_thread is None, timeout=5000)

    def test_produces_a_portable_folder(
        self, tree, lib, audio, tmp_path, qtbot, monkeypatch
    ):
        pl = lib.create_playlist("Summer Set")
        lib.set_items(pl, [lib.add_track(p) for p in audio])
        tree.refresh()
        dest = tmp_path / "dest"
        dest.mkdir()
        seen = silence_dialogs(monkeypatch)

        self._run(tree, qtbot, pl, dest, monkeypatch)

        folder = dest / "Summer Set"
        assert (folder / "a.wav").exists()
        assert (folder / "b.wav").exists()
        playlist = folder / "Summer Set.m3u8"
        assert playlist.exists()
        body = read(playlist)
        assert "\r\na.wav\r\n" in body  # relative: works on another machine
        assert str(tmp_path) not in body
        assert "Exported 2 tracks" in seen[0]

    def test_missing_tracks_are_reported_not_copied(
        self, tree, lib, audio, tmp_path, qtbot, monkeypatch
    ):
        pl = lib.create_playlist("Set")
        gone = tmp_path / "audio" / "gone.wav"
        gone.write_bytes(b"x")
        ids = [lib.add_track(audio[0]), lib.add_track(str(gone))]
        lib.set_items(pl, ids)
        gone.unlink()  # the drive went away between adding and exporting
        tree.refresh()
        dest = tmp_path / "dest"
        dest.mkdir()
        seen = silence_dialogs(monkeypatch)

        self._run(tree, qtbot, pl, dest, monkeypatch)

        assert not (dest / "Set" / "gone.wav").exists()
        assert "could not be found" in seen[0]
        # The rest stayed portable rather than being dragged to full paths.
        assert "\r\na.wav\r\n" in read(dest / "Set" / "Set.m3u8")

    def test_an_empty_playlist_never_creates_a_folder(
        self, tree, lib, tmp_path, monkeypatch
    ):
        pl = lib.create_playlist("Empty")
        tree.refresh()
        dest = tmp_path / "dest"
        dest.mkdir()
        seen = silence_dialogs(monkeypatch)
        monkeypatch.setattr(
            QFileDialog, "getExistingDirectory", lambda *a, **k: str(dest)
        )

        tree._export_with_tracks(pl)
        assert list(dest.iterdir()) == []
        assert "empty" in seen[0]

    def test_a_failed_copy_leaves_no_half_built_folder(
        self, tree, lib, audio, tmp_path, qtbot, monkeypatch
    ):
        pl = lib.create_playlist("Set")
        lib.set_items(pl, [lib.add_track(audio[0])])
        tree.refresh()
        dest = tmp_path / "dest"
        dest.mkdir()
        silence_dialogs(monkeypatch)
        monkeypatch.setattr(
            "src.gui.workers.playlist_copy_worker.write_playlist",
            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
        )

        self._run(tree, qtbot, pl, dest, monkeypatch)
        assert list(dest.iterdir()) == []

    def test_the_folder_name_is_disambiguated(
        self, tree, lib, audio, tmp_path, qtbot, monkeypatch
    ):
        pl = lib.create_playlist("Set")
        lib.set_items(pl, [lib.add_track(audio[0])])
        tree.refresh()
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "Set").mkdir()  # something is already called that
        silence_dialogs(monkeypatch)

        self._run(tree, qtbot, pl, dest, monkeypatch)
        assert (dest / "Set (2)" / "a.wav").exists()


class TestSettingsControls:
    def test_the_absolute_paths_toggle_round_trips(self, qtbot):
        panel = SettingsPanel()
        qtbot.addWidget(panel)

        assert panel.get_config().export_absolute_paths is False
        panel.load_config(AppConfig(export_absolute_paths=True))
        assert panel._export_absolute_cb.isChecked()
        assert panel.get_config().export_absolute_paths is True

    def test_export_all_only_asks_the_window(self, qtbot):
        # The panel has no library and must never touch playlist data.
        panel = SettingsPanel()
        qtbot.addWidget(panel)
        with qtbot.waitSignal(panel.export_all_playlists):
            panel._export_all_btn.click()
