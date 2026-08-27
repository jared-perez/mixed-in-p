"""Shared setup for headless GUI tests.

Forces Qt's offscreen platform plugin before pytest-qt creates the
QApplication, so these tests never open a real window (and so they behave the
same on a dev Mac and on a headless machine).

READ tests/gui/README.md before adding tests here — the offscreen platform
does NOT reproduce macOS's QMacStyle, so this suite cannot validate rendering.
"""

import os

# Must be set before any QApplication is constructed; pytest-qt builds one
# lazily on first qtbot use, and conftest import happens well before that.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="session", autouse=True)
def warm_lazy_audio_imports():
    """Pull librosa's lazy import in on the main thread, once, before any test.

    ``waveform_worker._read_audio`` imports librosa on first decode, and it
    runs on the Player's background decode threads. Two of those entering the
    import lock together — or one of them against a main-thread import — aborts
    the interpreter outright (``Fatal Python error: Aborted``, every thread
    parked in ``<frozen importlib._bootstrap>``).

    Any test that pumps the event loop while a Player fixture is alive can
    trigger it, because pumping is what lets a queued prefetch actually start
    decoding; the duplicate-prompt tests do exactly that. Importing here means
    the lock is uncontended by the time any thread wants it.

    NB: this is the §21 race, not the separate teardown segfault — that one
    happens after every test has already passed.
    """
    try:
        import librosa  # noqa: F401 — imported for the side effect

        librosa.load  # noqa: B018 — materialises the lazy_loader proxy
    except ImportError:  # pragma: no cover — librosa is a hard dependency
        pass


@pytest.fixture(autouse=True)
def lookup_review_guard(monkeypatch):
    """Make a stray online-lookup review dialog fail rather than hang.

    Same hazard as the duplicate prompt below: ``exec()`` on a modal blocks
    forever in a headless run, and the failure lands on whichever test was
    unlucky. Replaced with a recorder that answers Cancel and then fails the
    test by name.

    A test that *means* to open it patches ``exec`` itself — that overrides
    this stub, so the guard stays quiet.
    """
    from src.gui.widgets.dialogs.lookup_review import LookupReviewDialog

    seen = []

    def trap(self):
        seen.append(self._file_path)
        return 0  # QDialog.Rejected — apply nothing

    monkeypatch.setattr(LookupReviewDialog, "exec", trap)
    yield
    assert not seen, (
        "The lookup review dialog opened unexpectedly for: "
        + "; ".join(seen)
        + ". Patch LookupReviewDialog.exec in a test that means to reach it."
    )


@pytest.fixture(autouse=True)
def duplicate_prompt_guard(monkeypatch):
    """Pin the duplicate policy, and make a stray prompt fail rather than hang.

    Two hazards, both worth closing off for every GUI test:

    * The policy is a **user setting**, so without pinning it the suite would
      pass or fail depending on what the developer happens to have chosen in
      Settings. It is pinned to the shipped default ("ask").
    * "ask" opens a modal. Nothing clicks it in a headless run, so
      ``QMessageBox.exec()`` blocks forever — and because the prompt is fired
      from a zero-delay timer, it goes off during pytest-qt's teardown event
      processing, hanging a test that had already passed. Instead of a hang,
      the box is replaced by a recorder that abandons the add and fails the
      test afterwards, naming the collision it was asked about.

    A test that *wants* the prompt patches ``_prompt`` itself; that overrides
    this stub, so the guard stays quiet.
    """
    from src.gui.widgets.dialogs import duplicate_policy

    seen = []

    def trap(parent, collisions, total, playlist_name):
        seen.append((collisions, total, playlist_name))
        return None  # Cancel — add nothing, so the test can still finish

    monkeypatch.setattr(duplicate_policy, "_prompt", trap)
    monkeypatch.setattr(duplicate_policy, "current_policy", lambda: "ask")
    yield
    assert not seen, (
        "The duplicate prompt opened unexpectedly: "
        + "; ".join(f"{c} of {t} already in {name!r}" for c, t, name in seen)
        + ". Patch duplicate_policy._prompt (or pin current_policy) in a test "
        "that means to reach it."
    )


@pytest.fixture(autouse=True)
def no_latched_modifiers():
    """Fail the test that leaves a keyboard modifier held down.

    ``QTest.keyClick(w, key, SomeModifier)`` presses the modifier and never
    releases it, and ``QGuiApplication.keyboardModifiers()`` is *application*
    state — it outlives the widget, the test and every fixture, for the whole
    session.

    The damage lands somewhere else entirely, which is what makes it worth a
    guard rather than a convention. ``QAbstractItemView.selectRow`` does not
    simply select: it asks ``selectionCommand()``, which reads those
    modifiers. So a latched Control turns a *programmatic* ``selectRow(1)`` in
    some later, unrelated test into a Ctrl-click that adds row 1 to the
    selection instead of replacing it — and that test then asserts against the
    union of two rows, with nothing in its own code to explain why. Measured:
    the Cmd/Ctrl+L tests silently broke a search-highlight test three files
    away, and only ever when the two ran in that order.

    Release the modifier in the helper that pressed it (see ``press_hotkey``
    in test_playing_playlist_hotkey.py). This only says so out loud.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest

    yield
    stuck = QGuiApplication.keyboardModifiers()
    if stuck != Qt.KeyboardModifier.NoModifier:
        # Don't leave it latched for the rest of the session as well. The
        # release needs somewhere to go: QTest.keyRelease(None, ...) takes a
        # null QWidget* and crashes the interpreter, so give it a scratch
        # widget rather than the test's own, which teardown has already closed.
        from PySide6.QtWidgets import QWidget

        sink = QWidget()
        for modifier, key in (
            (Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Control),
            (Qt.KeyboardModifier.ShiftModifier, Qt.Key.Key_Shift),
            (Qt.KeyboardModifier.AltModifier, Qt.Key.Key_Alt),
            (Qt.KeyboardModifier.MetaModifier, Qt.Key.Key_Meta),
        ):
            if stuck & modifier:
                QTest.keyRelease(sink, key)
        sink.deleteLater()
        pytest.fail(
            f"This test left {stuck!r} held down. QTest.keyClick presses a "
            "modifier without releasing it, and keyboardModifiers() is "
            "application-global — a later test's selectRow() reads it and "
            "silently extends its selection. Follow the keyClick with "
            "QTest.keyRelease(widget, Qt.Key.Key_Control) (or the matching "
            "key)."
        )
