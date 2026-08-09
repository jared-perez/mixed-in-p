"""The Cancel button in the Analyze/Convert progress panel.

Two complaints, both about a control that lies. It stayed on screen after the
run ended, where clicking it does nothing at all — there is no longer a thread
to cancel — and it was a solid red block, which reads as an error state rather
than an available action next to a live progress readout.

What matters is that it is present exactly while a run is cancellable, and that
it is wide enough for its own translated label: a QPushButton centres rather
than elides, so a label wider than the button is cut at *both* ends, and the
stylesheet padding these are sized against is invisible to Qt's native size
hint.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QTranslator

from src.gui.widgets.progress_bar import ProgressPanel


@pytest.fixture
def panel(qtbot):
    widget = ProgressPanel(show_activity=True)
    qtbot.addWidget(widget)
    return widget


def test_hidden_before_anything_runs(panel):
    assert not panel._cancel_btn.isVisible()


def test_visible_while_running(panel, qtbot):
    panel.start(3)
    assert panel._cancel_btn.isVisible()
    assert panel._cancel_btn.isEnabled()


def test_hidden_once_complete(panel):
    """The reported bug: it lingered after the run, doing nothing when clicked."""
    panel.start(3)
    panel.complete("Complete: 3 files analyzed")
    assert not panel._cancel_btn.isVisible()


def test_hidden_once_cancelled(panel):
    panel.start(3)
    panel.cancelled()
    assert not panel._cancel_btn.isVisible()


def test_hidden_on_error(panel):
    panel.start(3)
    panel.set_error("Could not read file")
    assert not panel._cancel_btn.isVisible()


def test_returns_for_a_second_run(panel):
    """A panel reused for the next batch must offer Cancel again."""
    panel.start(2)
    panel.complete()
    panel.start(2)
    assert panel._cancel_btn.isVisible()


def test_cancel_emits_once_clicked(panel, qtbot):
    panel.start(1)
    with qtbot.waitSignal(panel.cancel_clicked, timeout=1000):
        panel._cancel_btn.click()


def test_cancelled_is_not_styled_as_an_error(panel):
    """Cancelling is a neutral outcome the user asked for, not a failure.

    It previously reused set_error, painting "Cancelled" in error red.
    """
    panel.start(2)
    panel.cancelled()
    assert "Cancelled" in panel._status_label.text()
    from src.gui.styles.theme import Theme
    assert Theme.ERROR.lower() not in panel._status_label.styleSheet().lower()


@pytest.mark.parametrize("code", ["de", "nl", "ja", "ru", "es"])
def test_button_fits_its_translated_label(qtbot, code):
    """German "Abbrechen" needs 99px; the old fixed 80px minimum clipped it."""
    translator = QTranslator()
    if not translator.load(f"mixedinp_{code}", "src/gui/translations"):
        pytest.skip(f"no compiled translation for {code}")

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    app.installTranslator(translator)
    try:
        widget = ProgressPanel(show_activity=True)
        qtbot.addWidget(widget)
        widget.start(1)
        button = widget._cancel_btn
        # 28px is the stylesheet's horizontal padding (14px each side).
        needed = button.fontMetrics().horizontalAdvance(button.text()) + 28
        available = max(button.minimumWidth(), button.sizeHint().width())
        assert available >= needed, (
            f"{code}: {button.text()!r} needs {needed}px, button offers {available}px"
        )
    finally:
        app.removeTranslator(translator)
