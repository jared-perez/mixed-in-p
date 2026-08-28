"""The History footer row decides the window minimum, rather than a constant.

`window_sizer._PANEL_MIN_WIDTH["history"]` was 600 — an English width. Every
button in the footer is translated and two of them also carry a runtime count,
so German and Russian overran it and the row was *squeezed* instead of the
window grown: `0 Umbenennungssitzunge` lost its final letter and
`Auswahl widerrufen` was cut at both ends, while Russian's
`Тональности треков` overlapped `Показать`. Found by `scripts/visual_pass.py`
and confirmed by rendering the pages and looking at them.

No pixel counts here. The suite runs with no application stylesheet, so its
widths are Fusion's and not the app's — what must hold is the *relationship*:
the window minimum is at least what the row needs, whatever that turns out to
be on the platform running the test.
"""

import pytest
from PySide6.QtCore import QSize

from src.gui.widgets.history_panel import HistoryPanel
from src.gui.window_sizer import WindowSizer


@pytest.fixture
def panel(qtbot):
    p = HistoryPanel()
    qtbot.addWidget(p)
    return p


def _sizer_for(panel, sidebar_width=220):
    """The wiring, without standing up a whole MainWindow."""
    from types import SimpleNamespace

    window = SimpleNamespace(
        _sidebar=SimpleNamespace(width=lambda: sidebar_width),
        _history_panel=panel,
        _header=SimpleNamespace(minimumSizeHint=lambda: QSize(0, 0)),
        _current_page="history",
    )
    return WindowSizer(window)


def test_the_window_minimum_is_measured_from_the_footer_row(panel):
    sizer = _sizer_for(panel)
    assert sizer._min_width_for("history") >= 220 + panel.footer_row_min_width()


def test_a_wider_button_raises_the_window_minimum(panel):
    """The regression proper: a longer label must move the window, not clip."""
    sizer = _sizer_for(panel)
    before = sizer._min_width_for("history")

    # Stand in for a translation: German's 'Auswahl widerrufen' and Russian's
    # 'Отменить выбранное' are both wider than 'Undo Selected'.
    panel._undo_btn.setText("Auswahl widerrufen und noch etwas mehr Text")
    panel._undo_btn.setMinimumWidth(panel._undo_btn.sizeHint().width() + 44)

    assert sizer._min_width_for("history") > before


def test_the_row_min_grows_with_a_longer_label(panel):
    before = panel.footer_row_min_width()
    panel._export_btn.setText("Een veel langer label voor deze knop")
    panel._export_btn.setMinimumWidth(panel._export_btn.sizeHint().width())
    assert panel.footer_row_min_width() > before


def test_the_row_spacing_is_set_so_the_sum_does_not_subtract(panel):
    """`QLayout.spacing()` reads back -1 when it was never set.

    The row is measured, and a width summed with a -1 gap subtracts where it
    means to add — so the spacing has to be explicit. Asserting it is >= 0 is
    the honest form: the *value* is Theme.SPACING, but what breaks the
    measurement is the sentinel.
    """
    assert panel._footer_row.spacing() >= 0


def test_a_count_change_announces_that_the_row_may_have_grown(panel, qtbot):
    """_fit widens the toggles at runtime, so a once-measured minimum goes stale.

    Asserted on the signal rather than on a width: the signal is the contract
    with the sizer, and it is what a future refactor would drop.
    """
    with qtbot.waitSignal(panel.footer_row_resized, timeout=1000):
        panel._refresh_sessions()


def test_the_footer_row_is_never_partly_hidden(panel):
    """Why footer_row_min_width may ask the layout instead of summing widgets.

    A hidden widget contributes nothing to a layout's own hint — the trap that
    makes ConversionPanel.format_row_min_width enumerate its widgets by hand.
    Asking the layout is only safe here because nothing in this row is ever
    hidden; if that stops being true, this test fails and the method has to
    change with it.
    """
    for widget in (
        panel._sessions_btn,
        panel._keys_btn,
        panel._show_label,
        panel._limit_btn,
        panel._export_btn,
        panel._delete_btn,
        panel._undo_btn,
    ):
        assert not widget.isHidden()
