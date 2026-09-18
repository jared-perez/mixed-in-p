# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mixed in P is a desktop application for DJs that:
- Analyzes audio files (AIFF, WAV, MP3, FLAC) for BPM, musical key and energy (1-10), shown as harmonic key codes (1A-12B) or traditional notation
- Batch-renames files from templates, converts between formats (WAV/FLAC/AIFF lossless, MP3 via lameenc), and edits metadata tags with auto-save and Discogs lookup
- Plays audio from a playlist library, with waveform, loop slicer, metronome, compatible-track suggestions and visualizers
- Has a keyboard panel: 3-octave piano, harmonic key reference, chord playback
- Routes files between panels by dropping them on the sidebar's nav buttons
- Runs a pipeline (rename → convert → analyze → file into a playlist), with a toggle per step in each panel and mirrored in the header

## Tech Stack

- **Language**: Python 3.11+
- **GUI**: PySide6
- **Audio Analysis**: librosa (BPM/key detection), soundfile (I/O)
- **Audio Encoding**: lameenc (MP3 encoding)
- **Audio Playback**: sounddevice (player, audition, slicer loop, keyboard, metronome)
- **Metadata**: mutagen (tag read/write/delete)
- **Library**: SQLite (playlists, tracks, FTS5 search)
- **Packaging**: PyInstaller

## Common Commands

```bash
# Virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Run application
python -m src.main

# Run tests
pytest tests/
pytest tests/test_analyzer.py -v  # Single test file

# Build executable
pyinstaller mixedinp.spec
```

**The shell here is zsh, not bash — never trust the exit code of a piped pytest.**
`pytest | tail` reports *tail's* status, and bash's `${PIPESTATUS[0]}` expands to
empty in zsh (it is `${pipestatus[1]}` there), so a failing run has looked like
`exit 0` more than once. Redirect to a file and read `$?` on the next line:

```zsh
venv/bin/python -m pytest tests/ -q > /tmp/out.log 2>&1; echo "EXIT=$?"
tail -3 /tmp/out.log; grep -cE "^(FAILED|ERROR)" /tmp/out.log   # 0 = clean
```

## Architecture

```
src/
├── main.py, cli.py      # Entry point; CLI (English-only, no tr())
├── analysis/            # BPM, key and energy detection; keycode.py maps key -> key code
├── conversion/          # Format conversion; result.py holds the quality-direction rules
├── metadata/tags.py     # mutagen tag read/write/delete; stores_tags()
├── renamer/             # Rename operations, preview/conflicts, session history (undo)
├── library/             # SQLite playlist library (library.py: schema + migrations), export, relocate
├── online/              # Discogs lookup and match ranking
├── utils/               # app_dirs (every persistent path), config, paths (normalize_track_path), i18n, args, default_app
└── gui/
    ├── app.py           # Startup: logging, translators, stylesheet
    ├── main_window.py   # The window: wires panels, sidebar, pipeline, open-with
    ├── single_instance.py, file_open_relay.py  # One-app claim and "Open with" handoff
    ├── convert_pipeline.py, play_context.py    # Qt-free state: a pipeline run; the playing row
    ├── styles/          # theme.py palettes, app.qss.template (@TOKEN@ placeholders), spin_arrows.py
    ├── translations/    # .ts/.qm per language; README has the workflow and glossary
    ├── widgets/         # One *_panel.py per page, shared widgets, vis_*.py visualizers, dialogs/
    ├── workers/         # QThread workers; thread_keeper.py for keep-alive and joins
    └── models/          # TrackStore/track model, app state, undo stack
scripts/                 # build_translations, race_check, visual_pass, vis_sheet, make_dmg_background
```

## Key Domain Knowledge

### Harmonic Key-Code Mapping

The key-code system maps musical keys to codes for harmonic mixing:

| Code | Minor Key | Code | Major Key |
|------|-----------|------|-----------|
| 1A   | G#m/A♭m   | 1B   | B         |
| 2A   | D#m/E♭m   | 2B   | F#/G♭     |
| 3A   | A#m/B♭m   | 3B   | C#/D♭     |
| 4A   | Fm        | 4B   | G#/A♭     |
| 5A   | Cm        | 5B   | D#/E♭     |
| 6A   | Gm        | 6B   | A#/B♭     |
| 7A   | Dm        | 7B   | F         |
| 8A   | Am        | 8B   | C         |
| 9A   | Em        | 9B   | G         |
| 10A  | Bm        | 10B  | D         |
| 11A  | F#m/G♭m   | 11B  | A         |
| 12A  | C#m/D♭m   | 12B  | E         |

Compatible keys for mixing: same number (relative major/minor) or +/-1 on same letter.

## Technical Considerations

Most design rationale lives in comments at the code it explains; read those
before changing a function. What is here are the traps that span files, or
that you would hit before reaching the code that explains them.

### Audio, analysis and conversion

- **BPM ambiguity**: electronic music reads as half/double tempo (64 vs 128), so detection is folded into a DJ range — 99-199 by default, set in Settings (`AppConfig.min_bpm`/`max_bpm`).
- **Conversion quality never goes up** (`src/conversion/result.py`): into another format only `raises_quality` is refused (an `error`); into the same format only a strict `is_quality_downgrade` runs, anything else is `skipped`; MP3 is exempt from both. A lossy source only ever becomes an MP3 at a strictly lower bitrate (`lowers_bitrate`), but it still gets a row: Convert used to refuse it at the door after a panel move had already taken it out of its old panel. Three call sites must agree or a row reads "Ready" and Convert does nothing: `convert_file`, the CLI dry run, and `ConversionPanel._verdict`. A `None` rate/depth means "Keep source" and must survive every hop (a Signal `object`, not `int`; `_optional_int` in config) — an `int` path silently turns it into 0.
- **WAV cannot hold BPM or key, yet `update_bpm_key` returns `True` for one**: ask `stores_tags()` (`src/metadata/tags.py`) whether a write will persist. Analysing a WAV is still allowed; the Analyze panel flags the row.
- **`TrackState` decides which panel owns a track**: one `TrackStore` backs Analyze, Rename, Convert and the queue; `QUEUED` *is* the Rename panel's working set, while Analyze shows `PENDING`/`ANALYSING`/`ANALYSED`/`ERROR`. A state change is a panel move (a cancelled analysis leaves tracks `PENDING`, not `QUEUED`), so check who owns a state before assigning it or widening a filter.
- **A cancel flag checked only at the top of a per-item loop can never cancel the last (or only) item.** Gate the terminal signal too, discard the in-flight item's result, and give items that already completed the same follow-through the finished path would (e.g. auto-rename after analysis).
- **What is playing is a *row in a playlist*, not a file, and not the list on screen** — see `src/gui/play_context.py`. Four traps: **never compare `PlaylistEntry` with `==`, `in` or `list.index`** (it is a dataclass, so two copies of one file are equal — use `index_of`); **don't add a per-item id column** (`set_items` rewrites wholesale; identity in memory plus stored position covers it); **an orphaned playing row never re-binds** to a same-path row on reload (that is a different copy); and **away from the playing list, read it fresh from the library** — the tree, pipeline, undo and delete edit it without telling the Player.
- **The Player writes the visible list's tags through to the library on every list change**, empty fields included (`_persist_playlist`), so a library row tagged behind its back is blanked by the next add. In tests, put fixture tags on the entry dicts passed to `add_tracks`, never on the library row afterwards.
- **A per-frame decay is a duration at only one frame rate.** The popout runs some visuals at 16 ms and the backdrop always at 33, so write any decay or frame count in seconds and rescale it in the host's `set_frame_interval` (`VisRenderer`, `BeatClock`, each `*Scene`). Pin it with a test that feeds the same second of audio at both rates.

### Paths, persistence and the library

- **Cross-platform paths**: use `src/utils/app_dirs.py` for all persistent data (config, history, library, logs). Never hardcode OS-specific paths.
- **Every path entering the app goes through `normalize_track_path`** (`src/utils/paths.py`): library identity is exact-string (`Library.add_track` keys on `WHERE path=?`, `duplicate_policy.filter_new` compares literals), and on Windows `QUrl.toLocalFile()`/`QFileDialog` give forward slashes while argv and `find_audio_files` give backslashes. Normalize where a path arrives from the OS or user (drop handler, dialog, argv, `QFileOpenEvent`) and **never** on a path read back from the database — the stored string *is* the identity.
- **Windows file locking**: mutagen file handles must be released before rename operations. The rename worker retries transient Windows locks.
- **PyInstaller**: use `sys._MEIPASS` for bundled resource paths when frozen. See `_get_base_path()` in `src/gui/app.py`.
- **The installed build has no console; the app logs to `<app data>/logs/mixedinp.log`** (`src/gui/app.py:setup_logging`, with a `sys.excepthook` for exceptions escaping Qt slots). Log every silent early return a user could report as "nothing happened". Tests call `teardown_logging()` after `setup_logging()`, or the open log blocks temp-dir deletion on Windows.
- **A new library column needs an ALTER, not just a `_SCHEMA` edit**: `CREATE TABLE IF NOT EXISTS` leaves existing databases on the old columns. Add the column to `_SCHEMA`, an `ALTER` in `Library._migrate` keyed on `PRAGMA table_info`, and bump `_SCHEMA_VERSION`; dry-run against a copy of a real `library.db`. A new *table* needs none of this; stored data that needs recomputing is keyed on `user_version`.
- **Name a persisted id for the mechanism, never the look, and rename one by retiring it.** Map the retired id one-way to whatever draws *the same picture* today, keyed on the stored value still being retired (`RETIRED_VIS_MODES` / `_renamed_vis_mode` in `src/utils/config.py`); a straight swap of two live ids has no safe trigger. Swapping *labels* is free in i18n as long as both source strings survive verbatim. When sweeping identifiers, `\bfoo\b` does not match inside `vis_foo` (`_` is a word character), so grep for survivors, and grep the human spelling separately.
- **`MainWindow._persist_config` re-reads panel-owned fields from disk before its wholesale save on close.** A new field a *panel* writes to config must join that merge list (with any sibling fields it travels with), or closing the window reverts it. A field the *window* owns must stay off it, or the save reverts the value it was called to save.
- **A control shown in two places has one owner and two reflects**: both widgets emit a request, `MainWindow` holds the state and reflects it into both inside `blockSignals` (the step toggles and their header minis).
- **Changing a *default* layout reaches nobody who has ever opened the app**, because a saved state wins. It needs a version and a one-time migration that writes the new version back immediately (`PlayerPanel._COLUMN_DEFAULTS_VERSION` / `AppConfig.player_column_defaults_version`). Express a default order as a *visual* order (`moveSection`), never by renumbering logical indexes, which saved states address sections by. Tests of the pre-migration path must stamp the current version, or they discard their own fixture.
- **`QHeaderView.restoreState` accepts a state saved from fewer columns, returns True, and leaves the header unable to save a restorable state.** Store the column count beside the state, apply defaults past it, and re-seat the header (`PlayerPanel._normalize_header`).

### Qt traps

- **`blockSignals` around every reflect.** Reflecting state into a checkable widget re-enters its own handler (`setChecked` fires `toggled`), and a handler that opens a modal hangs the suite — the handler acts, the reflect only shows (`ConversionPanel._sync_destination`). The flip side: `blockSignals` also silences a widget's own housekeeping, so anything a widget must do for itself on a state change (tooltip, repaint) belongs on Qt's hook — `checkStateSet()` for a `QAbstractButton` — never on a signal a caller may block (`PipelineToggle`).
- **`isVisible()` answers "is this on screen", not "is this switched on"**: it is False for every widget on a panel that isn't the current page, and for every widget in a dialog once `exec()` returns. Key such state off the control that owns it (a toggle's `isChecked()`, see `PlayerPanel.compat_panel_open`), or use `isHidden()`. In offscreen tests, assert `isHidden()`.
- **Bare `QWidget` containers are opaque**: `app.qss.template` opens with a global `QWidget { background-color: @BG_DARK@ }`, so a plain `QWidget`/`QStackedWidget` used as a layout container paints over the panel. Give it an object name and a `background-color: transparent` rule (`QStackedWidget` also needs `border: none`). See `#sidebarModeStack` / `#playlistTreePanel`.
- **A widget with states is styled by object name in `app.qss.template`, not with an inline `setStyleSheet`.** An inline rule carries none of the `:hover`/`:pressed`/`:disabled` states (a disabled button looks live) and hardcodes colours, which is wrong under `theme.py`'s four palettes. Conversely, a rule that must not leak to siblings goes under an object name, never the bare type (`#historyLimit`).
- **A stylesheet that targets `::item` defeats the model's `BackgroundRole`**: `app.qss.template` styles `QTableView::item`, so Qt ignores a brush returned from `data()`. Paint it in the delegate (`_NoFocusDelegate.paint` in `analysis_panel.py`), and test by sampling `viewport().grab()` — a `data()` assertion passes against the bug.
- **A drop that must not delete the source sets `CopyAction`**: outgoing drags from the Player/Analysis/Convert tables remove their rows when the drag returns `MoveAction`. A drop handler that keeps the source must call `event.setDropAction(Qt.DropAction.CopyAction)` **before** `event.accept()` (see `PlaylistTree._drop_tracks`).
- **A modal opened from inside a drop or drag handler fights Qt for the mouse grab**: accept the event, then fire the modal from `QTimer.singleShot(0, …)` (see `player_panel._guard_drag` and the duplicate prompt). The add is then *pending* when the handler returns, so follow-up work goes in the continuation.
- **`QProgressDialog.setValue()` pumps the event loop**, so a worker's `finished` can be delivered from inside your progress callback: set the label first and the value last, with nothing after it, and defer the terminal handler's work with `QTimer.singleShot(0, …)`.
- **Any edge-triggered Qt signal can fire before its receiver is attached, and the sender still reports success.** Drain a socket on take *and* on `disconnected` (`readyRead`); wire `newConnection` **before** `listen()` and then drain the queue once; buffer and replay app-level signals emitted during startup (`SingleInstance.start_delivering`, `FileOpenRelay.go_live`).
- **`deleteLater` on a child plus `deleteLater` on its parent is a double-free**: the parent takes the child with it, and the child's stale delete segfaults whatever runs *next*. Flush with `QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)` (children are posted first) and make drop/close paths idempotent.
- **A panel that starts reader threads must join them on close**: `stop_playback()` stops audio, not a decode or render in flight, which can only be waited out. Expose `shutdown_workers()` (built on `workers/thread_keeper.wait_for_threads`) and call it from the panel's `closeEvent` and from `MainWindow.closeEvent`, or you get `QThread: Destroyed while thread is still running`.
- **A panel that starts worker threads must also *forget* them when they finish**: clear the attributes from `thread.finished`, but only if they still name that thread, and guard any call into a possibly-deleted worker with `shiboken6.isValid` — otherwise a stale wrapper raises "Internal C++ object already deleted". Pattern: `PlayerPanel._on_artwork_thread_finished`; companion to `thread_keeper.keep_alive`.

### Layout and sizing

- **A width written as a constant is an English width, and "font metrics + a constant" is right on at most one platform.** Ask the style through the path that paints: `sizeHint()`, `header.sectionSizeHint(col)`, `resizeColumnToContents` (see `CompatibleTracksPanel._measure_narrow_columns`, `AnalysisPanel._fit_header_widths`). Where we paint a label ourselves, measure its own words with its own font and treat any constant as a floor-able base (`PlayerPanel._apply_header_fit_floor`).
- **`QLabel` never elides and a `QPushButton` centres its label**, so over-long text is cut at both ends with no ellipsis. Use `ElidedLabel` (`src/gui/widgets/elided_label.py`) for single-line text you don't control, and `HuggingElidedLabel`/`LinkLabel` for clickable text (their docstrings give the size-policy and tooltip rules). Size buttons, `QMessageBox` custom buttons included, from font metrics plus the QSS padding the native hint can't see (`_fit_buttons` in `dialogs/duplicate_policy.py`). A button smaller than the global `padding: 8px 16px` draws **no label at all**: give it an object-named rule zeroing padding/min-width/min-height (`#discogsApplyButton`).
- **Put QSS `font-size` on the widget selector (`QHeaderView { … }`), never a sub-control**, if anything measures `widget.font()`: `::section` is honoured when painting but never reaches `header.font()`. Row height doesn't follow the font either — scale `defaultSectionSize`, and don't use `resizeRowsToContents()`, which adds the QSS `::item` padding and nearly doubles every row.
- **Set a layout's spacing explicitly (`setSpacing(Theme.SPACING)`) whenever you wrap it in a widget or measure it.** A widget's own layout falls back to the style default (6px, not 8), and an unset one reads back `spacing() == -1`, so a `sum(hints) + spacing * gaps` width *subtracts*. In the same sums, a size hint ignores `setFixedWidth`: cap each term at `min(sizeHint().width(), maximumWidth())`.
- **Never read a size back from something you sized from it.** Decide geometry from inputs and `sizeHint()`s, never laid-out sizes (they are the geometry being replaced; a hidden widget's is stale). A `QLabel` holding a pixmap hints at that pixmap, and a word-wrapped widget reports `hasHeightForWidth`, after which layouts ignore `sizeHint().height()` — so `setFixedSize` from numbers the parent chose (`ArtworkWidget.set_column_width`, `PlayerPanel._text_row_height`).

### Tests and verification

- **The GUI suite cannot see layout, so a width or pixel assertion there says nothing about the app** (`tests/gui/README.md`). It runs offscreen with **no app stylesheet**, under **Fusion** rather than the platform style (QSS cannot change a style metric), and on Windows with **no fonts**. Write width tests as comparisons of two style-supplied numbers (`sizeHintForColumn(col) <= columnWidth(col)`), never pixel counts, and never `setStyleSheet` inside a test (it is app-global). `show()` on a widget whose parent is hidden leaves it invisible and changes Qt's behaviour — show the panel. For anything visual, render the real `MainWindow` with `load_stylesheet()` under the native style and look at it.
- **The suite is isolated from the developer's machine, and must stay that way.** `tests/conftest.py::isolated_app_data` (autouse) patches `src.utils.app_dirs.get_app_data_dir` to a per-test directory, so **every caller must import `get_app_data_dir` inside the function that uses it** — a module-level `from … import` binds its own copy and silently writes into the real app data. To give a widget a setting, `save_config()` an `AppConfig` before constructing it rather than patching `load_config`. **Anything deferred that reads app data must be flushed or cancelled on close**: the directory is resolved when the work fires, so a pending save lands in the next test's config (`PlayerPanel._flush_column_save`).
- **GUI test timing and modals.** `qtbot.wait(0)` does not drain the event queue — use `qtbot.wait(10)` (the `pump()` helpers) or `waitUntil` on the effect. Anything Qt computes lazily from layout (scroll ranges, `rowAt`) is stale until the loop runs, so wait *first*. A `waitUntil(lambda: x._thread is None)` passes on the state *before* a debounced worker starts: stop the debounce and call the load directly (`pump_art` in `tests/gui/test_player_artwork.py`). An unclicked modal hangs the suite: `tests/gui/conftest.py::duplicate_prompt_guard` turns a stray duplicate prompt into a named failure; a test that means to reach the box patches `duplicate_policy._prompt` itself.
- **`QMenu.exec` cannot be monkeypatched out** (PySide6 resolves it through C++), so a test that drives a context-menu handler opens a real modal and hangs the suite silently. Split building from exec'ing — `PlayerPanel._build_row_menu` returns `(menu, {name: action})` — and test the builder.
- **`QDropEvent` keeps only a raw pointer to its `QMimeData`**: in a test, `view.dropEvent(make_event(QMimeData()))` lets Python collect the mime object and the first `event.mimeData()` segfaults. Hold the `QMimeData` in a local for the event's lifetime.
- **Concurrent lazy imports abort the process**: a main-thread `read_metadata` (mutagen → charset_normalizer) racing a decode thread's lazy librosa import gives `Fatal Python error: Aborted` inside `<frozen importlib._bootstrap>`. Any test that pumps the event loop with a Player alive can trigger it, so warm imports up front: `tests/gui/conftest.py::warm_lazy_audio_imports` does librosa, and a module-level `warm_tag_reader` fixture does the tag reader (see `test_playlist_drag_add.py`). This is not the interpreter-teardown segfault.
- **`add_tracks` leaves one file open** (`_prefetch_default_target` decodes the selection, else row 0). On Windows that handle blocks delete/rename (`WinError 32`), invisibly on POSIX, so a test that deletes or renames a file it just added must call `PlayerPanel.wait_for_readers()` first (`tests/gui/helpers.py::unlink_when_released`).
- **Verify concurrency fixes with `python scripts/race_check.py [trials] [processes]`; don't reason about them.** It launches the real `src.main` N times at once with app data isolated, and passes only if exactly one process became primary and every file reached Scratch in `shell_sorted` order. A harness that *models* the component hides the bug. Re-run any timing-based regression test with the fix removed, since it can be vacuous on the other platform.
- **`python scripts/visual_pass.py` before a release** (`--shots DIR` saves PNGs). It renders all twelve languages at the window minimum and reports widgets whose text needs more width than they were given, **as a diff against English**; it isolates its own app data, and on Windows uses `QT_QPA_PLATFORM=windows` and refuses a fontless run. It measures only visible `QLabel`/`QPushButton`/`QComboBox`/`QCheckBox`/`QRadioButton` in the app's *default state* — placeholders, header sections, tooltips, popups, hidden controls and labels a setting changes are never measured, so measure those by hand (font metrics + `BUTTON_PADDING`, counting the QSS bold). `section_header` buttons are known false positives. The baseline moves: establish it from a `git worktree` at HEAD (never `git stash`) before calling a finding yours, and ground-truth any finding against a screenshot.

## UI copy

- **A tooltip is a reminder, not the manual.** Roughly one line: what the control does, plus a before/after example where that is the shortest explanation (see Space Dashes in `rename_panel.py`). Edge cases and rationale go in the docs; every extra sentence is one more to translate into 11 languages.
- **A toggle's tooltip says what the next click will do**, in both directions, and updates with the state. See `Sidebar._sync_playlists_tooltip`.

## Internationalization (i18n)

Qt's translation system: language is chosen in Settings and applied on restart
(`src/gui/app.py:install_translators`); languages are listed in
`src/utils/i18n.py` (`LANGUAGES`); files live in `src/gui/translations/`
(`.ts` source, `.qm` compiled). All eleven languages are fully translated.

**When adding or changing any user-facing GUI string, you MUST:**

1. **Wrap it for translation.** Never add a bare user-visible literal.
   - Inside a `QObject`/widget instance method: `self.tr("Text")`.
   - At class-body / module level / `@staticmethod`:
     `QCoreApplication.translate("ClassName", "Text")`.
   - For a literal defined away from where it's displayed (e.g. a module-level
     field-label list): mark with `QT_TRANSLATE_NOOP("Ctx", "Text")` and wrap
     with `self.tr(...)` at the display site. See `metadata_panel.py`.
2. **Refresh the translation files**: `python scripts/build_translations.py`
   (lupdate into every `.ts`, then lrelease). It preserves existing translations.
3. **Re-translate any string you EDIT, not just new ones.** Qt keys a
   translation by its exact source text, so changing one character marks the
   old translation `vanished` and drops that string to **English in every
   language**. Read the script's "Untranslated strings" summary after every
   string change (`--strict` exits non-zero). The old text survives in the
   `vanished` entry, so an edit can usually be spliced rather than
   re-translated. Settle the English copy *before* translating, and keep `tr()`
   strings small so an edit orphans only the part that changed.

**The context argument must be a literal.** `QCoreApplication.translate(_CTX, "…")`
with a module constant extracts **nothing** (lupdate cannot resolve a variable),
so those strings silently stay English in every language.

**`%n` plurals:** lupdate marks them only for `tr()`, not for
`QCoreApplication.translate()` — host such strings on a `QObject` (see
`DuplicatePrompt` in `dialogs/duplicate_policy.py`). And English ships the
*source text*, so "Applied %n field(s)" reaches English users with its `(s)`;
before reaching for a plural, ask whether the count is needed at all
(ru/pl need three forms, so spelling out two breaks them).

**Use plain `#` comments in any file with `tr()` strings** — lupdate harvests a
`#:` comment as translator guidance and staples it to the next string.

**Do NOT wrap** (data/config, not UI prose): note names and key codes ("8A",
"C#m"), audio format codes used as logic values ("WAV", "MP3"), tag/dict keys,
`setObjectName(...)` selectors, stylesheet strings, file-glob filters, and
`logger`/`print` messages. CLI strings (`src/cli.py`) stay English-only.

### Translation glossary

Buttons and titles use the infinitive/command form ("Renombrar", "Renommer",
"Переименовать"); feature labels use noun phrases; match Apple's localized UI
conventions. The reasons behind these rulings are in
`src/gui/translations/README.md` — read it before changing one.

- **English in ALL languages**: `BPM`, `beat tracking`, `Chroma`, key codes and
  note names, format codes (`WAV`, `MP3`, `FLAC`, `AIFF`, `M4A`, `OGG`), the
  product name "Mixed in P", and units (`dB`, `kHz`, `Hz`).
- **`sample`, `slicer`**: English in Latin-script languages; native script
  elsewhere (ru слайсер/сэмпл). "Sample rate" (DSP) is translated normally.
- **`pipeline`**: the loanword in es/fr/it/pt_BR, `пайплайн` in ru, `potok` in
  pl, `流水线` in zh_CN. Never "chain" (*cadena*, *cadeia*, *цепочка*…) — that
  was a deliberate reversal; don't restore it. ru's button is the noun
  `Запуск пайплайна` because the infinitive doesn't fit its 160px.
- **`stream`** (the backdrop visual): translated in every language as a plain
  noun (de `Strom`, ru `поток`, ja `流れ`). It replaced "Silly Scope", which was
  kept English; don't restore that from the `vanished` entries.
- **Localize phrases like "Send To"** in every language rather than leaving a
  Latin island in a localized UI.

Note a per-string change with a `<translatorcomment>`; never a raw `<!-- -->`
(lupdate strips it).
