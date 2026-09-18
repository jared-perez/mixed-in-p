"""A drop on a sidebar button files the files without leaving the page.

Rename, Convert, Analyze and the Player just take the files on, so switching
to them pulled the user out of whatever they were doing. Metadata and Spectrum
work on the dropped file itself, so a drop there still opens the page.
"""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from src.gui.main_window import MainWindow
from src.gui.models import TrackState
from src.utils.config import AppConfig, save_config


@pytest.fixture
def window(qtbot):
    # Auto-analyze off: a drop on Analyze queues the file rather than starting
    # a real analysis thread, which is all this needs to see.
    save_config(AppConfig(auto_analyze=False))
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    yield win
    win._player_panel.shutdown_workers()


@pytest.fixture
def wav(tmp_path) -> str:
    path = tmp_path / "drop.wav"
    sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100)
    return str(path)


def _stay_on_keyboard(win) -> None:
    win._show_page("keyboard")
    assert win._current_page == "keyboard"


def test_a_drop_on_rename_queues_without_switching(window, wav):
    _stay_on_keyboard(window)
    window._on_sidebar_drop("rename", [wav])
    assert window._current_page == "keyboard"
    track = window._store.get_by_path(wav)
    assert track is not None and track.state == TrackState.QUEUED


def test_a_drop_on_analyze_queues_without_switching(window, wav):
    _stay_on_keyboard(window)
    window._on_sidebar_drop("analysis", [wav])
    assert window._current_page == "keyboard"
    track = window._store.get_by_path(wav)
    assert track is not None and track.state == TrackState.PENDING


def test_a_drop_on_convert_adds_without_switching(window, wav, monkeypatch):
    added = []
    monkeypatch.setattr(window._conversion_panel, "add_files", added.append)
    _stay_on_keyboard(window)
    window._on_sidebar_drop("convert", [wav])
    assert window._current_page == "keyboard"
    assert added == [[wav]]


def test_the_page_can_still_be_changed_after_a_drop(window, wav):
    _stay_on_keyboard(window)
    window._on_sidebar_drop("rename", [wav])
    window._show_page("rename")
    assert window._current_page == "rename"


@pytest.mark.parametrize("page, loader", [
    ("metadata", ("_metadata_panel", "_load_file")),
    ("spectrum", ("_spectrum_panel", "load_files")),
])
def test_a_drop_on_metadata_or_spectrum_opens_the_page(window, wav, monkeypatch, page, loader):
    loaded = []
    panel, method = loader
    monkeypatch.setattr(getattr(window, panel), method, loaded.append)
    _stay_on_keyboard(window)
    window._on_sidebar_drop(page, [wav])
    assert window._current_page == page
    assert loaded
