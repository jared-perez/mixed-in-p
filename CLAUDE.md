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
