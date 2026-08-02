"""Scratch is emptied at startup unless the user opts to keep it.

Scratch is the disposable working list the Player opens on. The clear runs
through the library API before the undo stack exists, so these tests exercise
``apply_scratch_policy`` directly rather than booting a MainWindow — which
would open the developer's real library.db.
"""

import pytest

from src.gui.main_window import apply_scratch_policy
from src.library import SCRATCH_NODE_ID, Library


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "library.db")
    yield library
    library.close()


def fill_scratch(library, *paths):
    ids = [library.add_track(p) for p in paths]
    library.set_items(SCRATCH_NODE_ID, ids)
    return ids


class TestClearing:
    def test_scratch_is_emptied_when_not_persisting(self, lib):
        fill_scratch(lib, "/music/a.wav", "/music/b.wav")
        apply_scratch_policy(lib, persist=False)
        assert lib.get_item_track_ids(SCRATCH_NODE_ID) == []

    def test_scratch_survives_when_persisting(self, lib):
        ids = fill_scratch(lib, "/music/a.wav", "/music/b.wav")
        apply_scratch_policy(lib, persist=True)
        assert lib.get_item_track_ids(SCRATCH_NODE_ID) == ids

    def test_an_already_empty_scratch_is_fine(self, lib):
        apply_scratch_policy(lib, persist=False)
        assert lib.get_item_track_ids(SCRATCH_NODE_ID) == []

    def test_the_node_itself_is_never_deleted(self, lib):
        """Scratch is reserved: clearing empties it, it does not remove it."""
        fill_scratch(lib, "/music/a.wav")
        apply_scratch_policy(lib, persist=False)
        assert lib.get_node(SCRATCH_NODE_ID) is not None


class TestSavedPlaylistsAreUntouched:
    def test_a_saved_playlist_keeps_its_tracks(self, lib):
        pl = lib.create_playlist("Set")
        kept = [lib.add_track(p) for p in ("/music/x.wav", "/music/y.wav")]
        lib.set_items(pl, kept)
        fill_scratch(lib, "/music/a.wav")

        apply_scratch_policy(lib, persist=False)

        assert lib.get_item_track_ids(pl) == kept

    def test_a_track_in_both_survives_the_gc(self, lib):
        """The clear garbage-collects orphans only.

        A track sitting in Scratch *and* in a saved playlist must not be
        collected out from under the saved playlist when Scratch drops it.
        """
        shared = lib.add_track("/music/shared.wav")
        pl = lib.create_playlist("Set")
        lib.set_items(pl, [shared])
        lib.set_items(SCRATCH_NODE_ID, [shared])

        apply_scratch_policy(lib, persist=False)

        assert lib.get_item_track_ids(pl) == [shared]
        assert lib.get_track(shared) is not None
