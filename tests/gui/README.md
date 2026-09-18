# Headless GUI tests

Run with the rest of the suite (`pytest tests/`) or on their own:

```bash
pytest tests/gui -v
```

They use **pytest-qt** (already in `requirements.txt`) and Qt's **offscreen**
platform plugin, forced in `conftest.py`. No window opens; a full run is well
under a second.

## What these tests are for

Panel **behaviour and data flow** — the logic layer of the GUI:

- sort order, and the display text a sort produces
- row ↔ data-index mapping (does the selected row return the right object?)
- state after refresh / repopulation
- signal emission and payloads (`qtbot.waitSignal`)
- enabled/disabled and visibility logic

## What these tests CANNOT catch

**`QT_QPA_PLATFORM=offscreen` uses the Fusion style, not macOS's
`QMacStyle`.** Every Mac-specific rendering bug in
`spitball/2026-06-09-session-report-qt-rendering-gotchas.md` was *invisible*
offscreen, and worse, offscreen produced false "it works" results.

So this suite gives you **no signal** on:

- text eliding / `…` truncation
- header and cell alignment
- padding, margins, and metrics
- stylesheet cascade and tooltip style leakage
- fonts, DPI, and anything else the platform style touches

Three more ways it measures a different app than the one users run:

- **No application stylesheet.** `conftest.py` never loads `app.qss.template`
  (it is app-global, so a test must not set it either), so padding, bold and
  sub-control rules are absent: `#treeCreateButton` is 80px here, 69px in the
  app — the gap runs the wrong way, so a clipped control has room in a test.
- **No fonts on Windows.** The offscreen plugin has no font database there,
  so text falls back to fixed-width tofu and a width is a character count.
  `visual_pass.py` refuses such a run; tests must be font-agnostic (compare
  two style-supplied numbers, never a pixel count).
- **Device pixels.** A `grab()` is in device pixels and `visualRect` in
  logical ones; multiply by `img.devicePixelRatio()`, and give any pixel
  check a control case that must fail.

A passing run here is **not** verification that a visual fix works. Those still
need a real window on a real Mac — see the "verification method" lesson in that
same report.

## Conventions

- Feed panels fake data by monkeypatching the loader the panel imports
  (e.g. `monkeypatch.setattr(history_panel, "load_analysis_entries", ...)`)
  rather than writing to the real app-data directory.
- Register every widget with `qtbot.addWidget(...)` so it's cleaned up.
- Assert on **rendered text** (`item.text()`), not only on ordering — a bug
  that corrupts display while preserving order is exactly how the `EditRole`
  regression slipped through (see
  `spitball/2026-07-21-history-export-and-sorting-plan.md`, section 3a).
