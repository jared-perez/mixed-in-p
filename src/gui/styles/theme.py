"""Color palettes and theme definitions.

Colours live in :class:`Palette` objects (one per theme). The rest of the app
reads colours as class attributes on :class:`Theme` (e.g. ``Theme.NEON_YELLOW``);
:meth:`Theme.apply` repopulates those attributes from whichever palette is
active, so every call site stays palette-agnostic without change.

Token names are historical (they describe the *Neon Dark* look), but in every
palette they carry a **role**, not a literal colour:

* ``NEON_YELLOW``  → primary accent (focus borders, active nav, emphasis)
* ``NEON_GREEN``   → secondary accent (success, progress, "analysed")
* ``CHROME`` / ``CHROME_DARK`` → metallic lines / borders
* ``PLAYHEAD``     → playback position line over the waveform

See ``spitball/theming-plan-revised.md`` for the full role table and palette
design rationale.
"""

import sys
from dataclasses import dataclass, fields
from pathlib import Path

from PySide6.QtCore import QModelIndex, QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    ASSETS_DIR = Path(sys._MEIPASS) / "src" / "gui" / "assets"
else:
    ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def load_panel_bg(name: str) -> QPixmap:
    """Load a background icon pixmap from the assets directory."""
    return QPixmap(str(ASSETS_DIR / name))


# Panel-header description labels registered by ``panel_header_row``. The window
# sizer toggles their word-wrap together: wrap on while the window is wide, off
# (so the single line clips instead of cluttering) once it narrows past a
# threshold. Stored as a plain list of live QLabels; dead ones are skipped.
_wrap_labels: list[QLabel] = []


def panel_header_row(title: QLabel, desc: QLabel) -> QHBoxLayout:
    """Lay a panel's section title and its description out on one line.

    The title is pinned at the left; the description flows to its right and
    wraps within its own column (left-aligned). Both are bottom-aligned so the
    last description line sits level with the bottom of the title — whether the
    description is one line or wraps to several. Replacing the old stacked
    title-over-description layout frees the vertical space the description used
    to occupy, letting the panel's controls move up.

    The caller builds and styles both labels (so each keeps its own ``tr()``
    translation context); this only arranges them.
    """
    desc.setWordWrap(True)
    # An unwrapped (clipped) description must not be able to push the panel
    # wider than the per-panel minimum, so let its width be ignored by layout.
    desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    _wrap_labels.append(desc)
    row = QHBoxLayout()
    row.setSpacing(Theme.PADDING)
    row.addWidget(title, 0, Qt.AlignmentFlag.AlignBottom)
    row.addWidget(desc, 1, Qt.AlignmentFlag.AlignBottom)
    return row


def set_description_wrap(enabled: bool) -> None:
    """Toggle word-wrap on every registered panel-header description label.

    When disabled, each description renders on a single line and clips at the
    edge of its column rather than wrapping — this keeps long descriptions from
    cluttering or overstepping the UI once the window is narrow.
    """
    for label in list(_wrap_labels):
        try:
            label.setWordWrap(enabled)
        except RuntimeError:
            # Underlying C++ label was deleted; drop it from the registry.
            _wrap_labels.remove(label)


class BackgroundOverlay(QWidget):
    """Transparent overlay that draws a faint icon on top of all child widgets.

    Usage inside a panel's ``__init__``::

        self._bg_overlay = BackgroundOverlay("bg_rename.png", self)
    """

    def __init__(self, image_name: str, parent: QWidget, opacity: float = 0.07) -> None:
        super().__init__(parent)
        self._pixmap = load_panel_bg(image_name)
        self._opacity = opacity
        # Let mouse events pass through to widgets underneath
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        self.raise_()

    # Re-raise on show so the overlay stays on top after layout changes
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.raise_()

    def paintEvent(self, event) -> None:
        if self._pixmap.isNull():
            return
        p = QPainter(self)
        p.setOpacity(self._opacity)
        target_size = int(min(self.width(), self.height()) * 0.6)
        scaled = self._pixmap.scaled(
            target_size,
            target_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) / 2
        y = (self.height() - scaled.height()) / 2
        p.drawPixmap(
            QRectF(x, y, scaled.width(), scaled.height()),
            scaled,
            QRectF(scaled.rect()),
        )
        p.end()


class NoFocusDelegate(QStyledItemDelegate):
    """Item delegate that suppresses the native focus rectangle."""

    def initStyleOption(self, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        super().initStyleOption(option, index)
        option.state &= ~QStyle.StateFlag.State_HasFocus


@dataclass(frozen=True)
class Palette:
    """One theme's colour values. Field names are the role tokens read app-wide."""

    name: str  # stable id stored in config (e.g. "neon_dark")
    label: str  # human-facing name (wrapped for translation at the display site)

    # Backgrounds: window → panels/inputs → hover → active/selected
    BG_DARK: str
    BG_MEDIUM: str
    BG_LIGHT: str
    BG_LIGHTER: str

    # Accents and metallic lines
    NEON_YELLOW: str  # primary accent
    NEON_GREEN: str  # secondary accent / success
    PLAYHEAD: str  # playback position line over the waveform
    CHROME: str  # secondary metallic / stronger lines
    CHROME_DARK: str  # borders

    # Text
    TEXT_PRIMARY: str
    TEXT_SECONDARY: str
    TEXT_DISABLED: str

    # Status
    ERROR: str
    WARNING: str
    INFO: str
    PENDING: str  # "pending analysis" state (distinct from TEXT_DISABLED)

    # Variant shades — hover/pressed states of the accents, and table-row
    # backgrounds. Kept as explicit tokens (rather than computed offsets) so
    # each palette controls them exactly.
    ACCENT_HOVER: str  # primary-accent fill on hover
    ACCENT_PRESSED: str  # primary-accent fill while pressed
    ACCENT2_HOVER: str  # secondary-accent fill on hover
    ERROR_HOVER: str  # danger fill on hover
    ROW_ALT: str  # alternate (zebra) table row
    ROW_HOVER: str  # table row under the cursor

    # Slicer / waveform surfaces.
    TRAY_BG: str  # recessed "work area" tray behind the slicer detail + controls
    WAVE_AXIS: str  # faint centre reference line drawn through a waveform
    WAVEFORM_DEFAULT: str  # default full-length waveform colour for this theme
    #                        (used only when the user hasn't picked a custom one)

    # The primary accent when used as *foreground label/heading text*. Equals
    # the accent on dark themes; on light themes it drops to near-black, since
    # the bright accent reads poorly as text on a pale surface.
    ACCENT_TEXT: str


# ── Theme A: Neon Dark ──────────────────────────────────────────────────────
# The current look, ported verbatim. The default; produces no visible change.
NEON_DARK = Palette(
    name="neon_dark",
    label="Neon Dark",
    BG_DARK="#1a1a1a",
    BG_MEDIUM="#2d2d2d",
    BG_LIGHT="#3d3d3d",
    BG_LIGHTER="#4d4d4d",
    NEON_YELLOW="#f0ff00",
    NEON_GREEN="#00ff88",
    PLAYHEAD="#ffffff",  # white for max contrast over the waveform
    CHROME="#c0c0c0",
    CHROME_DARK="#808080",
    TEXT_PRIMARY="#ffffff",
    TEXT_SECONDARY="#b0b0b0",
    TEXT_DISABLED="#606060",
    ERROR="#ff4444",
    WARNING="#ffaa00",
    INFO="#4488ff",
    PENDING="#888888",
    ACCENT_HOVER="#d4e300",
    ACCENT_PRESSED="#b8c700",
    ACCENT2_HOVER="#00dd77",
    ERROR_HOVER="#dd3333",
    ROW_ALT="#333333",
    ROW_HOVER="#383838",
    TRAY_BG="#0d0d0d",
    WAVE_AXIS="#222222",
    WAVEFORM_DEFAULT="#f0ff00",
    ACCENT_TEXT="#f0ff00",
)

# ── Theme B: Night Dark ─────────────────────────────────────────────────────
# Low-strain dark theme for extended late-night use: no pure black/white,
# desaturated low-blue accents. NOT user-selectable until the picker lands.
NIGHT_DARK = Palette(
    name="night_dark",
    label="Night Dark",
    BG_DARK="#16181d",
    BG_MEDIUM="#1e2127",
    BG_LIGHT="#2a2e36",
    BG_LIGHTER="#363b45",
    NEON_YELLOW="#e0b95c",  # muted amber-gold (primary accent)
    NEON_GREEN="#6cc4a1",  # calm teal-green (secondary accent)
    PLAYHEAD="#eef1f5",  # soft near-white
    CHROME="#aab1bd",
    CHROME_DARK="#5b616b",
    TEXT_PRIMARY="#d7dae0",  # off-white ~12-13:1, no halation
    TEXT_SECONDARY="#969cab",
    TEXT_DISABLED="#5b606b",
    ERROR="#e06b6e",
    WARNING="#d9a441",
    INFO="#6f9bd1",
    PENDING="#7c828d",
    ACCENT_HOVER="#cda94f",
    ACCENT_PRESSED="#b5933f",
    ACCENT2_HOVER="#5bb08f",
    ERROR_HOVER="#c95d60",
    ROW_ALT="#1a1d22",
    ROW_HOVER="#262a32",
    TRAY_BG="#101216",
    WAVE_AXIS="#2a2e36",
    WAVEFORM_DEFAULT="#e0b95c",  # muted amber — low-strain at night
    ACCENT_TEXT="#e0b95c",
)

# ── Theme C: Daylight ───────────────────────────────────────────────────────
# Readable light theme: off-white surfaces (not pure white) to cut glare,
# near-black text (~15:1), accents darkened for AA contrast on light. The light
# palette still needs per-panel design verification (custom-painted widgets) —
# see step 5 of the plan. NOT user-selectable until the picker lands.
DAYLIGHT = Palette(
    name="daylight",
    label="Daylight",
    BG_DARK="#e7e9ed",  # window canvas (roles read inverted in a light theme)
    BG_MEDIUM="#ffffff",  # panels/inputs sit above the canvas
    BG_LIGHT="#eef0f4",
    BG_LIGHTER="#dfe3ea",
    NEON_YELLOW="#b8860b",  # deep gold, AA as text/border on white
    NEON_GREEN="#1f9d57",  # AA green on white
    PLAYHEAD="#c0392b",  # red — a light playhead vanishes on a light waveform
    CHROME="#8b919b",  # stronger line
    CHROME_DARK="#c4c8cf",  # lighter hairline border (role inverts vs dark)
    TEXT_PRIMARY="#1c2026",  # soft near-black ~15:1
    TEXT_SECONDARY="#565c66",
    TEXT_DISABLED="#a6abb3",
    ERROR="#c5303a",
    WARNING="#b9770e",
    INFO="#2b6fb5",
    PENDING="#8b919b",
    ACCENT_HOVER="#a5790a",
    ACCENT_PRESSED="#8f6808",
    ACCENT2_HOVER="#1b8a4c",
    ERROR_HOVER="#ad2a33",
    ROW_ALT="#f2f4f7",
    ROW_HOVER="#eef0f4",
    TRAY_BG="#d9dee5",  # light recessed tray, distinct from the white panels
    WAVE_AXIS="#c4c8cf",  # faint grey centre line on light surfaces
    WAVEFORM_DEFAULT="#006992",  # teal — reads well on the light waveform background
    ACCENT_TEXT="#1c2026",  # near-black: the gold accent reads poorly as text on white
)

# ── Theme D: Nuevo Leon ─────────────────────────────────────────────────────
# Midnight-navy dark theme (ported from the landing page palette): cool
# blue-black surfaces so the neon-yellow accent reads as a sharp accent rather
# than a darker cousin of a warm background. Waveform defaults to neon yellow.
NUEVO_LEON = Palette(
    name="nuevo_leon",
    label="Nuevo Leon",
    BG_DARK="#070a12",  # window canvas — blue-black (landing --bg)
    BG_MEDIUM="#121a2c",  # panels/inputs (landing --panel)
    BG_LIGHT="#1b2840",  # hover
    BG_LIGHTER="#25334d",  # active/selected (≈ landing --line)
    NEON_YELLOW="#ebff00",  # exact app waveform yellow (landing --yellow)
    NEON_GREEN="#1fe98a",  # bright mint — secondary accent / success on navy
    PLAYHEAD="#ffffff",  # white for max contrast over the waveform
    CHROME="#9aa6bd",  # cool steel line
    CHROME_DARK="#2c3a56",  # slate border
    TEXT_PRIMARY="#e7ebf2",  # cool white (landing --text)
    TEXT_SECONDARY="#8893a8",  # slate gray (landing --muted)
    TEXT_DISABLED="#555f73",
    ERROR="#ff5c5c",
    WARNING="#ffb13d",
    INFO="#4aa3ff",
    PENDING="#6b7689",
    ACCENT_HOVER="#d4e600",
    ACCENT_PRESSED="#b9c900",
    ACCENT2_HOVER="#17cf78",
    ERROR_HOVER="#e04a4a",
    ROW_ALT="#0d1422",
    ROW_HOVER="#16203a",
    TRAY_BG="#04060d",  # recessed tray, darker than the window canvas
    WAVE_AXIS="#1c2740",  # faint navy centre line
    WAVEFORM_DEFAULT="#ebff00",  # neon yellow, per design
    ACCENT_TEXT="#ebff00",  # accent reads fine as text on dark navy
)

# Registry keyed by the id persisted in config. Order = picker order.
THEMES: dict[str, Palette] = {
    p.name: p for p in (NEON_DARK, NIGHT_DARK, NUEVO_LEON, DAYLIGHT)
}
DEFAULT_THEME = NEON_DARK.name

# Palette field names that are colour tokens (everything but the two id fields).
_COLOR_TOKENS = tuple(
    f.name for f in fields(Palette) if f.name not in ("name", "label")
)


class Theme:
    """Live theme surface: colour tokens are repopulated by :meth:`apply`.

    Colour attributes are *not* defined here — they are written by
    :meth:`apply`, which is invoked at import time (below) with the default
    palette so ``Theme.X`` is always populated even before the app picks a
    theme. ``app.py`` calls :meth:`apply` again at startup with the configured
    palette, before any widget is built or the stylesheet is rendered.
    """

    # UI element sizes — palette-independent, so they stay plain constants.
    HEADER_HEIGHT = 60
    SIDEBAR_WIDTH = 176
    SIDEBAR_WIDTH_COLLAPSED = 56
    BORDER_RADIUS = 4
    SPACING = 8
    PADDING = 12

    # The currently-applied palette (set by apply()).
    active: Palette = NEON_DARK

    @classmethod
    def apply(cls, palette: Palette) -> None:
        """Repopulate the colour-token class attributes from *palette*."""
        cls.active = palette
        for token in _COLOR_TOKENS:
            setattr(cls, token, getattr(palette, token))
        # Derived / aliased tokens.
        cls.SUCCESS = palette.NEON_GREEN
        cls.QUEUED = palette.CHROME
        cls.ANALYSING = palette.NEON_YELLOW
        cls.ANALYSED = palette.NEON_GREEN
        cls.ERROR_STATE = palette.ERROR

    @classmethod
    def tokens(cls) -> dict[str, str]:
        """Return the active colour tokens as a {name: hex} mapping.

        Used to render the QSS template against the active palette.
        """
        return {token: getattr(cls, token) for token in _COLOR_TOKENS}

    @classmethod
    def get_state_color(cls, state: str) -> str:
        """Get the color for a track state."""
        state_colors = {
            "queued": cls.QUEUED,
            "pending": cls.PENDING,
            "analysing": cls.ANALYSING,
            "analysed": cls.ANALYSED,
            "error": cls.ERROR_STATE,
        }
        return state_colors.get(state.lower(), cls.TEXT_PRIMARY)


# Populate Theme with the default palette at import time so ``Theme.X`` is
# always available; app.py re-applies the configured palette at startup.
Theme.apply(NEON_DARK)
