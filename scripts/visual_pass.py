"""Find translated labels that do not fit, by diffing every language against English.

Tests cannot catch this: a label that overflows still passes every assertion
about its text. So walk the real window in each language and compare what each
text widget *needs* against what it was *given*.

**Reported as a diff against English, not as an absolute list.** Measuring
absolutely produces two dozen findings in English itself — mostly one- and
two-pixel artefacts of comparing font metrics against a laid-out width, plus a
few labels that are meant to be tight. Those are not translation bugs, and a
report full of them would bury the handful that are. What matters is a widget
that fits in English and stops fitting once translated, so each widget is
matched to its English self by position in the tree and only the *increase* is
reported.

Two rules, because the failure differs by widget:

* Text that does not wrap (buttons, checkboxes, plain labels) is **clipped**
  horizontally. Compare the font's advance for the string, plus the padding the
  stylesheet adds, against the widget's width.
* Text that wraps grows **downward**, so it overflows only if its container
  will not give it the height.

The stylesheet's `padding: 8px 16px` on QPushButton is invisible to sizeHint(),
the trap noted in CLAUDE.md — so buttons are measured from font metrics plus
that padding rather than from sizeHint.

Run at the window's own minimum size: the tightest layout a user can produce,
and where clipping bites first.

    python scripts/visual_pass.py                # all languages, diffed against en
    python scripts/visual_pass.py --shots DIR    # also save a PNG per language/page

It redirects its own app data and cannot touch your real Settings. It used to
say to do that yourself (``HOME=/tmp/vp python scripts/visual_pass.py``) and
that is not good enough: it persists a language to config on purpose (see
run()), so forgetting the prefix once leaves the app launching in whichever
language happened to run last — Korean, since ``ko`` sorts last. Which is
exactly what happened, twice, before this was made automatic.
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

REPO = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, REPO)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Redirect app data for this process *and* every child, at import — before
# anything can call get_app_data_dir(), which derives from HOME/%APPDATA%. The
# same trick as race_check.child_env, done here rather than only in child() so
# that a direct `--one <lang>` run is protected too. Children inherit VP_HOME
# and so reuse this directory instead of making their own.
_VP_HOME = os.environ.get("VP_HOME")
if not _VP_HOME:
    _VP_HOME = tempfile.mkdtemp(prefix="visual-pass-")
    os.environ["VP_HOME"] = _VP_HOME
    # Only the process that created it cleans it up, after its children exit.
    atexit.register(shutil.rmtree, _VP_HOME, ignore_errors=True)
if sys.platform == "win32":
    os.environ["APPDATA"] = _VP_HOME
    # HOME is not enough here, and setting only APPDATA is not either.
    # ``get_app_data_dir`` reads %APPDATA%, but ``get_history_dir`` also calls
    # ``_migrate_from_musickey``, which reads ``Path.home()`` — and on Windows
    # that resolves through ntpath.expanduser, which consults USERPROFILE and
    # then HOMEDRIVE+HOMEPATH and **never HOME**. So a win32 run that set only
    # HOME rendered the developer's real ~/.musickey sessions inside a report
    # that claims to be isolated. Set every name expanduser looks at.
    os.environ["USERPROFILE"] = _VP_HOME
    _drive, _tail = os.path.splitdrive(_VP_HOME)
    os.environ["HOMEDRIVE"] = _drive
    os.environ["HOMEPATH"] = _tail
    os.environ["HOME"] = _VP_HOME
else:
    os.environ["HOME"] = _VP_HOME

BUTTON_PADDING = 32      # qss: padding 8px 16px
CHECK_INDICATOR = 34     # indicator + spacing

# How much worse than English before it is worth a human looking. Small enough
# to catch a genuinely clipped word, large enough to ignore metric jitter.
REGRESSION_PX = 3

PAGES = [
    "player",
    "analysis",
    "convert",
    "rename",
    "metadata",
    "keyboard",
    "spectrum",
    "history",
    "settings",
]


def widget_key(w) -> str:
    """A path that identifies the same widget across languages.

    Class plus object name plus sibling index — none of which the language
    changes, unlike the text.
    """
    parts = []
    node = w
    while node is not None:
        parent = node.parent()
        idx = parent.children().index(node) if parent is not None else 0
        parts.append(f"{type(node).__name__}#{node.objectName() or '-'}[{idx}]")
        node = parent
    return "/".join(reversed(parts))


def measure(root, page: str, out: dict) -> None:
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QLabel,
        QPushButton,
        QRadioButton,
        QWidget,
    )

    from src.gui.widgets.elided_label import ElidedLabel

    for w in root.findChildren(QWidget):
        if not w.isVisible() or w.width() <= 0 or w.height() <= 0:
            continue
        # Handles its own overflow with an ellipsis; measuring text against
        # width here would report every elided label as a defect.
        if isinstance(w, ElidedLabel):
            continue

        if isinstance(w, QComboBox):
            # Ask the widget, not a constant. This used to be font metrics plus
            # a 48px COMBO_ARROW modelling the default QSS chrome (8px padding
            # and a 30px arrow, reserved twice over), so a combo styled any
            # other way was measured against the wrong allowance — the Convert
            # selectors carry a tighter rule and were reported clipped in four
            # languages while rendering in full.
            # sizeHint() is the style's own answer, computed from the widest
            # item and whatever padding actually applies, so it travels.
            out[widget_key(w)] = {
                "page": page,
                "type": type(w).__name__,
                "name": w.objectName() or "-",
                "text": w.currentText(),
                "over": w.sizeHint().width() - w.width(),
                "axis": "width",
            }
            continue
        if isinstance(w, QPushButton):
            text, slack = w.text(), BUTTON_PADDING
        elif isinstance(w, (QCheckBox, QRadioButton)):
            text, slack = w.text(), CHECK_INDICATOR
        elif isinstance(w, QLabel):
            text, slack = w.text(), 2
        else:
            continue

        if not text or not text.strip():
            continue

        if isinstance(w, QLabel) and w.wordWrap():
            over = w.heightForWidth(w.width()) - w.height()
            axis = "height"
        else:
            over = w.fontMetrics().horizontalAdvance(text) + slack - w.width()
            axis = "width"

        out[widget_key(w)] = {
            "page": page,
            "type": type(w).__name__,
            "name": w.objectName() or "-",
            "text": text,
            "over": over,
            "axis": axis,
        }


def assert_fonts_usable(app) -> None:
    """Abort rather than measure text in a fontless environment.

    Every number this script prints is a font advance, so a Qt install with no
    usable font database does not fail — it reports confident nonsense. Seen on
    Windows, where the offscreen plugin found no fonts and *every* glyph in
    every language, English included, rendered as an identical tofu box: the
    run was comparing character counts in a fixed-width fallback, so German
    ``Einstellungen`` was "over by 103px" purely for having five more letters
    than ``Settings``. It reported 55 regressions and took twenty minutes to
    disbelieve, because nobody can check this tool's arithmetic by eye.

    Two cheap signals, both about the *fallback* rather than about any one
    font. An empty family list is the obvious one. The load-bearing one is that
    a tofu fallback is fixed-width, so ``i`` and ``W`` measure the same — which
    stays true however the substitution is spelled, and is what actually
    distinguishes "no fonts" from "a font I did not expect".
    """
    from PySide6.QtGui import QFontDatabase, QFontMetrics

    families = QFontDatabase.families()
    metrics = QFontMetrics(app.font())
    narrow = metrics.horizontalAdvance("i")
    wide = metrics.horizontalAdvance("W")

    if families and narrow != wide:
        return

    why = (
        "no font families are available"
        if not families
        else f"'i' and 'W' both measure {narrow}px, i.e. a fixed-width fallback"
    )
    raise SystemExit(
        f"visual_pass: refusing to run — {why}.\n"
        f"  Every number this script prints is a font advance, so without a\n"
        f"  usable font database it would report confident nonsense rather\n"
        f"  than fail. QT_QPA_PLATFORM={os.environ.get('QT_QPA_PLATFORM')!r}.\n"
        f"  On Windows the offscreen plugin often has no fonts: re-run with\n"
        f"  QT_QPA_PLATFORM=windows. Override with VP_ALLOW_NO_FONTS=1 only if\n"
        f"  you intend to read the output as character counts."
    )


def run(lang: str, shots: Path | None) -> dict:
    from src.gui.app import create_qapplication, install_translators
    from src.utils.config import AppConfig, load_config, save_config

    # Persist the language *before* building anything, not just install the
    # translator. Widgets branch on load_config().language — the sidebar
    # shrinks one Russian label that way — so a harness that only installs
    # translations measures a configuration the app never actually runs in.
    save_config(replace(load_config(), language=lang))

    app = create_qapplication(["mixedinp"])
    if not os.environ.get("VP_ALLOW_NO_FONTS"):
        assert_fonts_usable(app)
    if lang != "en":
        install_translators(app, lang)

    from src.gui.main_window import MainWindow

    win = MainWindow()
    win.show()
    app.processEvents()
    if os.environ.get("VP_MIN"):
        # The enforced floor (600x683). Reachable by dragging, but not what
        # most users see — run both and treat the default size as the gate.
        win.resize(win.minimumSizeHint())
        app.processEvents()

    measured: dict = {}
    for page in PAGES:
        win._sidebar.set_current_page(page)
        win._on_page_changed(page)
        app.processEvents()
        measure(win, page, measured)
        if shots is not None:
            shots.mkdir(parents=True, exist_ok=True)
            win.grab().save(str(shots / f"{lang}-{page}.png"))
    return measured


def child(lang: str, shots: Path | None) -> dict:
    """One language per process — Qt does not want two QApplications."""
    import json

    args = [sys.executable, __file__, "--one", lang]
    if shots is not None:
        args += ["--shots", str(shots)]
    proc = subprocess.run(args, capture_output=True, text=True, cwd=REPO)
    if proc.returncode != 0:
        print(f"!! {lang} failed:\n{proc.stderr[-2000:]}")
        return {}
    return json.loads(proc.stdout)


def main() -> int:
    import json

    shots = None
    if "--shots" in sys.argv:
        shots = Path(sys.argv[sys.argv.index("--shots") + 1])

    if "--one" in sys.argv:
        lang = sys.argv[sys.argv.index("--one") + 1]
        print(json.dumps(run(lang, shots)))
        return 0

    from src.utils.i18n import LANGUAGES

    baseline = child("en", shots)
    print(f"english baseline: {len(baseline)} text widgets measured\n")

    total = 0
    for code, native in LANGUAGES:
        if code == "en":
            continue
        found = child(code, shots)
        if not found:
            continue

        rows = []
        for key, cur in found.items():
            base = baseline.get(key)
            if base is None:
                continue  # a widget English does not show; nothing to compare
            if cur["over"] > 0 and cur["over"] >= base["over"] + REGRESSION_PX:
                rows.append((cur, base))

        rows.sort(key=lambda r: -r[0]["over"])
        mark = "OK " if not rows else "!! "
        print(f"{mark}{code:6} {native:22} {len(rows)} regression(s)")
        for cur, base in rows:
            total += 1
            print(
                f"      [{cur['page']:9}] {cur['type']:12} "
                f"{cur['axis']} over by {cur['over']:4}px "
                f"(en: {base['over']:+}px)  {cur['text'][:52]!r}"
            )
    print(f"\n{total} regression(s) across all languages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
