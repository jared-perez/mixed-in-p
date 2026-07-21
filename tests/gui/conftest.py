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
