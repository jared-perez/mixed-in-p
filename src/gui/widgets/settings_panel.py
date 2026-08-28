"""Settings panel widget."""

import logging

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .fitted_combo import FittedComboBox

import sys
from dataclasses import replace

from ...online import discogs
from ...utils import default_app
from ...utils.config import AppConfig
from ...utils.i18n import LANGUAGES
from ..styles.theme import THEMES, Theme

logger = logging.getLogger(__name__)

# Preset waveform colors offered in Settings. The first entry is the "default"
# sentinel: selecting it makes the waveform follow the active theme's own
# default colour (see main_window._effective_waveform_color). It's shown as an
# outlined "Default" chip rather than a colour box.
_WAVEFORM_PRESETS = ("#f0ff00", "#006992", "#001d4a", "#c5ff15", "#00d61c")
_DEFAULT_PRESET = _WAVEFORM_PRESETS[0]


class SettingsPanel(QWidget):
    """Settings panel with tempo range and auto-rename options."""

    settings_changed = Signal()
    # "Export All Playlists…" clicked. The main window owns the library, so
    # the panel only asks; it never touches playlist data itself.
    # (Plain "#", not "#:" — lupdate harvests a "#:" comment as an
    # extracomment and staples it onto the next translatable string.)
    export_all_playlists = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(24)

        # ── Section 0: Language ────────────────────────────────────────────
        outer.addWidget(self._make_section_label(self.tr("Language")))

        language_frame = QFrame()
        language_frame.setObjectName("settingsSection")
        language_layout = QVBoxLayout(language_frame)
        language_layout.setContentsMargins(16, 10, 16, 10)
        language_layout.setSpacing(8)

        self._language_combo = FittedComboBox()
        for code, native in LANGUAGES:
            self._language_combo.addItem(native, code)
        # Pin to a compact fixed width sized to the longest language name (plus
        # room for the dropdown arrow) so it doesn't stretch across the panel.
        fm = self._language_combo.fontMetrics()
        widest = max((fm.horizontalAdvance(native) for _, native in LANGUAGES), default=80)
        self._language_combo.setFixedWidth(widest + 48)
        language_layout.addWidget(self._language_combo, alignment=Qt.AlignmentFlag.AlignLeft)

        language_hint = QLabel(self.tr("Restart to apply language changes."))
        language_hint.setObjectName("settingsHint")
        language_hint.setWordWrap(True)
        language_layout.addWidget(language_hint)

        outer.addWidget(language_frame)

        # ── Section: Default audio player ──────────────────────────────────
        # Sits with Language rather than at the bottom because both are
        # one-time setup, and because on Windows this button is the only route
        # to opening several files at once: Explorer's "Open with" submenu
        # does not appear for a multi-selection at all, so multi-file opening
        # happens through the default handler or not at all.
        if default_app.available():
            outer.addWidget(self._make_section_label(self.tr("Default Audio Player")))

            default_frame = QFrame()
            default_frame.setObjectName("settingsSection")
            default_layout = QVBoxLayout(default_frame)
            default_layout.setContentsMargins(16, 10, 16, 10)
            default_layout.setSpacing(8)

            self._default_app_btn = QPushButton(
                self.tr("Make Mixed in P your default audio player")
            )
            self._default_app_btn.clicked.connect(self._on_make_default_clicked)
            default_row = self._row_layout()
            default_row.addWidget(self._default_app_btn)
            default_row.addStretch(1)
            default_layout.addLayout(default_row)

            default_hint = QLabel(
                self.tr(
                    "Opens Windows Settings on the Mixed in P entry, where you "
                    "can hand it your audio file types. Windows only lets you "
                    "make that choice yourself."
                )
                if sys.platform == "win32"
                else self.tr(
                    "Double-clicking an audio file will open it here. Finder's "
                    "Get Info panel puts it back."
                )
            )
            default_hint.setObjectName("settingsHint")
            default_hint.setWordWrap(True)
            default_layout.addWidget(default_hint)

            outer.addWidget(default_frame)

        # ── Section: Theme ─────────────────────────────────────────────────
        outer.addWidget(self._make_section_label(self.tr("Theme")))

        theme_frame = QFrame()
        theme_frame.setObjectName("settingsSection")
        theme_layout = QVBoxLayout(theme_frame)
        theme_layout.setContentsMargins(16, 10, 16, 10)
        theme_layout.setSpacing(8)

        # Display names keyed by palette id. Falls back to the palette's own
        # label if a new theme is added without a label here. "Neon Dark"
        # (product-flavor name) and "Nuevo Leon" (proper noun) are deliberately
        # NOT tr()-wrapped — they stay English in every language; the other
        # names are descriptive and translate normally.
        # (``night_dark`` is labelled "Slate" — the id is what config stores,
        # so it kept its shipped spelling; see the palette's own comment.)
        theme_labels = {
            "nuevo_leon": "Nuevo Leon",
            "dark_mode": self.tr("Dark Mode"),
            "daylight": self.tr("Daylight"),
            "night_dark": self.tr("Slate"),
            "neon_dark": "Neon Dark",
        }
        self._theme_combo = FittedComboBox()
        for code, palette in THEMES.items():
            self._theme_combo.addItem(theme_labels.get(code, palette.label), code)
        # Size to the widest item (incl. the dropdown arrow + frame) at layout
        # time. Computing a fixed width here from fontMetrics underestimates,
        # because the larger stylesheet font isn't applied until setup finishes.
        self._theme_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        theme_layout.addWidget(self._theme_combo, alignment=Qt.AlignmentFlag.AlignLeft)

        theme_hint = QLabel(self.tr("Restart to apply theme changes."))
        theme_hint.setObjectName("settingsHint")
        theme_hint.setWordWrap(True)
        theme_layout.addWidget(theme_hint)

        outer.addWidget(theme_frame)

        # ── Section: Waveform color ────────────────────────────────────────
        outer.addWidget(self._make_section_label(self.tr("Waveform / Visuals")))

        wave_frame = QFrame()
        wave_frame.setObjectName("settingsSection")
        wave_layout = QVBoxLayout(wave_frame)
        wave_layout.setContentsMargins(16, 10, 16, 10)
        wave_layout.setSpacing(10)

        wave_hint = QLabel(self.tr("Color of the full-length waveform in the player."))
        wave_hint.setObjectName("settingsHint")
        wave_hint.setWordWrap(True)
        wave_layout.addWidget(wave_hint)

        # Live color, mirrored by the swatch borders. Set for real in load_config.
        self._waveform_color: str = _WAVEFORM_PRESETS[0]

        swatch_row = self._row_layout()
        swatch_row.setSpacing(8)
        self._wave_swatches: dict[str, QPushButton] = {}
        for hexcolor in _WAVEFORM_PRESETS:
            btn = QPushButton()
            btn.setObjectName("waveSwatch")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if hexcolor == _DEFAULT_PRESET:
                # Outlined "Default" chip (not a colour box) — follows the live
                # theme's default waveform colour. Sized to fit the (translated)
                # word; height matched to the colour swatches.
                btn.setText(self.tr("Default"))
                btn.setFixedHeight(28)
                btn.setToolTip(self.tr("Use the theme's default waveform color"))
            else:
                btn.setFixedSize(40, 28)
                btn.setToolTip(hexcolor)
            btn.clicked.connect(lambda _=False, c=hexcolor: self._select_waveform_color(c, emit=True))
            self._wave_swatches[hexcolor] = btn
            swatch_row.addWidget(btn)

        self._wave_custom_btn = QPushButton(self.tr("Custom…"))
        self._wave_custom_btn.clicked.connect(self._on_custom_waveform_color)
        swatch_row.addSpacing(8)
        swatch_row.addWidget(self._wave_custom_btn)
        swatch_row.addStretch(1)
        wave_layout.addLayout(swatch_row)

        outer.addWidget(wave_frame)
        self._restyle_waveform_swatches()

        # ── Section: Playlist text size ────────────────────────────────────
        outer.addWidget(self._make_section_label(self.tr("Playlist Text Size")))

        text_frame = QFrame()
        text_frame.setObjectName("settingsSection")
        text_layout = QVBoxLayout(text_frame)
        text_layout.setContentsMargins(16, 10, 16, 10)
        text_layout.setSpacing(10)

        text_hint = QLabel(
            self.tr("Size of the track rows in the player. Applies straight away.")
        )
        text_hint.setObjectName("settingsHint")
        text_hint.setWordWrap(True)
        text_layout.addWidget(text_hint)

        self._text_size_group = QButtonGroup(self)
        self._text_size_group.setExclusive(True)
        self._text_size_radios: dict[str, QRadioButton] = {}
        size_row = self._row_layout()
        for index, (size, label) in enumerate(
            (
                ("small", self.tr("Small")),
                ("medium", self.tr("Medium")),
                ("large", self.tr("Large")),
            )
        ):
            radio = QRadioButton(label)
            self._text_size_group.addButton(radio, index)
            self._text_size_radios[size] = radio
            size_row.addWidget(radio)
        self._text_size_radios["medium"].setChecked(True)
        size_row.addStretch(1)
        text_layout.addLayout(size_row)
        self._text_size_group.buttonClicked.connect(self._emit_changed)

        outer.addWidget(text_frame)

        # ── Section: Playlist artwork ──────────────────────────────────────
        # Its own section rather than another row inside Playlist Text Size:
        # the two do scale together, but a control placed under a section label
        # reads as belonging to it (the lesson from the energy-field checkbox),
        # and widening that label would orphan its translation in 11 languages.
        outer.addWidget(self._make_section_label(self.tr("Playlist Artwork")))

        art_frame = QFrame()
        art_frame.setObjectName("settingsSection")
        art_layout = QVBoxLayout(art_frame)
        art_layout.setContentsMargins(16, 10, 16, 10)
        art_layout.setSpacing(10)

        art_hint = QLabel(
            self.tr(
                "Part of the cover art shown in the player's Art column. "
                "Full makes each row tall enough for the whole sleeve."
            )
        )
        art_hint.setObjectName("settingsHint")
        art_hint.setWordWrap(True)
        art_layout.addWidget(art_hint)

        self._artwork_view_group = QButtonGroup(self)
        self._artwork_view_group.setExclusive(True)
        self._artwork_view_radios: dict[str, QRadioButton] = {}
        art_row = self._row_layout()
        for index, (view, label) in enumerate(
            (
                ("top", self.tr("Top")),
                ("middle", self.tr("Middle")),
                ("full", self.tr("Full")),
            )
        ):
            radio = QRadioButton(label)
            self._artwork_view_group.addButton(radio, index)
            self._artwork_view_radios[view] = radio
            art_row.addWidget(radio)
        self._artwork_view_radios["top"].setChecked(True)
        art_row.addStretch(1)
        art_layout.addLayout(art_row)
        self._artwork_view_group.buttonClicked.connect(self._emit_changed)

        outer.addWidget(art_frame)

        # ── Section 1: Tempo Range ──────────────────────────────────────────
        outer.addWidget(self._make_section_label(self.tr("Tempo Range")))

        bpm_frame = QFrame()
        bpm_frame.setObjectName("settingsSection")
        bpm_layout = QVBoxLayout(bpm_frame)
        bpm_layout.setContentsMargins(16, 10, 16, 10)
        bpm_layout.setSpacing(12)

        hint = QLabel(self.tr("Min 50, Max 250."))
        hint.setObjectName("settingsHint")
        bpm_layout.addWidget(hint)

        # Lowest BPM row
        low_row = self._row_layout()
        low_label = QLabel(self.tr("Lowest BPM"))
        low_label.setObjectName("settingsLabel")
        self._min_bpm_spin = QSpinBox()
        self._min_bpm_spin.setRange(50, 248)
        self._min_bpm_spin.setValue(99)
        # Measured, not 80: the stylesheet reserves room on the right for the
        # two arrow buttons, so a constant that fitted the number alone put
        # them on top of it. The floor keeps the shipped size.
        self._min_bpm_spin.setFixedWidth(max(80, self._min_bpm_spin.sizeHint().width()))
        low_row.addWidget(low_label)
        low_row.addStretch(1)
        low_row.addWidget(self._min_bpm_spin)
        low_row.addStretch(1)
        bpm_layout.addLayout(low_row)

        # Highest BPM row
        high_row = self._row_layout()
        high_label = QLabel(self.tr("Highest BPM"))
        high_label.setObjectName("settingsLabel")
        self._max_bpm_spin = QSpinBox()
        self._max_bpm_spin.setRange(52, 250)
        self._max_bpm_spin.setValue(199)
        self._max_bpm_spin.setFixedWidth(max(80, self._max_bpm_spin.sizeHint().width()))
        high_row.addWidget(high_label)
        high_row.addStretch(1)
        high_row.addWidget(self._max_bpm_spin)
        high_row.addStretch(1)
        bpm_layout.addLayout(high_row)

        outer.addWidget(bpm_frame)

        # ── Section 2: Auto-Rename ─────────────────────────────────────────
        outer.addWidget(self._make_section_label(self.tr("Key/BPM adding to filename after analysis")))

        rename_frame = QFrame()
        rename_frame.setObjectName("settingsSection")
        rename_layout = QVBoxLayout(rename_frame)
        rename_layout.setContentsMargins(16, 10, 16, 10)
        rename_layout.setSpacing(18)

        self._auto_analyze_cb = QCheckBox(self.tr("Auto-analyze when dropping or sending to the Analyze panel"))
        self._auto_analyze_cb.setObjectName("circleCheckLg")
        self._auto_analyze_cb.setChecked(True)
        rename_layout.addWidget(self._auto_analyze_cb)

        self._auto_write_bpm_cb = QCheckBox(self.tr("Automatically write BPM to metadata after analysis"))
        self._auto_write_bpm_cb.setChecked(True)
        rename_layout.addWidget(self._auto_write_bpm_cb)

        bpm_round_hint = QLabel(self.tr("BPM rounds to the nearest whole number when written to metadata."))
        bpm_round_hint.setObjectName("settingsHint")
        bpm_round_hint.setWordWrap(True)
        rename_layout.addWidget(bpm_round_hint)

        self._auto_write_key_cb = QCheckBox(self.tr("Automatically write the key to metadata after analysis"))
        self._auto_write_key_cb.setChecked(True)
        rename_layout.addWidget(self._auto_write_key_cb)

        self._auto_rename_cb = QCheckBox(self.tr("Automatically rename files after analysis"))
        self._auto_rename_cb.setChecked(True)
        rename_layout.addWidget(self._auto_rename_cb)

        # Added as direct widget children (like the checkboxes above) so they
        # share the same left edge — a horizontal sub-layout would inset the
        # first checkbox on some styles.
        self._key_in_comment_cb = QCheckBox(self.tr("Write key to comment"))
        self._key_in_comment_cb.setChecked(False)
        self._key_in_comment_cb.stateChanged.connect(self._emit_changed)
        rename_layout.addWidget(self._key_in_comment_cb)

        # Naming format sub-section
        format_label = QLabel(self.tr("Naming format:"))
        format_label.setObjectName("settingsSubLabel")
        rename_layout.addSpacing(8)
        rename_layout.addWidget(format_label)

        self._format_group = QButtonGroup(self)
        self._format_group.setExclusive(True)

        formats = [
            ("tempo_key_prefix", self.tr("128 8A - Original_File_Name"), self.tr("BPM + Key prefix")),
            ("key_tempo_prefix", self.tr("8A 128 - Original_File_Name"), self.tr("Key + BPM prefix")),
            ("key_prefix",       self.tr("8A - Original_File_Name"),     self.tr("Key prefix only")),
            ("suffix_key_tempo", self.tr("Original_File_Name - 8A 128"), self.tr("suffix: Key + BPM")),
            ("suffix_key",       self.tr("Original_File_Name - 8A"),     self.tr("suffix: Key only")),
        ]

        self._format_radios: dict[str, QRadioButton] = {}
        for i, (pref, example, explanation) in enumerate(formats):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            radio = QRadioButton(example)
            self._format_group.addButton(radio, i)
            self._format_radios[pref] = radio
            hint = QLabel(f"({explanation})")
            hint.setObjectName("settingsHint")
            row.addWidget(radio)
            row.addStretch(1)
            row.addWidget(hint)
            row.addStretch(1)
            rename_layout.addLayout(row)

        self._format_radios["tempo_key_prefix"].setChecked(True)

        outer.addWidget(rename_frame)

        # ── Section 3: Notation ───────────────────────────────────────────
        outer.addWidget(self._make_section_label(self.tr("Notation")))

        notation_frame = QFrame()
        notation_frame.setObjectName("settingsSection")
        notation_layout = QVBoxLayout(notation_frame)
        notation_layout.setContentsMargins(16, 10, 16, 10)
        notation_layout.setSpacing(18)

        notation_hint = QLabel(
            self.tr(
                "Only one notation can be active at a time. Applies to the key written "
                "to tags/filenames during analysis and to the Keyboard panel key labels."
            )
        )
        notation_hint.setObjectName("settingsHint")
        notation_hint.setWordWrap(True)
        notation_layout.addWidget(notation_hint)

        self._notation_group = QButtonGroup(self)
        self._notation_group.setExclusive(True)

        notations = [
            ("keycode",     self.tr("👑 Key Codes  (8A, 5A, 2B)")),
            ("traditional", self.tr("Traditional Key Notation  (Am, Ebm, F#…)")),
            ("open_key",    self.tr("Traktor Open Key  (1m, 10m, 9d…)")),
        ]

        self._notation_radios: dict[str, QRadioButton] = {}
        for i, (value, label) in enumerate(notations):
            radio = QRadioButton(label)
            self._notation_group.addButton(radio, i)
            self._notation_radios[value] = radio
            notation_layout.addWidget(radio)

        self._notation_radios["keycode"].setChecked(True)
        self._notation_group.buttonClicked.connect(self._emit_changed)

        outer.addWidget(notation_frame)

        # ── Section 4: Energy Tag ─────────────────────────────────────────
        outer.addWidget(self._make_section_label(self.tr("Energy Tag")))

        energy_frame = QFrame()
        energy_frame.setObjectName("settingsSection")
        energy_layout = QVBoxLayout(energy_frame)
        energy_layout.setContentsMargins(16, 16, 16, 16)
        energy_layout.setSpacing(18)

        self._energy_enabled_cb = QCheckBox(self.tr("Write energy level to Comment tag"))
        self._energy_enabled_cb.setChecked(True)
        self._energy_enabled_cb.stateChanged.connect(self._emit_changed)
        energy_layout.addWidget(self._energy_enabled_cb)

        # When both energy and key are written to the comment, this gives the
        # energy info priority (written first). Indented via its QSS margin
        # (objectName "circleCheck") to read as a sub-option.
        self._energy_written_first_cb = QCheckBox(self.tr("Energy level written first"))
        self._energy_written_first_cb.setObjectName("circleCheck")
        self._energy_written_first_cb.setChecked(True)
        self._energy_written_first_cb.setToolTip(
            self.tr("When both energy and key are written to the comment, put energy first and key second.")
        )
        self._energy_written_first_cb.stateChanged.connect(self._emit_changed)
        energy_layout.addWidget(self._energy_written_first_cb)

        # Format sub-section
        fmt_label = QLabel(self.tr("Format:"))
        fmt_label.setObjectName("settingsSubLabel")
        energy_layout.addSpacing(4)
        energy_layout.addWidget(fmt_label)

        self._energy_format_group = QButtonGroup(self)
        self._energy_format_group.setExclusive(True)

        self._radio_number_only = QRadioButton(self.tr("Number only  (7)"))
        self._radio_with_label = QRadioButton(self.tr("With label  (Energy 7)"))
        self._radio_number_only.setChecked(True)

        self._energy_format_group.addButton(self._radio_number_only, 0)
        self._energy_format_group.addButton(self._radio_with_label, 1)
        energy_layout.addWidget(self._radio_number_only)
        energy_layout.addWidget(self._radio_with_label)

        # Write mode sub-section
        mode_label = QLabel(self.tr("Write mode:"))
        mode_label.setObjectName("settingsSubLabel")
        energy_layout.addSpacing(4)
        energy_layout.addWidget(mode_label)

        self._energy_mode_group = QButtonGroup(self)
        self._energy_mode_group.setExclusive(True)

        self._radio_prepend = QRadioButton(self.tr("Prepend to existing comment"))
        self._radio_append = QRadioButton(self.tr("Append to existing comment"))
        self._radio_replace = QRadioButton(self.tr("Replace existing comment"))
        self._radio_prepend.setChecked(True)

        self._energy_mode_group.addButton(self._radio_prepend, 0)
        self._energy_mode_group.addButton(self._radio_append, 1)
        self._energy_mode_group.addButton(self._radio_replace, 2)
        energy_layout.addWidget(self._radio_prepend)
        energy_layout.addWidget(self._radio_append)
        energy_layout.addWidget(self._radio_replace)

        self._energy_format_group.buttonClicked.connect(self._emit_changed)
        self._energy_mode_group.buttonClicked.connect(self._emit_changed)

        # Last in the section, and deliberately not next to the comment
        # checkbox: everything above this line — written-first, format, write
        # mode — describes the *comment*, and a control placed between them
        # would read as one more of those. This one is independent of all of
        # it. On by default: a comment is prose, so an energy read back out of
        # one has to be guessed at, while a field of its own round-trips.
        energy_layout.addSpacing(8)
        self._energy_field_cb = QCheckBox(self.tr("Write energy level to its own tag field"))
        self._energy_field_cb.setChecked(True)
        self._energy_field_cb.setToolTip(
            self.tr("Stores the energy where it can be read back exactly, instead of parsed out of the comment.")
        )
        self._energy_field_cb.stateChanged.connect(self._emit_changed)
        energy_layout.addWidget(self._energy_field_cb)

        outer.addWidget(energy_frame)

        # ── Section: Online Metadata ────────────────────────────────────────
        outer.addWidget(self._make_section_label(self.tr("Online Metadata")))

        online_frame = QFrame()
        online_frame.setObjectName("settingsSection")
        online_layout = QVBoxLayout(online_frame)
        online_layout.setContentsMargins(16, 10, 16, 10)
        online_layout.setSpacing(8)

        self._online_lookup_cb = QCheckBox(
            self.tr("Look up track details online (Discogs)")
        )
        self._online_lookup_cb.setObjectName("circleCheckLg")
        self._online_lookup_cb.setChecked(False)
        online_layout.addWidget(self._online_lookup_cb)

        online_hint = QLabel(
            self.tr(
                "Off by default, and the app makes no network requests until you "
                "turn it on. A lookup sends the artist and title of the track you "
                "chose — never your audio, and never your library. BPM, key and "
                "energy always come from this app's own analysis."
            )
        )
        online_hint.setObjectName("settingsHint")
        online_hint.setWordWrap(True)
        online_layout.addWidget(online_hint)

        token_row = self._row_layout()
        token_row.addWidget(QLabel(self.tr("Discogs token:")))
        # Whether the token box held anything before the keystroke being
        # handled. See _on_token_text_changed.
        self._had_token = False
        self._discogs_token_edit = QLineEdit()
        self._discogs_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._discogs_token_edit.setPlaceholderText(self.tr("Paste your token"))
        self._discogs_token_edit.setMinimumWidth(260)
        token_row.addWidget(self._discogs_token_edit, 1)
        self._token_help_btn = QPushButton(self.tr("Get a Token…"))
        self._token_help_btn.clicked.connect(self._on_token_help_clicked)
        token_row.addWidget(self._token_help_btn)
        online_layout.addLayout(token_row)

        token_hint = QLabel(
            self.tr(
                "Discogs needs a free personal token to answer with cover images "
                "and at full speed. It is read-only, and you can revoke it on "
                "your Discogs account page at any time."
            )
        )
        token_hint.setObjectName("settingsHint")
        token_hint.setWordWrap(True)
        online_layout.addWidget(token_hint)

        self._fetch_artwork_cb = QCheckBox(self.tr("Fetch cover art with lookups"))
        self._fetch_artwork_cb.setObjectName("circleCheckLg")
        self._fetch_artwork_cb.setChecked(True)
        online_layout.addWidget(self._fetch_artwork_cb)

        artwork_hint = QLabel(
            self.tr(
                "Shows the release's cover next to your file's, so you can "
                "compare them. Nothing is written until you approve it."
            )
        )
        artwork_hint.setObjectName("settingsHint")
        artwork_hint.setWordWrap(True)
        online_layout.addWidget(artwork_hint)

        outer.addWidget(online_frame)

        # ── Section: Playlists ──────────────────────────────────────────────
        outer.addWidget(self._make_section_label(self.tr("Playlists")))

        playlist_frame = QFrame()
        playlist_frame.setObjectName("settingsSection")
        playlist_layout = QVBoxLayout(playlist_frame)
        playlist_layout.setContentsMargins(16, 10, 16, 10)
        playlist_layout.setSpacing(8)

        dup_row = self._row_layout()
        dup_row.addWidget(QLabel(self.tr("Duplicate tracks:")))
        self._duplicate_policy_combo = FittedComboBox()
        for label, code in (
            (self.tr("Ask each time"), "ask"),
            (self.tr("Always add duplicates"), "add"),
            (self.tr("Always skip duplicates"), "skip"),
        ):
            self._duplicate_policy_combo.addItem(label, code)
        self._duplicate_policy_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        dup_row.addWidget(self._duplicate_policy_combo)
        dup_row.addStretch(1)
        playlist_layout.addLayout(dup_row)

        dup_hint = QLabel(
            self.tr(
                "What happens when you add a track a playlist already contains. "
                "A set list can repeat a track on purpose, so this asks rather "
                "than deciding for you — pick one of the other options to stop "
                "being asked."
            )
        )
        dup_hint.setObjectName("settingsHint")
        dup_hint.setWordWrap(True)
        playlist_layout.addWidget(dup_hint)

        self._persist_scratch_cb = QCheckBox(self.tr("Keep Scratch between sessions"))
        self._persist_scratch_cb.setObjectName("circleCheckLg")
        self._persist_scratch_cb.setChecked(False)
        playlist_layout.addWidget(self._persist_scratch_cb)

        scratch_hint = QLabel(
            self.tr(
                "Scratch is the working list the Player opens on, and it starts "
                "empty each time you launch. Turn this on to have it reopen with "
                "whatever was in it — either way, Save Playlist keeps a copy."
            )
        )
        scratch_hint.setObjectName("settingsHint")
        scratch_hint.setWordWrap(True)
        playlist_layout.addWidget(scratch_hint)

        self._export_absolute_cb = QCheckBox(
            self.tr("Always use full paths in exported playlists")
        )
        self._export_absolute_cb.setObjectName("circleCheckLg")
        self._export_absolute_cb.setChecked(False)
        playlist_layout.addWidget(self._export_absolute_cb)

        export_hint = QLabel(
            self.tr(
                "Exported playlists use paths relative to the playlist file when "
                "the tracks sit beside it, so a folder you zip and send still "
                "works on someone else's machine. Turn this on to always write "
                "the full path instead."
            )
        )
        export_hint.setObjectName("settingsHint")
        export_hint.setWordWrap(True)
        playlist_layout.addWidget(export_hint)

        self._export_all_btn = QPushButton(self.tr("Export All Playlists…"))
        self._export_all_btn.clicked.connect(self.export_all_playlists.emit)
        export_all_row = self._row_layout()
        export_all_row.addWidget(self._export_all_btn)
        export_all_row.addStretch(1)
        playlist_layout.addLayout(export_all_row)

        export_all_hint = QLabel(
            self.tr(
                "Writes one folder of playlist files mirroring your tree — a "
                "backup any other app can read."
            )
        )
        export_all_hint.setObjectName("settingsHint")
        export_all_hint.setWordWrap(True)
        playlist_layout.addWidget(export_all_hint)

        outer.addWidget(playlist_frame)

        outer.addStretch()

        scroll.setWidget(container)
        root.addWidget(scroll)

        # Wire signals
        self._min_bpm_spin.valueChanged.connect(self._on_min_changed)
        self._max_bpm_spin.valueChanged.connect(self._on_max_changed)
        self._auto_rename_cb.stateChanged.connect(self._emit_changed)
        self._auto_write_bpm_cb.stateChanged.connect(self._emit_changed)
        self._auto_write_key_cb.stateChanged.connect(self._emit_changed)
        self._auto_analyze_cb.stateChanged.connect(self._emit_changed)
        self._export_absolute_cb.stateChanged.connect(self._emit_changed)
        self._persist_scratch_cb.stateChanged.connect(self._emit_changed)
        self._online_lookup_cb.stateChanged.connect(self._emit_changed)
        self._fetch_artwork_cb.stateChanged.connect(self._emit_changed)
        # editingFinished, not textChanged: a token is pasted in one go, and
        # persisting per keystroke would write a dozen half-tokens to disk.
        self._discogs_token_edit.editingFinished.connect(self._emit_changed)
        # ...and textChanged only to *reflect* the tick, never to save it.
        self._discogs_token_edit.textChanged.connect(self._on_token_text_changed)
        self._duplicate_policy_combo.currentIndexChanged.connect(self._emit_changed)
        self._format_group.buttonClicked.connect(self._emit_changed)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)

        # Style the spinboxes and frame
        self.setStyleSheet(self._build_stylesheet())

    # ── Helpers ────────────────────────────────────────────────────────────

    def _on_token_text_changed(self, text: str) -> None:
        """Filling the token box switches the lookup on — that is what it is for.

        Nobody pastes a Discogs token in order to leave Discogs switched off,
        and the two controls sat one above the other with the feature silently
        still off, which reads as a token that did not take.

        Two limits on it. It fires on the **empty → filled** transition only,
        so it cannot re-tick a box someone deliberately cleared while editing
        an existing token. And it only ever switches the feature *on*: a lookup
        works without a token (slower, and with no cover art), so clearing the
        field is not a request to turn the feature off, and an auto-off would
        overrule anyone running it untokened on purpose.

        The tick is reflected with the checkbox's signal blocked and left for
        the field's own ``editingFinished`` to persist, alongside the token it
        belongs with. Ticking it for real here would emit on every keystroke
        and write those half-tokens to disk — the very thing the line above
        exists to avoid.
        """
        had_token = self._had_token
        self._had_token = bool(text.strip())
        if had_token or not self._had_token or self._online_lookup_cb.isChecked():
            return
        self._online_lookup_cb.blockSignals(True)
        self._online_lookup_cb.setChecked(True)
        self._online_lookup_cb.blockSignals(False)

    def _on_token_help_clicked(self) -> None:
        """Open the Discogs page where a personal token is generated."""
        QDesktopServices.openUrl(QUrl(discogs.TOKEN_PAGE_URL))

    def _on_make_default_clicked(self) -> None:
        """Ask the OS, then say only what actually happened.

        The silent case is the Windows one: Settings comes to the front on our
        entry, and a message box on top of it would be telling the user
        something they can already see. Everything else gets a sentence,
        because nothing visible happened.
        """
        result = default_app.make_default()
        logger.info("Default audio player: %s %s", result.outcome.value, result.detail)

        title = self.tr("Default Audio Player")
        if result.outcome is default_app.Outcome.HANDED_OFF:
            return
        if result.outcome is default_app.Outcome.DONE:
            QMessageBox.information(
                self, title, self.tr("Mixed in P now opens your audio files.")
            )
            return

        # Both remaining outcomes need the same thing from the user: the route
        # that always works. Only macOS has one worth spelling out, so the two
        # are told apart by platform rather than by outcome — the severity is
        # what the outcome decides, since not-installed-yet is not a fault.
        if sys.platform == "win32":
            text = (
                self.tr(
                    "Mixed in P is not registered with Windows. Reinstalling "
                    "it will register it."
                )
                if result.outcome is default_app.Outcome.UNSUPPORTED
                else self.tr(
                    "Windows Settings did not open. You can set this yourself "
                    "there, under Apps → Default apps."
                )
            )
        else:
            text = self.tr(
                "Select an audio file in Finder, press Command-I, choose Mixed "
                "in P under “Open with”, then click Change All."
            )

        if result.outcome is default_app.Outcome.UNSUPPORTED:
            QMessageBox.information(self, title, text)
        else:
            QMessageBox.warning(self, title, text)

    @staticmethod
    def _row_layout():
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        return row

    @staticmethod
    def _make_section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("settingsSectionTitle")
        return lbl

    def _build_stylesheet(self) -> str:
        return f"""
            QLabel#settingsSectionTitle {{
                color: {Theme.NEON_YELLOW};
                font-size: 14px;
                font-weight: bold;
            }}
            QLabel#settingsLabel {{
                color: {Theme.TEXT_PRIMARY};
                font-size: 13px;
            }}
            QLabel#settingsSubLabel {{
                color: {Theme.TEXT_SECONDARY};
                font-size: 12px;
            }}
            QLabel#settingsHint {{
                color: {Theme.TEXT_SECONDARY};
                font-size: 11px;
                font-style: italic;
            }}
            QFrame#settingsSection {{
                background-color: transparent;
                border: none;
            }}
            QSpinBox {{
                background-color: {Theme.BG_LIGHT};
                color: {Theme.TEXT_PRIMARY};
                border: 1px solid {Theme.CHROME_DARK};
                border-radius: {Theme.BORDER_RADIUS}px;
                /* Shorthand, so it also overrides the app sheet's
                   padding-right — which is what reserves room for the two
                   arrow buttons. Restated here or the arrows sit on the
                   number. Keep it equal to the app sheet's. */
                padding: 4px 34px 4px 6px;
                font-size: 13px;
            }}
            QSpinBox:focus {{
                border-color: {Theme.NEON_YELLOW};
            }}
            QRadioButton {{
                color: {Theme.TEXT_PRIMARY};
                font-size: 13px;
                spacing: 6px;
            }}
            QRadioButton::indicator {{
                width: 14px;
                height: 14px;
            }}
            QRadioButton::indicator:checked {{
                background-color: {Theme.NEON_YELLOW};
                border: 2px solid {Theme.NEON_YELLOW};
                border-radius: 7px;
            }}
            QRadioButton::indicator:unchecked {{
                background-color: {Theme.BG_LIGHT};
                border: 2px solid {Theme.CHROME_DARK};
                border-radius: 7px;
            }}
            QCheckBox#circleCheck {{
                margin-left: 24px;
            }}
            QCheckBox#circleCheck::indicator {{
                width: 12px;
                height: 12px;
            }}
            QCheckBox#circleCheck::indicator:checked {{
                background-color: {Theme.NEON_YELLOW};
                border: 2px solid {Theme.NEON_YELLOW};
                border-radius: 6px;
            }}
            QCheckBox#circleCheck::indicator:unchecked {{
                background-color: {Theme.BG_LIGHT};
                border: 2px solid {Theme.CHROME_DARK};
                border-radius: 6px;
            }}
            QCheckBox#circleCheckLg::indicator {{
                width: 18px;
                height: 18px;
            }}
            QCheckBox#circleCheckLg::indicator:checked {{
                background-color: {Theme.NEON_YELLOW};
                border: 2px solid {Theme.NEON_YELLOW};
                border-radius: 9px;
            }}
            QCheckBox#circleCheckLg::indicator:unchecked {{
                background-color: {Theme.BG_LIGHT};
                border: 2px solid {Theme.CHROME_DARK};
                border-radius: 9px;
            }}
        """

    # ── Signal handlers ────────────────────────────────────────────────────

    def _on_min_changed(self, value: int) -> None:
        if value >= self._max_bpm_spin.value():
            self._max_bpm_spin.setValue(value + 1)
        self.settings_changed.emit()

    def _on_max_changed(self, value: int) -> None:
        if value <= self._min_bpm_spin.value():
            self._min_bpm_spin.setValue(value - 1)
        self.settings_changed.emit()

    def _selected_text_size(self) -> str:
        """The checked playlist text-size preset."""
        for size, radio in self._text_size_radios.items():
            if radio.isChecked():
                return size
        return "medium"

    def _selected_artwork_view(self) -> str:
        """The checked playlist artwork view."""
        for view, radio in self._artwork_view_radios.items():
            if radio.isChecked():
                return view
        return "top"

    def _emit_changed(self) -> None:
        self.settings_changed.emit()

    # ── Waveform color ─────────────────────────────────────────────────────

    def _select_waveform_color(self, color: str, *, emit: bool) -> None:
        """Set the active waveform color, restyle the swatches, persist if asked."""
        self._waveform_color = color
        self._restyle_waveform_swatches()
        if emit:
            self.settings_changed.emit()

    def _on_custom_waveform_color(self) -> None:
        chosen = QColorDialog.getColor(
            QColor(self._waveform_color), self, self.tr("Waveform color")
        )
        if chosen.isValid():
            self._select_waveform_color(chosen.name(), emit=True)

    def _restyle_waveform_swatches(self) -> None:
        """Highlight the preset matching the active color (none, if it's custom)."""
        active = self._waveform_color.lower()
        for hexcolor, btn in self._wave_swatches.items():
            selected = hexcolor.lower() == active
            if hexcolor == _DEFAULT_PRESET:
                # Outlined chip: the live theme's accent when it's the active
                # choice, muted grey otherwise — outline and label share a colour.
                color = Theme.NEON_YELLOW if selected else Theme.CHROME_DARK
                btn.setStyleSheet(
                    f"#waveSwatch {{ background-color: transparent; color: {color};"
                    f" border: 2px solid {color}; border-radius: 4px;"
                    f" padding: 2px 10px; font-weight: bold; }}"
                )
            else:
                border = Theme.TEXT_PRIMARY if selected else "transparent"
                btn.setStyleSheet(
                    f"#waveSwatch {{ background-color: {hexcolor};"
                    f" border: 2px solid {border}; border-radius: 4px; }}"
                )

    def _on_language_changed(self, _index: int) -> None:
        # Language only takes effect on restart, so remind the user once when
        # they change it. Persisting still happens via the settings_changed
        # signal below.
        QMessageBox.information(
            self,
            self.tr("Restart required"),
            self.tr(
                "The language change will take effect the next time you restart "
                "Mixed in P."
            ),
        )
        self.settings_changed.emit()

    def _on_theme_changed(self, _index: int) -> None:
        # The colour scheme is applied at startup, so a restart is needed for
        # the change to take effect. Persisting happens via settings_changed.
        QMessageBox.information(
            self,
            self.tr("Restart required"),
            self.tr(
                "The theme change will take effect the next time you restart "
                "Mixed in P."
            ),
        )
        self.settings_changed.emit()

    # ── Public API ─────────────────────────────────────────────────────────

    def set_auto_analyze(self, enabled: bool) -> None:
        """Reflect the auto-analyze setting in the checkbox.

        Used to mirror the Analyze panel's "Auto" toggle. Signals are blocked so
        this sync doesn't bounce back through ``settings_changed`` (the caller
        has already persisted the change).
        """
        self._auto_analyze_cb.blockSignals(True)
        self._auto_analyze_cb.setChecked(enabled)
        self._auto_analyze_cb.blockSignals(False)

    def get_config(self, base: AppConfig | None = None) -> AppConfig:
        """Read current widget state into an AppConfig.

        Fields the Settings UI doesn't manage (e.g. convert_* and
        spectrum_dynamic_range) are carried through from *base* so saving the
        result doesn't reset them to defaults.
        """
        naming = "tempo_key_prefix"
        for pref, radio in self._format_radios.items():
            if radio.isChecked():
                naming = pref
                break

        key_notation = "keycode"
        for value, radio in self._notation_radios.items():
            if radio.isChecked():
                key_notation = value
                break

        # Energy tag settings
        energy_format = "with_label" if self._radio_with_label.isChecked() else "number_only"
        energy_mode = "append" if self._radio_append.isChecked() else (
            "replace" if self._radio_replace.isChecked() else "prepend"
        )

        language = self._language_combo.currentData() or "en"
        theme = self._theme_combo.currentData() or "neon_dark"

        # Start from the live config so unmanaged fields survive, then override
        # only the fields this panel controls.
        return replace(
            base if base is not None else AppConfig(),
            language=language,
            theme=theme,
            min_bpm=float(self._min_bpm_spin.value()),
            max_bpm=float(self._max_bpm_spin.value()),
            auto_rename=self._auto_rename_cb.isChecked(),
            naming_preference=naming,
            key_notation=key_notation,
            auto_analyze=self._auto_analyze_cb.isChecked(),
            auto_write_bpm=self._auto_write_bpm_cb.isChecked(),
            auto_write_key=self._auto_write_key_cb.isChecked(),
            energy_tag_enabled=self._energy_enabled_cb.isChecked(),
            energy_field_enabled=self._energy_field_cb.isChecked(),
            player_text_size=self._selected_text_size(),
            player_artwork_view=self._selected_artwork_view(),
            energy_tag_format=energy_format,
            energy_tag_mode=energy_mode,
            key_in_comment_enabled=self._key_in_comment_cb.isChecked(),
            energy_written_first=self._energy_written_first_cb.isChecked(),
            waveform_color=self._waveform_color,
            export_absolute_paths=self._export_absolute_cb.isChecked(),
            persist_scratch=self._persist_scratch_cb.isChecked(),
            duplicate_policy=self._duplicate_policy_combo.currentData(),
            online_lookup_enabled=self._online_lookup_cb.isChecked(),
            discogs_token=self._discogs_token_edit.text().strip(),
            online_fetch_artwork=self._fetch_artwork_cb.isChecked(),
        )

    def load_config(self, cfg: AppConfig) -> None:
        """Populate widget state from an AppConfig (no signals emitted)."""
        # Block signals during load
        self._min_bpm_spin.blockSignals(True)
        self._max_bpm_spin.blockSignals(True)

        self._min_bpm_spin.setValue(int(cfg.min_bpm))
        self._max_bpm_spin.setValue(int(cfg.max_bpm))

        self._min_bpm_spin.blockSignals(False)
        self._max_bpm_spin.blockSignals(False)

        # Select the saved language without triggering the restart reminder.
        self._language_combo.blockSignals(True)
        lang_index = self._language_combo.findData(cfg.language)
        self._language_combo.setCurrentIndex(lang_index if lang_index >= 0 else 0)
        self._language_combo.blockSignals(False)

        # Select the saved theme without triggering the restart reminder.
        self._theme_combo.blockSignals(True)
        theme_index = self._theme_combo.findData(cfg.theme)
        self._theme_combo.setCurrentIndex(theme_index if theme_index >= 0 else 0)
        self._theme_combo.blockSignals(False)

        self._select_waveform_color(cfg.waveform_color, emit=False)

        self._auto_rename_cb.setChecked(cfg.auto_rename)
        self._auto_write_bpm_cb.setChecked(cfg.auto_write_bpm)
        self._auto_write_key_cb.setChecked(cfg.auto_write_key)
        notation_radio = self._notation_radios.get(cfg.key_notation)
        if notation_radio:
            notation_radio.setChecked(True)
        self._auto_analyze_cb.setChecked(cfg.auto_analyze)
        self._key_in_comment_cb.setChecked(cfg.key_in_comment_enabled)


        self._export_absolute_cb.blockSignals(True)
        self._export_absolute_cb.setChecked(cfg.export_absolute_paths)
        self._export_absolute_cb.blockSignals(False)
        self._persist_scratch_cb.blockSignals(True)
        self._persist_scratch_cb.setChecked(cfg.persist_scratch)
        self._persist_scratch_cb.blockSignals(False)

        self._online_lookup_cb.blockSignals(True)
        self._online_lookup_cb.setChecked(cfg.online_lookup_enabled)
        self._online_lookup_cb.blockSignals(False)
        self._fetch_artwork_cb.blockSignals(True)
        self._fetch_artwork_cb.setChecked(cfg.online_fetch_artwork)
        self._fetch_artwork_cb.blockSignals(False)
        self._discogs_token_edit.blockSignals(True)
        self._discogs_token_edit.setText(cfg.discogs_token)
        self._discogs_token_edit.blockSignals(False)
        # Kept beside the field rather than read back off it: the handler runs
        # *after* the text has already changed, so the widget can no longer say
        # what it held a moment ago. Set here too, and with signals blocked, so
        # loading a saved token is not mistaken for the user typing one.
        self._had_token = bool(cfg.discogs_token.strip())

        self._duplicate_policy_combo.blockSignals(True)
        dup_index = self._duplicate_policy_combo.findData(cfg.duplicate_policy)
        if dup_index >= 0:
            self._duplicate_policy_combo.setCurrentIndex(dup_index)
        self._duplicate_policy_combo.blockSignals(False)

        radio = self._format_radios.get(cfg.naming_preference)
        if radio:
            radio.setChecked(True)

        # Energy tag settings
        self._energy_enabled_cb.setChecked(cfg.energy_tag_enabled)
        self._energy_field_cb.setChecked(cfg.energy_field_enabled)
        radio = self._text_size_radios.get(cfg.player_text_size)
        if radio is not None:
            radio.setChecked(True)
        radio = self._artwork_view_radios.get(cfg.player_artwork_view)
        if radio is not None:
            radio.setChecked(True)
        self._energy_written_first_cb.setChecked(cfg.energy_written_first)
        if cfg.energy_tag_format == "with_label":
            self._radio_with_label.setChecked(True)
        else:
            self._radio_number_only.setChecked(True)
        if cfg.energy_tag_mode == "append":
            self._radio_append.setChecked(True)
        elif cfg.energy_tag_mode == "replace":
            self._radio_replace.setChecked(True)
        else:
            self._radio_prepend.setChecked(True)
