"""Energy from analysis to the file's own field, and back into the library.

Writing the field is only half of it: the point of a field that reads back
exactly is that the energy ends up somewhere queryable. So this covers the
whole path — analysis writes it, an add reads it, the library row holds it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QObject

from src.analysis.result import AnalysisResult
from src.gui.convert_pipeline import ConvertPipeline
from src.gui.main_window import MainWindow
from src.gui.models.track_model import TrackStore
from src.gui.widgets.player_panel import PlayerPanel
from src.library import Library
from src.metadata.tags import read_energy, read_metadata, write_energy
from src.utils.config import AppConfig


@pytest.fixture
def flac(tmp_path):
    sf = pytest.importorskip("soundfile")
    path = tmp_path / "track.flac"
    sf.write(str(path), np.zeros(44100, dtype=np.float32), 44100, format="FLAC")
    return str(path)


# ── The analysis write ──────────────────────────────────────────


class PanelStub(QObject):
    def __init__(self):
        super().__init__()
        self.auto_write_bpm = False
        self.auto_write_key = False


class WindowStub(QObject):
    _update_track_from_result = MainWindow._update_track_from_result
    _apply_analysis_result = MainWindow._apply_analysis_result

    def __init__(self, store, config):
        super().__init__()
        self._store = store
        self._config = config
        self._analysis_panel = PanelStub()
        self._analysis_writes_frozen = False
        # The write path now ends by offering the result to the convert
        # pipeline; an unarmed one is inert.
        self._pipeline = ConvertPipeline()


def analyse(flac, **config_overrides):
    """Run the real write path over one result and return the window stub."""
    config = AppConfig()
    config.energy_tag_enabled = False  # isolate the field from the comment
    config.key_in_comment_enabled = False
    for key, value in config_overrides.items():
        setattr(config, key, value)
    store = TrackStore()
    store.add_from_path(flac)
    window = WindowStub(store, config)
    window._update_track_from_result(
        AnalysisResult(
            file_path=flac, bpm=128.0, bpm_confidence=0.9, key="Am",
            key_confidence=0.8, keycode="8A", energy=7,
        )
    )
    return window


class TestAnalysisWritesIt:
    def test_the_energy_lands_in_its_own_field(self, flac):
        analyse(flac)

        assert read_energy(flac) == 7

    def test_the_setting_turns_it_off(self, flac):
        analyse(flac, energy_field_enabled=False)

        assert read_energy(flac) is None

    def test_the_comment_setting_does_not_govern_it(self, flac):
        """The two are independent: someone who doesn't want their comments
        touched still gets a readable energy."""
        analyse(flac, energy_tag_enabled=False, energy_field_enabled=True)

        assert read_energy(flac) == 7
        assert not (read_metadata(flac).comment or "")

    def test_the_write_freeze_holds_it_too(self, flac):
        """It is a write to the user's file, so it sits below the freeze gate
        with every other one."""
        config = AppConfig()
        config.energy_tag_enabled = False
        store = TrackStore()
        store.add_from_path(flac)
        window = WindowStub(store, config)
        window._analysis_writes_frozen = True

        window._update_track_from_result(
            AnalysisResult(
                file_path=flac, bpm=128.0, bpm_confidence=0.9, key="Am",
                key_confidence=0.8, keycode="8A", energy=7,
            )
        )

        assert read_energy(flac) is None


# ── And back into the library ───────────────────────────────────


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


class TestItReachesTheLibrary:
    def test_adding_a_tagged_file_fills_the_energy_column(
        self, player, lib, flac, qtbot
    ):
        """The column existed and was always NULL — nothing wrote it but a
        snapshot restore. This is what closes that."""
        write_energy(flac, 8)

        player.add_tracks(
            [{"file_path": flac, "display_name": Path(flac).name}],
            allow_duplicates=True,
        )
        qtbot.wait(10)

        assert lib.get_track_by_path(flac).energy == 8

    def test_the_playlist_tree_import_reads_it_too(self, lib, flac):
        """The other add site — a file dropped straight onto a playlist.

        Driven as an unbound method against a stub, the trick the drag tests
        use: what is under test is the tags it forwards, not a tree.
        """
        from src.gui.widgets.playlist_tree import PlaylistTree

        write_energy(flac, 4)

        class TreeStub:
            _library = lib
            _track_id_for = PlaylistTree._track_id_for

        track_id = TreeStub()._track_id_for(flac)

        assert lib.get_track(track_id).energy == 4

    def test_a_file_with_no_energy_leaves_the_column_alone(
        self, player, lib, flac, qtbot
    ):
        player.add_tracks(
            [{"file_path": flac, "display_name": Path(flac).name}],
            allow_duplicates=True,
        )
        qtbot.wait(10)

        assert lib.get_track_by_path(flac).energy is None
