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

Run it against a redirected HOME so it cannot overwrite your real Settings —
it persists a language to config on purpose (see run()):

    HOME=/tmp/vp python scripts/visual_pass.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

REPO = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, REPO)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BUTTON_PADDING = 32      # qss: padding 8px 16px
CHECK_INDICATOR = 34     # indicator + spacing
COMBO_ARROW = 48

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
            text, slack = w.currentText(), COMBO_ARROW
        elif isinstance(w, QPushButton):
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


def run(lang: str, shots: Path | None) -> dict:
    from src.gui.app import create_qapplication, install_translators
    from src.utils.config import AppConfig, load_config, save_config

    # Persist the language *before* building anything, not just install the
    # translator. Widgets branch on load_config().language — the sidebar
    # shrinks one Russian label that way — so a harness that only installs
    # translations measures a configuration the app never actually runs in.
    save_config(replace(load_config(), language=lang))

    app = create_qapplication(["mixedinp"])
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
