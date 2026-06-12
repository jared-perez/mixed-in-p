#!/usr/bin/env python3
"""Regenerate and compile the app's Qt translation files.

Runs two steps for every language in ``src/utils/i18n.LANGUAGES`` (except the
"en" source language):

1. ``pyside6-lupdate`` — scan the source for ``tr()`` / ``translate()`` /
   ``QT_TRANSLATE_NOOP`` calls and refresh ``mixedinp_<code>.ts`` (preserving
   existing translations, adding new strings, marking removed ones obsolete).
2. ``pyside6-lrelease`` — compile each ``.ts`` into the binary ``.qm`` the app
   loads at startup.

After compiling, it reports how many strings are still ``unfinished`` (i.e.
fall back to English) in each language. This is the guard against silently
shipping a regression: editing an existing ``tr()`` string changes its key, so
``lupdate`` marks the old translation ``vanished`` and re-adds the changed
source as ``unfinished`` — dropping that string to English in every language
until it is re-authored. Watch this summary after any string change.

Run from the project root with the venv active:

    python scripts/build_translations.py            # build + warn
    python scripts/build_translations.py --strict   # also exit 1 if anything is untranslated

Requires ``pyside6-lupdate`` and ``pyside6-lrelease`` on PATH (they ship with
PySide6 in the venv). The generated ``.qm`` files are bundled by
``mixedinp.spec`` and committed so a plain checkout runs translated without a
build step.
"""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"
TRANSLATIONS = SRC / "gui" / "translations"

# Import the language list so this script and the app stay in sync.
sys.path.insert(0, str(PROJECT_ROOT))
from src.utils.i18n import LANGUAGES  # noqa: E402


def _run(cmd: list[str]) -> None:
    print("  $", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _untranslated(ts: Path) -> list[str]:
    """Return the source texts of every ``unfinished`` message in a ``.ts`` file.

    "Unfinished" means the translation is empty or not yet confirmed, so Qt falls
    back to the English source at runtime. ``vanished``/obsolete entries are
    ignored — they are previous translations kept for recovery, not live strings.
    """
    sources: list[str] = []
    try:
        root = ET.parse(ts).getroot()
    except (ET.ParseError, FileNotFoundError):
        return sources
    for message in root.iter("message"):
        translation = message.find("translation")
        if translation is not None and translation.get("type") == "unfinished":
            source = message.findtext("source") or ""
            sources.append(source)
    return sources


def _report_untranslated(codes: list[str]) -> int:
    """Print a per-language untranslated summary; return the total count.

    This is the guard: edits to existing strings drop them to English in every
    language, and this surfaces exactly which ones so the regression is caught
    before it ships instead of in the running app.
    """
    by_lang: dict[str, list[str]] = {}
    union: dict[str, int] = defaultdict(int)
    for code in codes:
        srcs = _untranslated(TRANSLATIONS / f"mixedinp_{code}.ts")
        by_lang[code] = srcs
        for s in srcs:
            union[s] += 1

    total = sum(len(v) for v in by_lang.values())
    if total == 0:
        print("All shipped languages fully translated. ✓")
        return 0

    print("\n⚠  Untranslated strings (these fall back to English at runtime):")
    for code in codes:
        n = len(by_lang[code])
        if n:
            print(f"    {code:<6} {n} untranslated")
    print("\n  Strings needing translation (language count in brackets):")
    for source in sorted(union):
        oneline = " ".join(source.split())
        if len(oneline) > 70:
            oneline = oneline[:67] + "..."
        print(f"    [{union[source]:>2}] {oneline}")
    print(
        "\n  If an edit changed an existing string, its old translation is kept as a\n"
        "  `vanished` entry in each .ts and can be recovered + re-authored.\n"
    )
    return total


def main() -> int:
    strict = "--strict" in sys.argv[1:]
    py_files = sorted(str(p) for p in SRC.rglob("*.py"))
    codes = [code for code, _ in LANGUAGES if code != "en"]
    TRANSLATIONS.mkdir(parents=True, exist_ok=True)

    print(f"Updating {len(codes)} translation file(s) from {len(py_files)} sources...")
    for code in codes:
        ts = TRANSLATIONS / f"mixedinp_{code}.ts"
        _run(["pyside6-lupdate", *py_files, "-ts", str(ts)])

    print("Compiling .ts -> .qm ...")
    for code in codes:
        ts = TRANSLATIONS / f"mixedinp_{code}.ts"
        _run(["pyside6-lrelease", str(ts)])

    print("Done.")
    total_untranslated = _report_untranslated(codes)

    if strict and total_untranslated:
        print("--strict: failing because untranslated strings remain.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
