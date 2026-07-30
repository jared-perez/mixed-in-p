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
- **PyInstaller**: Use `sys._MEIPASS` for bundled resource paths when frozen. See `_get_base_path()` in `src/gui/app.py`.
- **Panel routing**: Panels connect via "Send To" dropdowns (Rename → Analyze/Convert, Convert → Analyze) and sidebar drag-and-drop (drop files onto nav buttons).
- **A new column in the library database needs an ALTER, not just a schema edit**: `_SCHEMA` is run with `CREATE TABLE IF NOT EXISTS`, so an existing `library.db` keeps its old columns and a fresh install gets the new ones — the two diverge silently until a query hits the missing column. Add the column to `_SCHEMA`, add the `ALTER TABLE` to `Library._migrate` (keyed on `PRAGMA table_info`, not `user_version`), and bump `_SCHEMA_VERSION`. Dry-run it against a copy of the real database before shipping.
- **Bare `QWidget` containers are opaque**: `app.qss.template` opens with a global `QWidget { background-color: @BG_DARK@ }`, so any plain `QWidget` (or `QStackedWidget`) used purely as a layout container paints `BG_DARK` over whatever panel it sits on. Give such a container an object name and a `background-color: transparent` rule. `QStackedWidget` is also a `QFrame`, so it inherits the global 1px frame border too — add `border: none` unless a box is wanted. See `#sidebarModeStack` / `#playlistTreePanel`.
- **Moving a layout into a widget changes its spacing**: a nested layout inherits the parent layout's spacing; a widget's own layout falls back to the Qt style default (6px, not `Theme.SPACING`'s 8). Call `setSpacing(Theme.SPACING)` explicitly when wrapping an existing row in a container.
- **A drop that must not delete the source sets `CopyAction`**: outgoing drags from the Player/Analysis/Convert tables remove their rows when the drag returns `MoveAction`. Any drop handler that keeps the source intact must call `event.setDropAction(Qt.DropAction.CopyAction)` **before** `event.accept()` — see `PlaylistTree._drop_tracks` and `ReorderableTableWidget._handle_internal_reorder`. Forgetting it silently turns "add to playlist" into "move out of playlist".
- **The tree's own drags carry file URLs too**: a playlist dragged in `PlaylistTree` ships both `NODE_MIME` and its member tracks' URLs (one gesture reorders internally AND exports to Finder). Every drop handler must therefore check `NODE_MIME` **first** — treating such a drag as a file drop makes a playlist merge itself into whatever it lands on.
- **`QDropEvent` keeps only a raw pointer to its `QMimeData`**: in a test, `view.dropEvent(make_event(QMimeData()))` lets Python collect the mime object and the first `event.mimeData()` call segfaults. Hold the `QMimeData` in a local for the event's lifetime.
- **Concurrent lazy imports abort the process**: a main-thread `read_metadata` (mutagen → charset_normalizer) racing a decode thread's lazy librosa import produces `Fatal Python error: Aborted` with both threads inside `<frozen importlib._bootstrap>`. In tests, warm the imports up front — `tests/gui/conftest.py::warm_lazy_audio_imports` does librosa for every GUI test, `test_playlist_drag_add.py::warm_tag_reader` does the tag reader. Any test that pumps the event loop while a Player fixture is alive can trigger it, because pumping is what lets a queued prefetch actually start decoding. This signature is NOT the known interpreter-teardown segfault, which happens after every test has already passed.
- **A modal opened from inside a drop or drag handler fights Qt for the mouse grab**: fire it from `QTimer.singleShot(0, …)` instead, and accept the event first. Both the moved-file warning (`player_panel._guard_drag`) and the duplicate-tracks prompt do this. Consequence for the caller: the add is *pending*, not done, when the handler returns — so anything that must run afterwards goes in the continuation, and the accept/ignore verdict can't depend on the outcome. Accepting early is safe only because these drops are `CopyAction`, so a cancelled add leaves the source untouched anyway.
- **`qtbot.wait(0)` does not drain the event queue**: a test that uses it to "let the deferred dialog run" asserts against a prompt that never fired and passes for the wrong reason. Use `qtbot.wait(10)` (see the `pump()` helpers) or `qtbot.waitUntil` on the effect.
- **An unclicked modal hangs the whole suite**: `tests/gui/conftest.py::duplicate_prompt_guard` replaces the duplicate prompt with a recorder that answers Cancel and then fails the test naming the collision, so a stray prompt is a readable failure instead of a hang. It also pins `duplicate_policy` to the shipped default, since it is a user setting the suite must not inherit. A test that means to reach the box patches `duplicate_policy._prompt` itself.
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
