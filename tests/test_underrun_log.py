"""UnderrunLog: audio-thread counting, GUI-thread throttled reporting.

The counter is what makes an underrun visible at all — the streams' callbacks
used to ignore ``status`` entirely, so a glitch left no trace anywhere.
"""

import logging

import pytest

from src.gui.widgets import loop_player
from src.gui.widgets.loop_player import UnderrunLog


class _Clock:
    """A monotonic clock the test can advance by hand."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(loop_player.time, "monotonic", c)
    return c


def test_count_tallies_only_flagged_blocks():
    log = UnderrunLog("Test stream")
    # A clean block reports a falsy status (sounddevice's CallbackFlags is
    # falsy with no flags set); only flagged blocks may count.
    log.count(0)
    log.count(None)
    assert log.total == 0
    log.count(4)  # any truthy flags object
    log.count(True)
    assert log.total == 2


def test_report_logs_growth_with_name_and_total(clock, caplog):
    log = UnderrunLog("Test stream")
    log.count(True)
    with caplog.at_level(logging.WARNING):
        log.report()
    assert len(caplog.records) == 1
    assert "Test stream" in caplog.text
    assert "1 audio underruns" in caplog.text


def test_report_is_silent_when_nothing_new(clock, caplog):
    log = UnderrunLog("Test stream")
    with caplog.at_level(logging.WARNING):
        log.report()  # never counted anything
        log.count(True)
        clock.now += UnderrunLog.LOG_EVERY_S + 1
        log.report()  # logs the growth
        clock.now += UnderrunLog.LOG_EVERY_S + 1
        log.report()  # total unchanged since — must stay quiet
    assert len(caplog.records) == 1


def test_report_throttles_then_catches_up(clock, caplog):
    log = UnderrunLog("Test stream")
    with caplog.at_level(logging.WARNING):
        log.count(True)
        log.report()  # first line
        log.count(True)
        log.report()  # inside the throttle window — suppressed
        assert len(caplog.records) == 1
        clock.now += UnderrunLog.LOG_EVERY_S + 0.1
        log.report()  # window elapsed — reports the missed growth
    assert len(caplog.records) == 2
    assert "2 audio underruns" in caplog.records[-1].getMessage()
