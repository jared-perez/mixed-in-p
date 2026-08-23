"""What the Metadata panel gives to the file, and what it stops giving to itself.

Three separable things. The cover column had been taking a quarter of the
panel for a cover that never rendered above 132px of it; the empty state kept
prompting for a drop over a file that was plainly loaded; and the cover sat a
whole tab bar above everything it belongs with.
"""

import numpy as np
import pytest

from src.gui.widgets.artwork_widget import _ART_MARGIN, ArtworkWidget
from src.gui.widgets.metadata_panel import _ART_COLUMN_WIDTH, MetadataPanel


@pytest.fixture
def panel(qtbot):
    p = MetadataPanel()
    qtbot.addWidget(p)
    p.resize(900, 600)
    p.show()
    qtbot.waitExposed(p)
    return p


@pytest.fixture
def audio_file(tmp_path):
    sf = pytest.importorskip("soundfile")
    path = tmp_path / "a track.wav"
    sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, subtype="PCM_16")
    return str(path)


def _cover_bytes() -> bytes:
    """A 600px square PNG, larger than any column it will be drawn into."""
    from PySide6.QtCore import QBuffer, QByteArray
    from PySide6.QtGui import QColor, QPixmap

    pix = QPixmap(600, 600)
    pix.fill(QColor(200, 60, 90))
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    pix.save(buf, "PNG")
    buf.close()
    return bytes(data.data())


class TestCoverColumn:
    def test_the_cover_fills_the_width_it_was_given(self, qtbot):
        """The bug: a QLabel reports its pixmap as its hint, and the pixmap was
        scaled from that same label — so it converged small and stayed there."""
        art = ArtworkWidget()
        qtbot.addWidget(art)
        art.set_column_width(_ART_COLUMN_WIDTH)
        art.set_artwork(_cover_bytes(), "image/png", emit=False)

        assert art.width() == _ART_COLUMN_WIDTH
        assert art._image_label.pixmap().width() == _ART_COLUMN_WIDTH - 2 * _ART_MARGIN

    def test_setting_the_width_twice_is_stable(self, qtbot):
        """Applied once, a feedback loop looks like a working layout. The
        playlist's artwork rows grew without bound for exactly this reason."""
        art = ArtworkWidget()
        qtbot.addWidget(art)
        art.set_column_width(_ART_COLUMN_WIDTH)
        art.set_artwork(_cover_bytes(), "image/png", emit=False)
        first = (art.size(), art._image_label.pixmap().size())

        art.set_column_width(_ART_COLUMN_WIDTH)
        assert (art.size(), art._image_label.pixmap().size()) == first

    def test_the_box_is_square_unless_the_hint_needs_more(self, qtbot):
        """Square for the cover; taller only if a translated hint wraps past it."""
        art = ArtworkWidget()
        qtbot.addWidget(art)
        art.set_column_width(_ART_COLUMN_WIDTH)
        assert art.height() >= art.width()

    def test_the_empty_state_hint_wraps_rather_than_clipping(self, qtbot):
        """fr wants 220px for its last line and ja 240, against ~142 available.
        A QLabel does not elide — unwrapped, the sentence is simply cut."""
        art = ArtworkWidget()
        qtbot.addWidget(art)
        assert art._image_label.wordWrap()


class TestCoverOffset:
    """The cover starts where the tabs' *contents* do, not where the tabs do.

    Level with the tab bar it began a row above every other thing in the
    panel, beside a word rather than beside the tags.
    """

    def test_the_column_is_offset_by_the_tab_bar(self, panel):
        # Asked of the tab bar, not written as a number: it is a font metric
        # wearing a widget, and a larger font or another style moves it.
        assert panel._art_column.contentsMargins().top() == (
            panel._tabs.tabBar().sizeHint().height()
        )

    def test_the_cover_clears_the_tab_bar(self, panel, audio_file):
        """The structural half, in a suite with no stylesheet: whatever the
        style makes the bar, the cover starts below it and not at the top."""
        panel._load_file(audio_file)
        panel.layout().activate()

        bar = panel._tabs.tabBar()
        bar_bottom = bar.mapTo(panel, bar.rect().bottomLeft()).y()
        cover_top = panel._artwork.mapTo(panel, panel._artwork.rect().topLeft()).y()
        assert cover_top >= bar_bottom

    def test_the_cover_sits_at_the_top_of_what_is_left(self, panel, audio_file):
        """The margin above is the alignment now, in place of AlignTop — so
        the slack has to go below the cover, not around it."""
        panel._load_file(audio_file)
        panel.layout().activate()

        column = panel._art_column.geometry()
        assert panel._artwork.y() == (
            column.y() + panel._art_column.contentsMargins().top()
        )


class TestEmptyState:
    def test_the_drop_prompt_and_watermark_go_when_a_file_arrives(
        self, panel, audio_file
    ):
        panel._load_file(audio_file)

        # isHidden, not isVisible: these assertions must be about the widget's
        # own state, which is what survives the panel not being the current page.
        assert panel._desc_label.isHidden()
        assert panel._bg_overlay.isHidden()

    def test_they_come_back_on_eject(self, panel, audio_file):
        panel._load_file(audio_file)
        panel._clear()

        assert not panel._desc_label.isHidden()
        assert not panel._bg_overlay.isHidden()
