"""The Metadata panel shows which file it is editing, and can reveal it.

The filename alone doesn't identify a track — a DJ library is full of second
copies — and this panel writes to disk, so "which one am I about to change?"
has to be answerable without leaving the panel.
"""

import numpy as np
import pytest

from src.gui.widgets import metadata_panel as mp_mod
from src.gui.widgets.elided_label import ElidedLabel
from src.gui.widgets.metadata_panel import MetadataPanel


@pytest.fixture
def panel(qtbot):
    p = MetadataPanel()
    qtbot.addWidget(p)
    p.resize(900, 600)
    # Shown, so the visibility assertions below are about the header's own
    # state rather than about a widget that was never on screen at all.
    p.show()
    qtbot.waitExposed(p)
    return p


@pytest.fixture
def audio_file(tmp_path):
    """A real (if brief) WAV, so read_metadata succeeds and a form is built."""
    sf = pytest.importorskip("soundfile")
    path = tmp_path / "deep" / "nested" / "folder" / "a track.wav"
    path.parent.mkdir(parents=True)
    sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, subtype="PCM_16")
    return str(path)


class TestPathDisplay:
    def test_the_full_path_is_shown_and_elides(self, panel, audio_file):
        panel._load_file(audio_file)

        assert panel._path_label.text() == audio_file
        # A path's length is not ours to control, and a plain QLabel would
        # draw past its own edge rather than eliding.
        assert isinstance(panel._path_label, ElidedLabel)

    def test_the_tooltip_carries_the_path_immediately(
        self, panel, audio_file, tmp_path
    ):
        """Not left to the label's resize handling — a load with no resize
        would otherwise keep the previous file's tooltip."""
        panel._load_file(audio_file)

        assert panel._path_label.toolTip() == audio_file

    def test_the_filename_elides(self, panel, audio_file):
        """The filename is the side of the header row that gives way — the
        props beside it keep their natural width — so it is the side that
        needs an ellipsis to admit it. A plain QLabel would draw past its own
        edge and cut a glyph in half."""
        panel._load_file(audio_file)

        assert isinstance(panel._file_label, ElidedLabel)
        assert panel._file_label.text() == "a track.wav"

    def test_a_name_too_long_for_the_row_is_recoverable_without_a_resize(
        self, panel, qtbot, tmp_path
    ):
        """The label maintains its own tooltip in resizeEvent only, and a
        longer name at an unchanged width starts overflowing with no resize to
        follow — so _load_file sets it too."""
        sf = pytest.importorskip("soundfile")
        panel.resize(500, 600)
        # A second file with the *same* audio properties, so the props label
        # beside it is unchanged and the filename's share of the row is too:
        # nothing resizes, and only the explicit set reaches the tooltip.
        short = tmp_path / "a.wav"
        name = "Some Artist - A Very Long Track Title (Extended Club Mix).wav"
        long = tmp_path / name
        for path in (short, long):
            sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100,
                     subtype="PCM_16")
        panel._load_file(str(short))
        qtbot.wait(10)

        panel._load_file(str(long))

        assert panel._file_label.toolTip() == name

    def test_the_path_is_not_an_editable_tag_field(self, panel, audio_file):
        """In the header, not the form: _do_save writes every _field_edits
        entry back to the file as a tag."""
        panel._load_file(audio_file)

        assert "path" not in panel._field_edits
        assert audio_file not in [e.text() for e in panel._field_edits.values()]

    def test_clearing_empties_the_path(self, panel, audio_file):
        panel._load_file(audio_file)
        assert panel._file_header_widget.isVisible()

        panel._clear()

        assert panel._path_label.text() == ""
        assert panel._path_label.toolTip() == ""
        assert panel._file_label.text() == ""
        assert panel._file_label.toolTip() == ""
        assert not panel._file_header_widget.isVisible()


class TestReveal:
    def test_it_reveals_the_loaded_file(self, panel, audio_file, monkeypatch):
        revealed = []
        monkeypatch.setattr(
            mp_mod, "reveal_in_file_manager", lambda p: revealed.append(p) or True
        )
        panel._load_file(audio_file)

        panel._reveal_btn.click()

        # The file itself, not its folder: selecting it is the whole point.
        assert revealed == [audio_file]

    def test_a_file_that_moved_is_explained_not_ignored(
        self, panel, audio_file, monkeypatch
    ):
        shown = []
        monkeypatch.setattr(mp_mod, "reveal_in_file_manager", lambda p: False)
        monkeypatch.setattr(
            mp_mod.QMessageBox,
            "information",
            staticmethod(lambda *a: shown.append(a[2])),
        )
        panel._load_file(audio_file)

        panel._reveal_btn.click()

        assert len(shown) == 1

    def test_it_does_nothing_with_no_file_loaded(self, panel, monkeypatch):
        calls = []
        monkeypatch.setattr(
            mp_mod, "reveal_in_file_manager", lambda p: calls.append(p) or True
        )

        panel._on_reveal_clicked()

        assert calls == []
