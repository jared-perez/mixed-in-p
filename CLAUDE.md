# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mixed in P is a desktop application for DJs that:
- Analyzes audio files (AIFF, WAV, MP3, FLAC) to detect BPM, musical key, and energy level (1-10)
- Displays results as harmonic key codes (1A-12A, 1B-12B) or traditional key notation
- Provides batch file renaming with customizable templates and "Send To" routing between panels
- Converts between audio formats (WAV, FLAC, AIFF lossless; MP3 encoding via lameenc)
- Slices audio files with visual range selection, nudge controls, and playback preview
- Edits metadata tags (title, artist, album, genre, BPM, key, year, track, comment) with auto-save
- Built-in audio player with playlist, transport controls, and drag-to-reorder
- Interactive keyboard panel with 3-octave piano, harmonic key strip reference, and chord playback
- Sidebar drag-and-drop: drop files onto nav buttons to route them to any panel

## Tech Stack

- **Language**: Python 3.11+
- **GUI**: PySide6
- **Audio Analysis**: librosa (BPM/key detection), soundfile (I/O)
- **Audio Encoding**: lameenc (MP3 encoding)
- **Audio Playback**: sounddevice (keyboard panel tone generation)
- **Metadata**: mutagen (ID3 tags, supports read/write/delete)
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

## Architecture

```
src/
├── main.py              # Entry point
├── cli.py               # CLI interface
├── analysis/            # Audio analysis engine
│   ├── analyzer.py      # Main analysis orchestrator
│   ├── bpm_detector.py  # librosa beat tracking
│   ├── key_detector.py  # Key estimation algorithms
│   ├── keycode.py       # Musical key -> harmonic key-code conversion
│   ├── energy_detector.py # Energy level detection
│   └── result.py        # Result dataclasses
├── conversion/          # Audio format conversion
│   ├── converter.py     # Lossless + MP3 conversion (WAV/FLAC/AIFF/MP3)
│   └── result.py        # Conversion result dataclass
├── metadata/            # File tag reading/writing/deleting
│   └── tags.py          # mutagen-based tag operations
├── renamer/             # File renaming system
│   ├── operations.py    # Rename operations (trim, prefix, etc.)
│   ├── preview.py       # Preview and conflict detection
│   └── history.py       # Session-based undo support
├── gui/                 # PySide6 interface
│   ├── app.py           # Application setup and entry
│   ├── main_window.py   # Main application window
│   ├── single_instance.py # One-app claim + file handoff ("Open with…")
│   ├── file_open_relay.py # macOS QFileOpenEvent, buffered until ready
│   ├── assets/          # Background images, icons, logo
│   │   ├── bg_*.png     # Panel background overlays
│   │   ├── icon.png     # App icon (gold P)
│   │   └── logo_title.png # Header bar logo
│   ├── styles/          # Theme and stylesheets
│   │   ├── theme.py     # Swappable colour palettes + Theme accessor
│   │   └── app.qss.template # QSS with @TOKEN@ palette placeholders (rendered at load)
│   ├── widgets/         # UI panels and components
│   │   ├── analysis_panel.py   # BPM/key/energy analysis results
│   │   ├── conversion_panel.py # Format conversion with Send To
│   │   ├── rename_panel.py     # Batch rename with Send To routing
│   │   ├── slice_panel.py      # Audio slicing with range selection
│   │   ├── player_panel.py     # Audio player with playlist
│   │   ├── metadata_panel.py   # Tag editor with auto-save
│   │   ├── keyboard_panel.py   # Piano + harmonic key strip reference
│   │   ├── settings_panel.py   # App configuration
│   │   ├── history_panel.py    # Rename undo history
│   │   ├── queue_panel.py      # File queue management
│   │   ├── sidebar.py          # Nav sidebar with drag-and-drop
│   │   ├── header_bar.py       # Header with logo
│   │   ├── range_slider.py     # Dual-handle range slider widget
│   │   ├── droppable_table.py  # Base table with file drop support
│   │   ├── drop_zone.py        # File drop zone widget
│   │   ├── linear_key_strip.py # Harmonic key strip (keyboard reference)
│   │   ├── loop_player.py      # Gapless A-B loop engine (slicer)
│   │   ├── progress_bar.py     # Progress indicator
│   │   └── dialogs/
│   │       └── about_dialog.py # About dialog with icon
│   ├── workers/         # Background thread workers
│   │   ├── analysis_worker.py  # Threaded audio analysis
│   │   ├── conversion_worker.py # Threaded format conversion
│   │   └── rename_worker.py    # Threaded file rename (with retry)
│   └── models/          # Data models and state
│       ├── state.py     # Application state
│       └── track_model.py # Track data model
└── utils/               # Shared utilities
    ├── app_dirs.py      # Cross-platform app data paths
    ├── args.py          # parse_audio_args + shell_sorted — the files the OS hands us, and their order
    ├── default_app.py   # "Make Mixed in P your default audio player" (LaunchServices / ms-settings)
    ├── paths.py         # normalize_track_path — one spelling per file
    └── config.py        # User settings persistence
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

- **BPM ambiguity**: Electronic music often has tempo that could be read as half/double (64 vs 128). Default to DJ-typical range (90-180 BPM).
- **Key detection confidence**: Show confidence scores and alternative suggestions; allow manual override.
- **Key notation modes**: Supports both key codes (1A-12B) and traditional key notation, toggled in Settings.
- **MP3 encoding**: Uses lameenc at 320 kbps default. Lossy-to-lossless upsampling is explicitly blocked.
- **Windows file locking**: mutagen file handles must be released before rename operations. The rename worker includes retry logic for transient Windows file locks.
- **Cross-platform paths**: Use `src/utils/app_dirs.py` for all persistent data (config, history). Never hardcode OS-specific paths.
- **Every path entering the app goes through `normalize_track_path`** (`src/utils/paths.py`): library identity is exact-string (`Library.add_track` keys on `WHERE path=?`, `duplicate_policy.filter_new` compares literals), so two spellings of one file mean two rows and a duplicate check that cannot see the collision. The Windows trap that proved it: `QUrl.toLocalFile()` **and** `QFileDialog` return forward slashes there (`C:/music/a.mp3`) while `find_audio_files` and argv return backslashes. Normalize at the point a path arrives from the OS or the user — a drop handler, a dialog result, argv, a `QFileOpenEvent` — and **never** on a path read back out of the database, where the stored string *is* the identity and rewriting it on load breaks row lookup, the playing-track marker and relocate.
- **PyInstaller**: Use `sys._MEIPASS` for bundled resource paths when frozen. See `_get_base_path()` in `src/gui/app.py`.
- **Panel routing**: Panels connect via "Send To" dropdowns (Rename → Analyze/Convert, Convert → Analyze) and sidebar drag-and-drop (drop files onto nav buttons).
- **A new column in the library database needs an ALTER, not just a schema edit**: `_SCHEMA` is run with `CREATE TABLE IF NOT EXISTS`, so an existing `library.db` keeps its old columns and a fresh install gets the new ones — the two diverge silently until a query hits the missing column. Add the column to `_SCHEMA`, add the `ALTER TABLE` to `Library._migrate` (keyed on `PRAGMA table_info`, not `user_version`), and bump `_SCHEMA_VERSION`. Dry-run it against a copy of the real database before shipping. Two different migration triggers, on purpose: a **column** is keyed on `PRAGMA table_info` (a version check would skip a database touched by a build predating the pragma bump, and re-adding a column is unrecoverable); **stored data that needs recomputing** is keyed on `user_version`, which also keeps it one-shot.
- **Making a field *searchable* is `_FTS_COLUMNS` plus a data migration**: the index statements are generated from that tuple (every name is also a `tracks` column), so adding one covers create/insert/update/resync in one edit — `_ensure_fts_schema` notices the column list changed and rebuilds `tracks_fts`, since an FTS5 table's columns are fixed at creation. What it does NOT cover is `search_blob`, the LIKE fallback's haystack: rows written before the change have a stored value their blob predates, so bump `_SCHEMA_VERSION` and call `_rebuild_search_blobs` (the `comment` addition was exempt only because a blank field can't change a blob). Rewrite a blob only via `_indexed_from_row` — the one call site that spelled the fields out by hand (`relink_track`) is exactly the one that broke when the tuple grew.
- **Bare `QWidget` containers are opaque**: `app.qss.template` opens with a global `QWidget { background-color: @BG_DARK@ }`, so any plain `QWidget` (or `QStackedWidget`) used purely as a layout container paints `BG_DARK` over whatever panel it sits on. Give such a container an object name and a `background-color: transparent` rule. `QStackedWidget` is also a `QFrame`, so it inherits the global 1px frame border too — add `border: none` unless a box is wanted. See `#sidebarModeStack` / `#playlistTreePanel`.
- **Moving a layout into a widget changes its spacing**: a nested layout inherits the parent layout's spacing; a widget's own layout falls back to the Qt style default (6px, not `Theme.SPACING`'s 8). Call `setSpacing(Theme.SPACING)` explicitly when wrapping an existing row in a container.
- **A drop that must not delete the source sets `CopyAction`**: outgoing drags from the Player/Analysis/Convert tables remove their rows when the drag returns `MoveAction`. Any drop handler that keeps the source intact must call `event.setDropAction(Qt.DropAction.CopyAction)` **before** `event.accept()` — see `PlaylistTree._drop_tracks` and `ReorderableTableWidget._handle_internal_reorder`. Forgetting it silently turns "add to playlist" into "move out of playlist".
- **The tree's own drags carry file URLs too**: a playlist dragged in `PlaylistTree` ships both `NODE_MIME` and its member tracks' URLs (one gesture reorders internally AND exports to Finder). Every drop handler must therefore check `NODE_MIME` **first** — treating such a drag as a file drop makes a playlist merge itself into whatever it lands on.
- **`QDropEvent` keeps only a raw pointer to its `QMimeData`**: in a test, `view.dropEvent(make_event(QMimeData()))` lets Python collect the mime object and the first `event.mimeData()` call segfaults. Hold the `QMimeData` in a local for the event's lifetime.
- **Concurrent lazy imports abort the process**: a main-thread `read_metadata` (mutagen → charset_normalizer) racing a decode thread's lazy librosa import produces `Fatal Python error: Aborted` with both threads inside `<frozen importlib._bootstrap>`. In tests, warm the imports up front — `tests/gui/conftest.py::warm_lazy_audio_imports` does librosa for every GUI test, `test_playlist_drag_add.py::warm_tag_reader` does the tag reader. Any test that pumps the event loop while a Player fixture is alive can trigger it, because pumping is what lets a queued prefetch actually start decoding. This signature is NOT the known interpreter-teardown segfault, which happens after every test has already passed.
- **A modal opened from inside a drop or drag handler fights Qt for the mouse grab**: fire it from `QTimer.singleShot(0, …)` instead, and accept the event first. Both the moved-file warning (`player_panel._guard_drag`) and the duplicate-tracks prompt do this. Consequence for the caller: the add is *pending*, not done, when the handler returns — so anything that must run afterwards goes in the continuation, and the accept/ignore verdict can't depend on the outcome. Accepting early is safe only because these drops are `CopyAction`, so a cancelled add leaves the source untouched anyway.
- **A panel that starts reader threads must join them on close**: `stop_playback()` ends the audio output, not the *readers* — a decode or render in flight is one long blocking call with nothing to cancel, so the only option is to wait. `PlayerPanel`/`SpectrumPanel` expose `shutdown_workers()` (built on `thread_keeper.wait_for_threads`), called from their own `closeEvent` and from `MainWindow.closeEvent`. Skipping it means `QThread: Destroyed while thread is still running` (undefined behaviour) and a worker emitting into a deleted receiver.
- **A single-instance claim must be an OS primitive that is exclusive *by contract* and released by the kernel when the process dies** — a named mutex on Windows, `flock` on POSIX (see `single_instance.py`). `QLocalServer` is the **transport only, never the claim**, on either platform: a Windows named pipe permits many servers on one name so a second `listen()` on a live name *succeeds*; and although a POSIX bind really is exclusive, there is a window where a primary has *created* its socket file and is not yet accepting, during which a connect is refused **identically** to a file left by a crash — so code that probes, sees the refusal and calls `removeServer` to clear the "stale" file unlinks a **live** primary's socket and each loser evicts the last. A refused connect cannot distinguish "dead" from "not ready yet" and the recovery for one is fatal to the other, so never guess at liveness; `removeServer` is only safe while holding the claim, which is the one place it is called.
- **Verify concurrency fixes with `python scripts/race_check.py`, don't reason about them.** Three separate single-instance designs looked correct, passed their unit tests, and gave *every* process electing itself primary the moment five started together — on both platforms, by different mechanisms. The script launches the real `src.main` (not a stand-in), redirects app data so it can't touch a real library, and passes only when exactly one process became primary, every file reached Scratch, **and** Scratch is in `shell_sorted` order. Two related habits it taught: a harness that *models* the component under test will hide the bug (a synthetic primary has its event loop running, while the real one spends ~500ms in `MainWindow()` with none); and always re-run a regression test with the fix removed, because a timing-based test for a platform-specific race is silently vacuous on the other platform — assert the invariant instead.
- **A multi-file "open" is not one call, and its arrival order means nothing.** Windows spawns **one process per file** for a multi-select (measured: five files, five processes, 25–43ms apart, `MultiSelectModel` does not change it) and macOS sends one `QFileOpenEvent` per file, so a batch reaches `MainWindow.open_files` as several calls in a racing order — different on every run. It therefore buffers for `OPEN_BATCH_MS` (300) and acts once, in `_flush_open_batch`, which sorts with `shell_sorted` (natural, filename-only, case-insensitive — what both shells show) and plays row 1. Two things that look optional and are not: the timer is **started, not restarted**, or a trickle of arrivals postpones playback indefinitely; and the *sort alone* is not enough, because without the wait the app has already committed to playing whichever process won the race. Raising the window stays immediate — a bare relaunch means "show me" and has no batch to wait for.
- **Becoming the *default* handler is opt-in, and the two platforms are not symmetric** (`src/utils/default_app.py`). macOS has an API (`LSSetDefaultRoleHandlerForContentType` via ctypes, no PyObjC) — guarded by a check that the process's own bundle identifier is `com.mixedinp.app`, because a handler is named by bundle and without the guard a source checkout hands every audio file to Python.app. Windows has none: `UserChoice` is hash-protected, writing it gets the association reset and looks like malware, so the button opens `ms-settings:defaultapps?registeredApp<Scope>=…` and the user confirms — with `<Scope>` **read** from whichever hive holds our `RegisteredApplications` value (HKLM → `Machine`, HKCU → `User`), never hardcoded. And **there is no readable "are we the default?" on Windows 11**: with our exe demonstrably launching, `assoc` said Windows Media Player, `UserChoice` said ZuneMusic and `UserChoiceLatest` had a hash and no ProgID, so `is_default()` answers `None` (unknowable) and the UI offers the action rather than a state. The macOS content-type list must stay equal to `LSItemContentTypes` in `mixedinp.spec` — LaunchServices silently refuses a type the bundle does not declare; a test asserts the two match. **The macOS write is asynchronous and `LSCopyDefaultRoleHandlerForContentType` is cached per process**: verified by hand, every call returned `noErr` and the plist really changed, yet the same process read the *old* handler back for seconds. So never confirm a set by reading it back (it reports failure for a change that worked), and never write a set-then-restore test — the two races itself and strands a type on the wrong app.
- **Any edge-triggered Qt signal can fire before its receiver is attached.** This bit three times in one module, each found only after fixing the one below: `readyRead` (on Windows it fires before `nextPendingConnection()` returns the socket — drain on take, *and* take a last read on `disconnected` before dropping); `newConnection` (a connection accepted between `listen()` and wiring the slot — wire the receiver **before** listening, then drain the queue once by hand); and an app-level signal emitted during startup, before the window that answers it exists (buffer and replay — `SingleInstance.start_delivering`, `FileOpenRelay.go_live`). The failures are silent and on the *success* path: the sender's write completes into the pipe buffer, so it reports success for a file that is then discarded.
- **`deleteLater` on a child plus `deleteLater` on its parent is a double-free waiting for an event loop**: whichever destroys the parent takes the children with it, and the child's stale delete lands on freed memory — surfacing as a segfault in whatever runs *next*, not where the bug is. Flush with `QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)` (post order: children first) rather than leaving it to a loop that may never come round again, and make any drop/close path idempotent.
- **`add_tracks` leaves a file open, and only *one*** — `_prefetch_default_target` warms the selection, else row 0. On Windows that read handle blocks the file from being deleted or renamed (`WinError 32`) for as long as the decode runs. A test that deletes the file it just added is racing that thread: it must call `PlayerPanel.wait_for_readers()` first (`tests/gui/helpers.py::unlink_when_released`). Two traps in diagnosing this: it is invisible on POSIX, where an open handle does not block an unlink; and it looks like a *teardown* problem because it only reproduces in a full run — but the contention from other tests' decodes is merely what widens the window, and the thread belongs to the failing test itself. The tell is which tests flake: those deleting the **first** file of a playlist, never the second. The user-facing version (rename a track mid-prefetch) is already covered — `rename_worker` retries `PermissionError` 3× at 0.3s, and the measured lock is 10–20ms.
- **When a fix makes an intermittent failure rarer without changing its signature, the surviving passes are the evidence.** Two rounds of raising a timeout took a Windows failure from 3-of-3 to 6-of-8, which felt like progress and was not — the signature never moved. What ended it was comparing a clean run against a failing one on the same machine minutes apart: the difference was *exactly one timeout*, which proved the process was not starved and the fault was local to one connection. That comparison is only available once a failure is intermittent, so the rarer-but-identical state is the one to exploit rather than to keep pushing on. Corollary to the entry below.
- **Don't drive `SingleInstance.send()` against a live primary in the same process** — use `hand_off` (`tests/gui/test_single_instance.py`), as every test there now does. On Windows that one connection is intermittently never serviced: 6 of 8 full-suite runs failed with `36 of 36 bytes still queued after 12000 ms`, load-sensitive in whether it fires but absolute when it does, under both a `qtbot.wait` spin and a real `QEventLoop`. It is local to the connection, not the process — a failing run is longer than a clean one by exactly the timeout, so everything else runs at normal speed around it. Raising the budget was the wrong instinct twice; the `N of M bytes` in the log is what settles it, since a whole frame still queued means the primary never read at all and no budget helps. The real cross-process path is `scripts/race_check.py`'s job, and one process was always a model of it.
- **Never join a worker thread from the thread whose event loop it needs**, and never stop pumping while it runs. `tests/gui/test_single_instance.py::run_off_the_main_thread` pumped with `qtbot.waitUntil` and then joined with `thread.wait()` (which does not pump), so the moment the worker was late the loop stopped — and since a Windows named-pipe write completes only once the server end reads, the join was waiting for a thread waiting for the join to stop. Pump in one loop, keep pumping through an overrun so the worker unwinds, and only then join. The diagnostic lesson is bigger than the fix: the abandoned worker still held the 30s `WRITE_TIMEOUT_MS` and logged `Timed out handing files` half a minute later **against whichever test was running by then** — so a stray log line does not belong to the test it is printed under once threads outlive tests, and a test that inherits a production timeout inherits that whole failure mode.
- **`qtbot.wait(0)` does not drain the event queue**: a test that uses it to "let the deferred dialog run" asserts against a prompt that never fired and passes for the wrong reason. Use `qtbot.wait(10)` (see the `pump()` helpers) or `qtbot.waitUntil` on the effect.
- **An unclicked modal hangs the whole suite**: `tests/gui/conftest.py::duplicate_prompt_guard` replaces the duplicate prompt with a recorder that answers Cancel and then fails the test naming the collision, so a stray prompt is a readable failure instead of a hang. It also pins `duplicate_policy` to the shipped default, since it is a user setting the suite must not inherit. A test that means to reach the box patches `duplicate_policy._prompt` itself.
- **The suite is isolated from the developer's own machine, and must stay that way**: `tests/conftest.py::isolated_app_data` (autouse) repoints `get_app_data_dir` at a throwaway directory, so `config.json`, `library.db` and the histories are per-test. Without it a test that reaches `load_config()` reads whatever was last chosen in Settings — which is how three `test_player_header_layout` tests passed here and failed on a fresh checkout. To give a widget a setting, build an `AppConfig` and `save_config()` it *before* constructing the widget; don't patch `load_config`, since a widget that imports it at module level has bound its own copy (see the next entry).
- **Don't read a user setting via `from … import helper` at a call site**: the name binds into the importing module, so patching it on the defining module has no effect and a test silently exercises the developer's own config. `resolve_additions` reads `duplicate_policy` itself for exactly this reason.
- **`#:` comments become translator guidance**: lupdate harvests a `#:`-prefixed comment as an `extracomment` and staples it onto the next translatable string, so internal implementation notes end up as instructions to translators. Use plain `#` in any file containing `tr()` strings.
- **A `QMessageBox` button with custom text clips its own label**: the stylesheet's `padding: 8px 16px` on `QPushButton` is invisible to the native size hint, so any label wider than the 80px `QDialogButtonBox QPushButton` minimum is drawn into a contents rect narrower than the text — and QMessageBox centres rather than elides, so it's cut off at *both* ends ("kip Duplicate"). Boxes built from standard buttons are short enough to escape it. Size such buttons from their own font metrics, not a constant, because the labels get translated — see `_fit_buttons` in `dialogs/duplicate_policy.py`.
- **`pyside6-lupdate` only marks `%n` plurals for `tr()`, not for `QCoreApplication.translate()`**: a module-level function using `translate()` with a count silently ships a string no translator can give plural forms for. Host such strings on a `QObject` so `self.tr(src, "", n)` applies — see `DuplicatePrompt` in `dialogs/duplicate_policy.py`.

## UI copy

- **A tooltip is a reminder, not the manual.** Keep it to roughly one line — what the control does, plus a before/after example where that is the shortest possible explanation (see Space Dashes in `rename_panel.py`). Edge cases and rationale go in the docs, not the hover. Every extra sentence is also a sentence to translate into 11 languages.
- **A toggle's tooltip says what the next click will do**, in both directions, and updates with the state — a checked button alone doesn't convey that Playlists *replaces* the nav rail rather than opening a panel. See `Sidebar._sync_playlists_tooltip` and the collapse chevron in `set_collapsed`.

## Internationalization (i18n)

The GUI is translatable via Qt's native translation system. Language is chosen
in Settings and applied on restart (a `QTranslator` is installed at startup in
`src/gui/app.py:install_translators`). The selectable languages live in
`src/utils/i18n.py` (`LANGUAGES`); translation files are in
`src/gui/translations/` (`.ts` = source, `.qm` = compiled/bundled).

**When adding or changing any user-facing GUI string, you MUST:**

1. **Wrap it for translation.** Never add a bare user-visible literal.
   - Inside a `QObject`/widget instance method: `self.tr("Text")`.
   - At class-body / module level / `@staticmethod` (no widget `self`):
     `QCoreApplication.translate("ClassName", "Text")`.
   - For a literal that must be defined away from where it's displayed (e.g. a
     module-level field-label list): mark with `QT_TRANSLATE_NOOP("Ctx", "Text")`
     and wrap with `self.tr(...)` at the display site. See `metadata_panel.py`.
2. **Refresh the translation files** after adding/removing strings:
   `python scripts/build_translations.py` (runs lupdate to extract new strings
   into every `.ts`, then lrelease to recompile the `.qm`). This preserves
   existing translations and is the only way new strings reach Qt Linguist.
3. **Re-translate any string you EDIT, not just new ones.** Qt keys a
   translation by its exact source text, so changing an existing `tr()` string
   (even one character) breaks the key: lupdate marks the old translation
   `vanished` and re-adds the changed source as `unfinished`, dropping that
   string to **English in every language** until it's re-authored. The build
   script prints an "Untranslated strings" summary at the end (and
   `--strict` exits non-zero) so this regression is caught here, not in the
   running app — read it after every string change. The old text survives in
   the `vanished` entry of each `.ts`, so an edit can usually be recovered and
   spliced rather than re-translated from scratch. Two habits avoid the churn:
   settle the English copy *before* translating, and keep translatable text in
   small, granular `tr()` strings (not one big block per screen) so an edit
   orphans only the part that changed.

**Do NOT wrap** (these are data/config, not UI prose): musical note names and
key codes (e.g. "8A", "C#m"), audio format codes used as logic values ("WAV",
"MP3"), tag/dict keys, `setObjectName(...)` selectors, stylesheet strings,
file-glob filter strings, and `logger`/`print` messages.

### Translation glossary (term handling per language)

When translating the `.ts` files, follow these term rules. Action buttons and
titles use the infinitive/command verb form (e.g. "Renombrar", "Renommer",
"Переименовать"); feature-list labels use noun phrases. Match Apple's localized
UI conventions for each language.

- **Keep in English in ALL languages**: `BPM`, `beat tracking`, `Chroma`,
  harmonic key codes (1A–12B / 1A–12A) and note names, and audio format codes
  (`WAV`, `MP3`, `FLAC`, `AIFF`, `M4A`, `OGG`). Also the product name
  "Mixed in P" and units (`dB`, `kHz`, `Hz`).
- **`sample`, `slicer`**: keep in English for Latin-script languages (es, fr,
  pt_BR, …); use native script for Cyrillic/non-Latin (ru: слайсер/сэмпл) so a
  Cyrillic UI stays consistent. (NB: "Sample Rate"/"Sample rate" is the DSP term
  and IS translated normally — it is not the producer "sample".)
- **`Send To`**: localize in ALL languages (es "Enviar a", fr "Envoyer vers",
  ru "Отправить в") — it reads as a Latin island in an otherwise localized UI.

Per-string changes during a translation audit get a `<translatorcomment>` noting
the reason; never use raw XML `<!-- -->` comments (lupdate strips them).

Untranslated strings always fall back to the English source, so a
partly-translated language is safe to ship. CLI strings (`src/cli.py`) are
intentionally left English-only. Full background: `src/gui/translations/README.md`.
