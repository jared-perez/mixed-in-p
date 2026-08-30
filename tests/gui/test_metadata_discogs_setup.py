"""The Metadata panel's Discogs Setup button, and where it lands.

An empty Metadata panel is a dead end: nothing to edit, and no sign that the
online lookup it offers has to be switched on in another panel entirely. The
button is the way out, so what is asserted here is that it stays put (it is a
header-row control that must not wander when the description beside it is
taken down) and that following it actually shows the Discogs settings rather
than merely the Settings page.
"""

import pytest

from src.gui.widgets.metadata_panel import MetadataPanel
from src.gui.widgets.settings_panel import SettingsPanel


@pytest.fixture
def panel(qtbot):
    p = MetadataPanel()
    qtbot.addWidget(p)
    p.resize(900, 600)
    p.show()
    qtbot.waitExposed(p)
    return p


def test_button_sits_at_the_right_of_the_header_row(panel, qtbot):
    btn = panel._discogs_setup_btn
    right = btn.mapTo(panel, btn.rect().topRight()).x()
    # Inside the panel, and hard against its right margin rather than trailing
    # the description. The margin is Theme.PADDING; allow a couple of pixels
    # of style slack on either side of it.
    from src.gui.styles.theme import Theme

    assert right <= panel.width()
    assert panel.width() - right <= Theme.PADDING + 2


def test_button_keeps_its_width_when_the_description_goes(panel, qtbot):
    """A loaded file hides the description; the button must not inherit its room.

    A QPushButton's default size policy lets it grow, so before it was pinned
    the button took the freed stretch and slid into the middle of the row at
    three times its own width.
    """
    btn = panel._discogs_setup_btn
    before_width = btn.width()
    before_right = btn.mapTo(panel, btn.rect().topRight()).x()

    panel._desc_label.setVisible(False)
    panel.layout().activate()

    assert btn.width() == before_width
    assert btn.mapTo(panel, btn.rect().topRight()).x() == before_right


def test_button_is_wide_enough_for_its_own_label(panel):
    """Sized from font metrics, because the label is translated.

    Not a pixel count: the suite runs without the app stylesheet, so the only
    honest assertion is that the minimum clears the text the button paints.
    """
    btn = panel._discogs_setup_btn
    assert btn.minimumWidth() >= btn.fontMetrics().horizontalAdvance(btn.text())


def test_button_emits_the_request(panel, qtbot):
    with qtbot.waitSignal(panel.discogs_setup_requested, timeout=1000):
        panel._discogs_setup_btn.click()


def test_settings_scrolls_to_the_discogs_section(qtbot):
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel.resize(700, 500)
    panel.show()
    qtbot.waitExposed(panel)
    qtbot.wait(10)

    bar = panel._scroll.verticalScrollBar()
    bar.setValue(0)
    panel.scroll_to_online_metadata()

    # The section heading is inside the viewport afterwards, and the controls
    # it names are with it — "the user sees the Discogs settings", which a bar
    # slammed to its maximum only happens to satisfy while nothing has been
    # added below the section.
    viewport = panel._scroll.viewport()
    for widget in (
        panel._online_section_label,
        panel._online_lookup_cb,
        panel._discogs_token_edit,
    ):
        top = widget.mapTo(viewport, widget.rect().topLeft()).y()
        assert 0 <= top < viewport.height()


def test_setup_button_reaches_the_discogs_settings(qtbot, tmp_path):
    """End to end through MainWindow: the page changes and the view scrolls.

    The scroll is the half that only works in the right order — a QScrollArea
    on a page that has never been current has no range to set a value within.
    """
    from src.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1100, 800)
    window.show()
    qtbot.waitExposed(window)

    window._metadata_panel._discogs_setup_btn.click()
    qtbot.wait(10)

    assert window._current_page == "settings"
    settings = window._settings_panel
    viewport = settings._scroll.viewport()
    label = settings._online_section_label
    top = label.mapTo(viewport, label.rect().topLeft()).y()
    assert 0 <= top < viewport.height()

    window.close()
