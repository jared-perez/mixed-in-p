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
