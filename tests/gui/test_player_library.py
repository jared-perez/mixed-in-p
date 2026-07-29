"""Player <-> playlist library binding: Scratch persistence, load, save."""

import pytest
from PySide6.QtWidgets import QInputDialog

from src.gui.widgets.player_panel import PlayerPanel, _parse_bpm, _parse_duration
from src.library import SCRATCH_NODE_ID, Library


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "library.db")
    yield library
    library.close()


@pytest.fixture
def player(qtbot, lib):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    panel.set_library(lib)
    return panel


def make_files(tmp_path, *names):
    paths = []
    for name in names:
        f = tmp_path / name
        f.write_bytes(b"not-really-audio-" + name.encode())
        paths.append(str(f))
    return paths


def track_dicts(paths):
    from pathlib import Path

    return [{"file_path": p, "display_name": Path(p).name} for p in paths]


class TestParsers:
    def test_bpm(self):
        assert _parse_bpm("128") == 128.0
        assert _parse_bpm("128.5") == 128.5
        assert _parse_bpm("") is None
        assert _parse_bpm(None) is None

    def test_duration(self):
        assert _parse_duration("4:03") == 243
        assert _parse_duration("") is None
        assert _parse_duration(None) is None


class TestScratchPersistence:
    def test_adds_removes_and_clear_write_through(self, player, lib, tmp_path):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        player.add_tracks(track_dicts([a, b]))
        assert [t.path for t in lib.get_items(SCRATCH_NODE_ID)] == [a, b]

        player._table.selectRow(0)
        player._on_remove_selected()
        assert [t.path for t in lib.get_items(SCRATCH_NODE_ID)] == [b]

        player._on_clear_playlist()
        assert lib.get_items(SCRATCH_NODE_ID) == []

    def test_scratch_restores_on_load(self, qtbot, lib, tmp_path):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        first = PlayerPanel()
        qtbot.addWidget(first)
        first.set_library(lib)
        first.add_tracks(track_dicts([a, b]))

        # A fresh panel (fresh app session) restores the same list.
        second = PlayerPanel()
        qtbot.addWidget(second)
        second.set_library(lib)
        second.load_node(SCRATCH_NODE_ID)
        assert [e.file_path for e in second._playlist] == [a, b]


class TestLoadNode:
    def test_load_playlist_and_back_to_scratch(self, player, lib, tmp_path):
        a, b, c = make_files(tmp_path, "a.wav", "b.wav", "c.wav")
        player.add_tracks(track_dicts([a]))  # scratch content

        pl = lib.create_playlist("Set")
        ids = [lib.add_track(p) for p in (b, c)]
        lib.set_items(pl, ids)

        player.load_node(pl)
        assert [e.file_path for e in player._playlist] == [b, c]
        assert player.loaded_node_id == pl
        assert player._context_label.text() == "› Set"

        # Loading did NOT overwrite Scratch; going back restores it.
        player.load_node(SCRATCH_NODE_ID)
        assert [e.file_path for e in player._playlist] == [a]
        assert player._context_label.text() == "› Scratch"

    def test_loaded_playlist_edits_autosave_to_that_node(self, player, lib, tmp_path):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        pl = lib.create_playlist("Set")
        lib.set_items(pl, [lib.add_track(a)])

        player.load_node(pl)
        player.add_tracks(track_dicts([b]))
        assert [t.path for t in lib.get_items(pl)] == [a, b]
        assert lib.get_items(SCRATCH_NODE_ID) == []  # scratch untouched

    def test_duplicates_survive_load(self, player, lib, tmp_path):
        (a,) = make_files(tmp_path, "a.wav")
        pl = lib.create_playlist("Doubles")
        tid = lib.add_track(a)
        lib.set_items(pl, [tid, tid])
        player.load_node(pl)
        assert [e.file_path for e in player._playlist] == [a, a]

    def test_deleted_node_falls_back_to_scratch(self, player, lib, tmp_path):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        pl = lib.create_playlist("Doomed")
        lib.set_items(pl, [lib.add_track(a)])
        player.load_node(pl)

        lib.delete_node(pl)
        player.add_tracks(track_dicts([b]))  # triggers persist
        assert player.loaded_node_id == SCRATCH_NODE_ID
        assert [t.path for t in lib.get_items(SCRATCH_NODE_ID)] == [a, b]


class TestPlaybackDecoupledFromList:
    def test_switching_lists_keeps_playing_track(self, player, lib, tmp_path):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        player.add_tracks(track_dicts([a]))  # scratch: [a]
        pl = lib.create_playlist("Other")
        lib.set_items(pl, [lib.add_track(b)])

        player._play_track(0)  # start "playing" a from scratch
        assert player._playing_path == a
        assert player._now_playing_label.text().endswith("a.wav")

        player.load_node(pl)  # navigate to a list NOT containing a
        assert player._playing_path == a  # playback untouched
        assert not player._now_playing_label.isHidden()
        assert player._current_index == -1  # no row highlight in this list
        assert player._current_path() == a  # slicer/artwork still track a

        player.load_node(SCRATCH_NODE_ID)  # back to the list that has it
        assert player._current_index == 0  # row re-linked

    def test_clear_resets_now_playing(self, player, lib, tmp_path):
        (a,) = make_files(tmp_path, "a.wav")
        player.add_tracks(track_dicts([a]))
        player._play_track(0)
        player._on_clear_playlist()
        assert player._playing_path is None
        assert player._now_playing_label.isHidden()

    def test_removing_playing_row_unloads(self, player, lib, tmp_path):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        player.add_tracks(track_dicts([a, b]))
        player._play_track(0)
        player._table.selectRow(0)
        player._on_remove_selected()
        assert player._playing_path is None
        assert player._now_playing_label.isHidden()
        assert [e.file_path for e in player._playlist] == [b]


class TestSavePlaylist:
    def test_save_creates_named_playlist_at_top(self, player, lib, tmp_path, monkeypatch, qtbot):
        a, b = make_files(tmp_path, "a.wav", "b.wav")
        player.add_tracks(track_dicts([a, b]))
        lib.create_playlist("Older")  # should end up below the new one

        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *args, **kw: ("Peak Time", True))
        )
        with qtbot.waitSignal(player.playlist_saved, timeout=1000) as blocker:
            player._on_save_playlist()
        node_id = blocker.args[0]

        children = lib.get_children()
        assert [n.name for n in children] == ["Peak Time", "Older"]
        assert children[0].id == node_id
        assert [t.path for t in lib.get_items(node_id)] == [a, b]
        # Player still shows (and persists to) Scratch — saving is a copy.
        assert player.loaded_node_id == SCRATCH_NODE_ID
        assert [t.path for t in lib.get_items(SCRATCH_NODE_ID)] == [a, b]

    def test_cancel_and_blank_name_do_nothing(self, player, lib, tmp_path, monkeypatch):
        (a,) = make_files(tmp_path, "a.wav")
        player.add_tracks(track_dicts([a]))
        for response in (("Whatever", False), ("   ", True)):
            monkeypatch.setattr(
                QInputDialog, "getText", staticmethod(lambda *args, _r=response, **kw: _r)
            )
            player._on_save_playlist()
        assert lib.get_children() == []

    def test_save_button_hidden_without_library(self, qtbot):
        panel = PlayerPanel()
        qtbot.addWidget(panel)
        assert panel._save_btn.isHidden()


class TestTagPopulation:
    def test_add_tracks_falls_back_to_file_tags_for_bpm_and_key(
        self, player, lib, tmp_path, monkeypatch
    ):
        # Regression: the tag-read fallback filled artist/title/comment/year
        # but skipped bpm/key, leaving those two columns blank for file drops.
        from src.metadata.tags import TrackMetadata

        (a,) = make_files(tmp_path, "a.wav")
        monkeypatch.setattr(
            "src.metadata.tags.read_metadata",
            lambda _p: TrackMetadata(
                artist="Helene", title="Astral", bpm=180.0, key="6A", duration=410.0
            ),
        )
        player.add_tracks(track_dicts([a]))

        entry = player._playlist[0]
        assert (entry.bpm, entry.key) == ("180", "6A")
        # And the auto-save carried them into the library row.
        track = lib.get_track_by_path(a)
        assert (track.bpm, track.key) == (180.0, "6A")

    def test_load_node_uses_stored_tags_without_file_reads(
        self, player, lib, tmp_path
    ):
        # The DB row is the source: a load must show its tags even when the
        # file can't be read (here: fake bytes that mutagen rejects).
        (a,) = make_files(tmp_path, "a.wav")
        pl = lib.create_playlist("Set")
        tid = lib.add_track(
            a, artist="Helene", title="Astral", bpm=180.0, key="6A", duration=410.0
        )
        lib.set_items(pl, [tid])

        player.load_node(pl)
        entry = player._playlist[0]
        assert (entry.artist, entry.title) == ("Helene", "Astral")
        assert (entry.bpm, entry.key) == ("180", "6A")
        assert entry.duration == "6:50"
