"""Looking at the cover, and the menu that replaced the Remove button.

The lightbox is a child of the *window*, not of the cover — which is what makes
"click anywhere to close" a true statement rather than a description of a 150px
target. These tests are mostly about that parentage and about the one rule the
scaling follows.
"""

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QVBoxLayout, QWidget

from src.gui.widgets.artwork_lightbox import _MIN_ENLARGED, ArtworkLightbox
from src.gui.widgets.artwork_widget import ArtworkWidget
from src.gui.widgets.metadata_panel import _ART_COLUMN_WIDTH, MetadataPanel


def _cover(side: int = 600) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray

    pix = QPixmap(side, side)
    pix.fill(QColor(200, 60, 90))
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    pix.save(buf, "PNG")
    buf.close()
    return bytes(data.data())


@pytest.fixture
def hosted(qtbot):
    """A cover inside a window, because the lightbox parents to the window."""
    window = QWidget()
    window.resize(900, 700)
    layout = QVBoxLayout(window)
    art = ArtworkWidget()
    art.set_column_width(_ART_COLUMN_WIDTH)
    layout.addWidget(art)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window, art


class TestOpening:
    def test_it_covers_the_window_not_the_cover(self, hosted):
        window, art = hosted
        art.set_artwork(_cover(), "image/png", emit=False)

        box = art.open_lightbox()

        assert box is not None
        assert box.parentWidget() is window
        assert box.size() == window.size()

    def test_an_empty_cover_opens_nothing(self, hosted):
        _, art = hosted
        assert art.open_lightbox() is None

    def test_a_click_anywhere_closes_it(self, qtbot, hosted):
        window, art = hosted
        art.set_artwork(_cover(), "image/png", emit=False)
        box = art.open_lightbox()

        qtbot.mouseClick(box, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))

        qtbot.waitUntil(lambda: box.isHidden(), timeout=2000)

    def test_escape_closes_it(self, qtbot, hosted):
        _, art = hosted
        art.set_artwork(_cover(), "image/png", emit=False)
        box = art.open_lightbox()

        qtbot.keyClick(box, Qt.Key.Key_Escape)

        qtbot.waitUntil(lambda: box.isHidden(), timeout=2000)

    def test_it_follows_the_window_being_resized(self, qtbot, hosted):
        """Not following leaves a scrim over part of a window, which reads as
        a paint bug; closing on resize loses the picture for a window nudge."""
        window, art = hosted
        art.set_artwork(_cover(), "image/png", emit=False)
        box = art.open_lightbox()

        window.resize(700, 500)
        qtbot.waitUntil(lambda: box.size() == window.size(), timeout=2000)


class TestScaling:
    def test_a_large_cover_is_fitted_to_the_window(self, qtbot):
        host = QWidget()
        host.resize(800, 800)
        qtbot.addWidget(host)
        host.show()
        qtbot.waitExposed(host)
        source = QPixmap(2000, 2000)
        source.fill(QColor(10, 10, 10))

        box = ArtworkLightbox(source, host)
        box.show_over_parent()

        assert box._scaled.width() <= host.width()
        assert box._scaled.width() > host.width() // 2

    def test_a_tiny_cover_is_not_blown_up_without_limit(self, qtbot):
        """Upscaling invents pixels. Allowed only far enough that an enlarged
        postage stamp is worth having opened at all."""
        host = QWidget()
        host.resize(1400, 1400)
        qtbot.addWidget(host)
        host.show()
        qtbot.waitExposed(host)
        source = QPixmap(80, 80)
        source.fill(QColor(10, 10, 10))

        box = ArtworkLightbox(source, host)
        box.show_over_parent()

        assert box._scaled.width() == _MIN_ENLARGED


class TestCoverMenu:
    def test_remove_is_offered_only_when_there_is_a_cover(self, qtbot):
        art = ArtworkWidget()
        qtbot.addWidget(art)

        _, empty = art.build_context_menu()
        assert not empty["remove"].isEnabled()

        art.set_artwork(_cover(), "image/png", emit=False)
        _, filled = art.build_context_menu()
        assert filled["remove"].isEnabled()

    def test_the_panel_no_longer_carries_a_remove_button(self, qtbot):
        """It moved to the cover's menu; nothing should be left behind."""
        panel = MetadataPanel()
        qtbot.addWidget(panel)
        assert not hasattr(panel, "_remove_artwork_btn")

    def test_removing_from_the_menu_writes_the_file(self, qtbot, tmp_path):
        sf = pytest.importorskip("soundfile")
        from src.metadata.tags import TrackMetadata, read_metadata, write_metadata

        path = tmp_path / "t.flac"
        sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
        write_metadata(
            str(path),
            TrackMetadata(artwork=_cover(120), artwork_mime="image/png"),
            fields=["artwork"],
        )
        panel = MetadataPanel()
        qtbot.addWidget(panel)
        panel._load_file(str(path))
        assert read_metadata(str(path)).artwork is not None

        # What the menu's action does, without showing a menu: QMenu.exec
        # cannot be patched out, and a real one hangs the suite silently.
        panel._artwork.clear_artwork(emit=True)

        assert read_metadata(str(path)).artwork is None


def test_two_clicks_do_not_stack_two_lightboxes(qtbot, hosted):
    _, art = hosted
    art.set_artwork(_cover(), "image/png", emit=False)

    first = art.open_lightbox()
    second = art.open_lightbox()

    assert second is first


def test_closing_lets_it_be_opened_again(qtbot, hosted):
    """The guard must be cleared by the box's own death, or one look at a
    cover is all you ever get."""
    _, art = hosted
    art.set_artwork(_cover(), "image/png", emit=False)

    first = art.open_lightbox()
    first.close()
    qtbot.waitUntil(lambda: art._lightbox is None, timeout=2000)

    assert art.open_lightbox() is not None
