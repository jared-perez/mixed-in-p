"""setup_logging writes a file the installed build can hand back.

The exe has no console, so until the file existed a declined rename or an
exception swallowed by a Qt slot left no trace on a user's machine.
"""

from __future__ import annotations

import logging
import sys

import pytest

from src.gui import app
from src.utils import app_dirs


@pytest.fixture
def clean_logging():
    yield
    app.teardown_logging()


def test_the_log_lands_under_the_app_data_dir(clean_logging):
    path = app.setup_logging()

    # Through the module, never a bound name: the suite patches it there.
    assert path == app_dirs.get_app_data_dir() / "logs" / "mixedinp.log"
    for handler in logging.getLogger().handlers:
        handler.flush()
    text = path.read_text(encoding="utf-8")
    assert "Mixed in P" in text and "starting" in text


def test_a_second_setup_replaces_rather_than_stacks(clean_logging):
    app.setup_logging()
    before = len(logging.getLogger().handlers)
    app.setup_logging()
    assert len(logging.getLogger().handlers) == before


def test_an_escaped_exception_reaches_the_file(clean_logging, monkeypatch):
    # Chain over a benign hook (restored after): pytest-qt's own capture would
    # otherwise count the chained call as an exception in the event loop.
    chained = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: chained.append(a[0]))
    path = app.setup_logging()
    try:
        raise ValueError("boom in a slot")
    except ValueError as exc:
        sys.excepthook(type(exc), exc, exc.__traceback__)
    for handler in logging.getLogger().handlers:
        handler.flush()
    text = path.read_text(encoding="utf-8")
    assert "Unhandled exception" in text and "boom in a slot" in text
    assert chained == [ValueError]  # the previous hook still ran


def test_teardown_is_idempotent(clean_logging):
    app.setup_logging()
    app.teardown_logging()
    app.teardown_logging()
    assert app._file_handler is None
