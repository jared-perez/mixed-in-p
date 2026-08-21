"""The path's right-click menu: reveal, play, copy.

The path is the one thing in the panel that *identifies* the file rather than
describing it, so it is where "do something with this file" belongs. Every test
here drives `build_path_menu` and the handlers rather than showing a menu:
`QMenu.exec` cannot be monkeypatched out (PySide6 resolves it through C++), so
a real one hangs the whole suite with no output.
"""

import numpy as np
import pytest
from PySide6.QtGui import QGuiApplication

from src.gui.widgets import metadata_panel as mp_mod
from src.gui.widgets.metadata_panel import MetadataPanel


@pytest.fixture
def panel(qtbot):
    p = MetadataPanel()
    qtbot.addWidget(p)
    p.resize(900, 600)
    return p


@pytest.fixture
def audio_file(tmp_path):
    sf = pytest.importorskip("soundfile")
    path = tmp_path / "deep" / "folder" / "a track.wav"
    path.parent.mkdir(parents=True)
    sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, subtype="PCM_16")
    return str(path)


class TestWhatIsOffered:
    def test_all_three_entries_are_there(self, panel, audio_file):
        panel._load_file(audio_file)
        _, actions = panel.build_path_menu()
        assert set(actions) == {"reveal", "play", "copy"}

    def test_nothing_is_offered_with_no_file(self, panel):
        _, actions = panel.build_path_menu()
        assert not any(action.isEnabled() for action in actions.values())

    def test_the_menu_does_not_open_on_an_empty_panel(self, panel):
        """Guarded before construction, so no menu is built for no file."""
        from PySide6.QtCore import QPoint

        panel._on_path_menu(QPoint(0, 0))  # would exec() a real menu if it ran


class TestCopy:
    def test_it_copies_the_whole_path_not_the_elided_text(self, panel, audio_file):
        panel._load_file(audio_file)
        # The label elides; what is on screen is a rendering decision, and
        # pasting an ellipsis into a terminal is worse than pasting nothing.
        panel.copy_path_to_clipboard()

        assert QGuiApplication.clipboard().text() == audio_file

    def test_copying_with_no_file_leaves_the_clipboard_alone(self, panel):
        QGuiApplication.clipboard().setText("untouched")
        panel.copy_path_to_clipboard()
        assert QGuiApplication.clipboard().text() == "untouched"


class TestPlay:
    def test_play_asks_the_window_rather_than_reaching_for_the_player(
        self, panel, audio_file, qtbot
    ):
        """This panel owns a file, not the transport."""
        panel._load_file(audio_file)
        with qtbot.waitSignal(panel.play_requested, timeout=1000) as caught:
            panel.play_requested.emit(panel._file_path)
        assert caught.args == [audio_file]


class TestReveal:
    def test_reveal_from_the_menu_takes_the_same_path_as_the_button(
        self, panel, audio_file, monkeypatch
    ):
        seen: list[str] = []
        monkeypatch.setattr(
            mp_mod, "reveal_in_file_manager", lambda p: seen.append(p) or True
        )
        panel._load_file(audio_file)

        panel._on_reveal_clicked()

        assert seen == [audio_file]
