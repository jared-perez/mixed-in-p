"""The Settings control that offers to make Mixed in P the default player.

The OS call itself is covered (as far as it safely can be) in
``tests/test_default_app.py``. What matters here is everything around it: that
the button exists where there is a route and not where there isn't, that it
calls the module rather than reimplementing it, and — the part with real
consequences — that the *silent* case is the one where the user can already
see what happened.
"""

from __future__ import annotations

import pytest

from src.gui.widgets import settings_panel as panel_mod
from src.gui.widgets.settings_panel import SettingsPanel
from src.utils import default_app
from src.utils.default_app import Outcome, Result


@pytest.fixture
def boxes(monkeypatch):
    """Record message boxes instead of showing them.

    An unclicked modal hangs the whole suite, and this handler opens one on
    three of its four paths.
    """
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        panel_mod.QMessageBox,
        "information",
        lambda parent, title, text, *a, **k: shown.append(("info", text)),
    )
    monkeypatch.setattr(
        panel_mod.QMessageBox,
        "warning",
        lambda parent, title, text, *a, **k: shown.append(("warning", text)),
    )
    return shown


@pytest.fixture
def panel(qtbot):
    widget = SettingsPanel()
    qtbot.addWidget(widget)
    return widget


def answer(monkeypatch, result: Result) -> list[int]:
    """Make the OS call return *result* without touching the OS."""
    calls: list[int] = []

    def fake():
        calls.append(1)
        return result

    monkeypatch.setattr(default_app, "make_default", fake)
    return calls


class TestTheControl:
    def test_it_is_there_on_a_platform_with_a_route(self, panel):
        assert default_app.available()
        assert panel._default_app_btn is not None

    def test_it_is_absent_where_there_is_no_route(self, qtbot, monkeypatch):
        """A Linux build shows nothing rather than a button that can only
        apologise."""
        monkeypatch.setattr(default_app, "available", lambda: False)
        widget = SettingsPanel()
        qtbot.addWidget(widget)
        assert not hasattr(widget, "_default_app_btn")

    def test_the_button_asks_the_module(self, panel, monkeypatch, boxes):
        calls = answer(monkeypatch, Result(Outcome.HANDED_OFF, "ms-settings:…"))
        panel._default_app_btn.click()
        assert calls == [1]


class TestWhatTheUserIsTold:
    def test_handing_off_to_the_os_says_nothing(self, panel, monkeypatch, boxes):
        """Windows Settings is now in front of them on our entry. A box on top
        of it would narrate what they are looking at."""
        answer(monkeypatch, Result(Outcome.HANDED_OFF, "ms-settings:…"))
        panel._default_app_btn.click()
        assert boxes == []

    def test_a_completed_change_is_confirmed(self, panel, monkeypatch, boxes):
        """The macOS case: nothing visible happened, so say so."""
        answer(monkeypatch, Result(Outcome.DONE))
        panel._default_app_btn.click()
        assert [kind for kind, _ in boxes] == ["info"]

    def test_no_route_is_explained_not_reported_as_an_error(
        self, panel, monkeypatch, boxes
    ):
        """Running from a source checkout is the ordinary state of a dev
        machine, not a fault — and the message has to be the manual route,
        because that one always works."""
        answer(monkeypatch, Result(Outcome.UNSUPPORTED, "not a bundle"))
        panel._default_app_btn.click()
        (kind, text), = boxes
        assert kind == "info"
        assert "Change All" in text or "Reinstalling" in text

    def test_a_failure_warns(self, panel, monkeypatch, boxes):
        answer(monkeypatch, Result(Outcome.FAILED, "boom"))
        panel._default_app_btn.click()
        assert [kind for kind, _ in boxes] == ["warning"]

    def test_every_answer_leaves_a_log_line(self, panel, monkeypatch, boxes, caplog):
        """The detail is English and never shown; the log is the only place it
        goes, and it is what a support question gets answered from."""
        answer(monkeypatch, Result(Outcome.FAILED, "OSStatus -10814"))
        with caplog.at_level("INFO", logger=panel_mod.__name__):
            panel._default_app_btn.click()
        assert "OSStatus -10814" in caplog.text
