"""Settings → Troubleshooting → Show Log File.

The installed build has no console, so the log is what a user sends with a
report; this button replaces "find this path by hand". What is worth testing
is that it aims at the isolated app data's log (never the developer's), and
that none of its three paths is a click that does nothing. The OS calls are
stubbed: a test must never open Finder or Explorer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.gui.app import log_file_path
from src.gui.widgets import settings_panel as panel_mod
from src.gui.widgets.settings_panel import SettingsPanel


@pytest.fixture
def calls(monkeypatch):
    """Record every way the button can answer, instead of performing it."""
    seen: dict[str, list] = {"reveal": [], "open": [], "box": []}

    def reveal(path):
        seen["reveal"].append(path)
        return Path(path).exists()

    monkeypatch.setattr(panel_mod, "reveal_in_file_manager", reveal)
    monkeypatch.setattr(panel_mod.QDesktopServices, "openUrl",
                        lambda url: seen["open"].append(url.toLocalFile()))
    monkeypatch.setattr(panel_mod.QMessageBox, "information",
                        lambda parent, title, text, *a, **k: seen["box"].append(text))
    return seen


@pytest.fixture
def panel(qtbot):
    widget = SettingsPanel()
    qtbot.addWidget(widget)
    return widget


def test_it_reveals_the_log_file(panel, calls):
    log = log_file_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("hello\n")

    panel._show_log_btn.click()

    assert calls["reveal"] == [str(log)]
    assert calls["open"] == [] and calls["box"] == []


def test_a_missing_file_opens_its_folder(panel, calls):
    log = log_file_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    assert not log.exists()

    panel._show_log_btn.click()

    assert calls["open"] == [str(log.parent)]
    assert calls["box"] == []


def test_no_log_folder_at_all_says_so(panel, calls):
    assert not log_file_path().parent.exists()

    panel._show_log_btn.click()

    assert calls["open"] == []
    assert calls["box"] == ["No log has been written yet."]
