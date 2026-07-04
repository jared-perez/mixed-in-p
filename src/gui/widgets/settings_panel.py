"""Settings panel widget."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dataclasses import replace

from ...utils.config import AppConfig
from ...utils.i18n import LANGUAGES
from ..styles.theme import THEMES, Theme

# Preset waveform colors offered in Settings. The first entry is the "default"
# sentinel: selecting it makes the waveform follow the active theme's own
# default colour (see main_window._effective_waveform_color). It's shown as an
# outlined "Default" chip rather than a colour box.
_WAVEFORM_PRESETS = ("#f0ff00", "#006992", "#001d4a", "#c5ff15", "#00d61c")
_DEFAULT_PRESET = _WAVEFORM_PRESETS[0]


class SettingsPanel(QWidget):
    """Settings panel with tempo range and auto-rename options."""

    settings_changed = Signal()

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

        self._language_combo = QComboBox()
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

        # ── Section: Theme ─────────────────────────────────────────────────
        outer.addWidget(self._make_section_label(self.tr("Theme")))

        theme_frame = QFrame()
        theme_frame.setObjectName("settingsSection")
        theme_layout = QVBoxLayout(theme_frame)
        theme_layout.setContentsMargins(16, 10, 16, 10)
        theme_layout.setSpacing(8)

        # Translatable display names keyed by palette id. Falls back to the
        # palette's own label if a new theme is added without a label here.
        theme_labels = {
            "neon_dark": self.tr("Neon Dark"),
            "night_dark": self.tr("Night Dark"),
            "nuevo_leon": self.tr("Nuevo Leon"),
            "daylight": self.tr("Daylight"),
        }
        self._theme_combo = QComboBox()
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
        outer.addWidget(self._make_section_label(self.tr("Waveform")))

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

        # ── Section: Visualizations ────────────────────────────────────────
        outer.addWidget(self._make_section_label(self.tr("Visualizations")))

        vis_frame = QFrame()
        vis_frame.setObjectName("settingsSection")
        vis_layout = QVBoxLayout(vis_frame)
        vis_layout.setContentsMargins(16, 10, 16, 10)
        vis_layout.setSpacing(8)

        self._visualizations_cb = QCheckBox(self.tr("Enable audio visualizations"))
        self._visualizations_cb.setObjectName("circleCheckLg")
        self._visualizations_cb.setChecked(False)
        vis_layout.addWidget(self._visualizations_cb)

        vis_hint = QLabel(
            self.tr(
                "Adds a visuals selector to the Player and an animated waveform "
                "while analyzing or converting."
            )
        )
        vis_hint.setObjectName("settingsHint")
        vis_hint.setWordWrap(True)
        vis_layout.addWidget(vis_hint)

        outer.addWidget(vis_frame)

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
        self._min_bpm_spin.setFixedWidth(80)
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
        self._max_bpm_spin.setFixedWidth(80)
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

        outer.addWidget(energy_frame)
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
        self._visualizations_cb.stateChanged.connect(self._emit_changed)
        self._format_group.buttonClicked.connect(self._emit_changed)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)

        # Style the spinboxes and frame
        self.setStyleSheet(self._build_stylesheet())

    # ── Helpers ────────────────────────────────────────────────────────────

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
                padding: 4px 6px;
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
            energy_tag_format=energy_format,
            energy_tag_mode=energy_mode,
            key_in_comment_enabled=self._key_in_comment_cb.isChecked(),
            energy_written_first=self._energy_written_first_cb.isChecked(),
            waveform_color=self._waveform_color,
            visualizations_enabled=self._visualizations_cb.isChecked(),
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

        self._visualizations_cb.blockSignals(True)
        self._visualizations_cb.setChecked(cfg.visualizations_enabled)
        self._visualizations_cb.blockSignals(False)

        radio = self._format_radios.get(cfg.naming_preference)
        if radio:
            radio.setChecked(True)

        # Energy tag settings
        self._energy_enabled_cb.setChecked(cfg.energy_tag_enabled)
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
