"""About dialog for the application."""

from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...styles.theme import Theme

import sys

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _ASSETS = Path(sys._MEIPASS) / "src" / "gui" / "assets"
else:
    _ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"


class AboutDialog(QDialog):
    """About popup with image/info toggle that closes on outside click."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFixedSize(440, 560)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # Page 0: Icon image (the gold "P") + website link, centered on dark bg.
        image_page = QWidget()
        image_page.setStyleSheet(f"background: {Theme.BG_DARK};")
        image_page.setCursor(Qt.CursorShape.PointingHandCursor)
        image_layout = QVBoxLayout(image_page)
        # Bottom margin nudges the link up by ~3/4 of its value (the top stretch
        # absorbs the rest): 8px here ≈ 6px higher.
        image_layout.setContentsMargins(0, 0, 0, 8)
        image_layout.setSpacing(0)
        # Larger top stretch keeps the icon centered; equal stretches above and
        # below the link (added later) sit it halfway between the icon's bottom
        # and the bottom edge of the slide.
        image_layout.addStretch(2)

        self._image_page = QLabel()
        self._image_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = _ASSETS / "icon.png"
        if icon.exists():
            pixmap = QPixmap(str(icon))
            self._image_page.setPixmap(
                pixmap.scaled(
                    380,
                    380,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self._image_page.setText(self.tr("Mixed in P"))
            self._image_page.setStyleSheet(
                f"color: {Theme.NEON_YELLOW}; font-size: 32px; font-weight: bold;"
            )
        image_layout.addWidget(self._image_page)

        # Docs link under the icon. setOpenExternalLinks routes the click to the
        # user's default browser. The label is pulled into its own tr() call
        # because lupdate does not extract tr() nested inside an f-string field.
        docs_label = self.tr("docs")
        link = QLabel(
            '<a href="https://jared-perez.github.io/mixed-in-p/docs/"'
            f' style="color: {Theme.NEON_YELLOW}; text-decoration: none;">'
            f"{docs_label}</a>"
        )
        link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        link.setOpenExternalLinks(True)
        link.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        link.setStyleSheet("font-size: 14px;")
        image_layout.addStretch(1)
        image_layout.addWidget(link)
        image_layout.addStretch(1)

        self._stack.addWidget(image_page)

        # Page 1: Info content
        info_page = QWidget()
        info_page.setCursor(Qt.CursorShape.PointingHandCursor)
        info_layout = QVBoxLayout(info_page)
        info_layout.setContentsMargins(30, 30, 30, 30)
        info_layout.setSpacing(20)

        info_layout.addStretch()

        presented = QLabel(self.tr("Jared P presents"))
        presented.setAlignment(Qt.AlignmentFlag.AlignCenter)
        presented.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 12px;")
        info_layout.addWidget(presented)

        title = QLabel(self.tr("Mixed in P"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title.setStyleSheet(f"""
            font-size: 32px;
            font-weight: bold;
            color: {Theme.NEON_YELLOW};
        """)
        info_layout.addWidget(title)

        subtitle = QLabel(self.tr("DJ Audio Analysis Toolkit"))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle.setStyleSheet(f"font-size: 16px; color: {Theme.TEXT_SECONDARY};")
        info_layout.addWidget(subtitle)

        # Keep the version number OUT of the translatable string so bumping it
        # never orphans the translations — translators handle only "Version {0}".
        version = QLabel(self.tr("Version {0}").format("1.3.0"))
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)

        version.setStyleSheet(f"color: {Theme.CHROME};")
        info_layout.addWidget(version)

        info_layout.addSpacing(10)

        desc = QLabel(
            self.tr(
                "Analyze audio files to detect BPM and musical key.\n"
                "Results displayed as harmonic key codes for easy harmonic mixing.\n\n"
                "Features:\n"
                "  - Batch file renaming with Undo\n"
                "  - Metadata editing\n"
                "  - Player with built-in slicer for sample lifting\n"
                "  - Harmonic keyboard\n"
                "  - BPM detection using beat tracking\n"
                "  - Key detection using Chroma analysis\n"
                "  - Spectrum analyzer"
            )
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)

        desc.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; line-height: 1.4;")
        desc.setWordWrap(True)
        info_layout.addWidget(desc)

        info_layout.addSpacing(10)

        formats = QLabel(
            self.tr("Supported formats: MP3, WAV, FLAC, AIFF, M4A, OGG")
        )
        formats.setAlignment(Qt.AlignmentFlag.AlignCenter)

        formats.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 13px;")
        info_layout.addWidget(formats)

        info_layout.addStretch()
        self._stack.addWidget(info_page)

        # Page 2: How To – Find Your Way Around
        howto1 = QWidget()
        howto1.setCursor(Qt.CursorShape.PointingHandCursor)
        h1_layout = QVBoxLayout(howto1)
        h1_layout.setContentsMargins(30, 30, 30, 30)
        h1_layout.setSpacing(0)

        h1_layout.addStretch()

        h1_title = QLabel(self.tr("Find Your Way Around"))
        h1_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h1_title.setStyleSheet(
            f"font-size: 22px; font-weight: bold; color: {Theme.NEON_YELLOW};"
            " margin-bottom: 18px;"
        )
        h1_layout.addWidget(h1_title)

        y = Theme.NEON_YELLOW
        p = Theme.TEXT_PRIMARY
        s = Theme.TEXT_SECONDARY
        h1_body = QLabel(
            self.tr(
                '<div style="color: {p}; font-size: 13px; line-height: 1.6;'
                ' text-align: center;">'
                'Drop your files onto any panel to get started.<br>'
                'The sidebar isn\'t just for navigation — you can<br>'
                'drag files right onto the buttons to route them.'
                '<br><br>'
                '<span style="color: {y}; font-weight: bold;">RENAME</span>'
                ' — Clean up filenames first<br>'
                '<span style="color: {s};">'
                'trim, prefix, preview before you commit</span>'
                '<br>'
                '<span style="color: {s};">↓</span><br>'
                '<span style="color: {y}; font-weight: bold;">ANALYZE</span>'
                ' — Detects BPM, key &amp; energy<br>'
                '<span style="color: {s};">'
                'auto-writes tags + renames in one shot</span>'
                '<br>'
                '<span style="color: {s};">↓</span><br>'
                '<span style="color: {y}; font-weight: bold;">CONVERT</span>'
                ' — Flip formats<br>'
                '<span style="color: {s};">'
                'WAV ↔ FLAC ↔ AIFF ↔ MP3</span>'
                '<br><br>'
                'Use <span style="color: {y};">Send To</span>'
                ' to move files between panels.'
                '</div>'
            ).format(p=p, y=y, s=s)
        )
        h1_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h1_body.setTextFormat(Qt.TextFormat.RichText)
        h1_body.setWordWrap(True)
        h1_layout.addWidget(h1_body)

        h1_layout.addStretch()

        self._stack.addWidget(howto1)

        # Page 3: How To – The Rest of the Kit
        howto2 = QWidget()
        howto2.setCursor(Qt.CursorShape.PointingHandCursor)
        h2_layout = QVBoxLayout(howto2)
        h2_layout.setContentsMargins(30, 30, 30, 30)
        h2_layout.setSpacing(0)

        h2_layout.addStretch()

        h2_title = QLabel(self.tr("The Rest of the Kit"))
        h2_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h2_title.setStyleSheet(
            f"font-size: 22px; font-weight: bold; color: {Theme.NEON_YELLOW};"
            " margin-bottom: 18px;"
        )
        h2_layout.addWidget(h2_title)

        h2_body = QLabel(
            self.tr(
                '<div style="color: {p}; font-size: 13px; line-height: 1.7;'
                ' text-align: center;">'
                '<span style="color: {y}; font-weight: bold;">SLICE</span>'
                ' — Grab a section from any track.<br>'
                '<span style="color: {s};">'
                'Open from inside Player window.<br>'
                'Set start/end with the range slider or mark<br>'
                'boundaries from playback. Nudge ±10ms.</span>'
                '<br><br>'
                '<span style="color: {y}; font-weight: bold;">METADATA</span>'
                ' — Drop a file in, edit its tags.<br>'
                '<span style="color: {s};">'
                'Auto-saves when you move on.</span>'
                '<br><br>'
                '<span style="color: {y}; font-weight: bold;">KEYBOARD</span>'
                ' — Play notes in any key.<br>'
                '<span style="color: {s};">'
                'Harmonic key strip right there for reference.</span>'
                '<br><br>'
                '<span style="color: {y}; font-weight: bold;">SPECTRUM</span>'
                ' — Acoustic spectrum analyzer.<br>'
                '<span style="color: {s};">'
                'Visual representation of audio quality.</span>'
                '<br><br>'
                '<span style="color: {y}; font-weight: bold;">SETTINGS</span>'
                ' — BPM range, key format,<br>'
                '<span style="color: {s};">'
                'auto-rename rules.</span>'
                '</div>'
            ).format(p=p, y=y, s=s)
        )
        h2_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h2_body.setTextFormat(Qt.TextFormat.RichText)
        h2_body.setWordWrap(True)
        h2_layout.addWidget(h2_body)

        h2_layout.addStretch()
        self._stack.addWidget(howto2)

        # "click for more" hint — a free-floating overlay pinned just above the
        # bottom edge, NOT part of any slide's layout. This keeps it at the exact
        # same spot on every slide and immune to tall (translated) body text: the
        # body is centred within its 30px margins, so it never reaches down into
        # this strip. Mouse-transparent so clicks pass through to cycle pages.
        # Hidden on the icon slide (index 0).
        self._hint = QLabel(self.tr("click for more"), self)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setStyleSheet(
            f"color: {Theme.CHROME_DARK}; font-size: 10px; background: transparent;"
        )
        self._hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._hint.setGeometry(0, self.height() - 20, self.width(), 14)
        self._hint.raise_()

        # Start on info page
        self._stack.setCurrentIndex(1)
        self._update_hint_visibility()

    def _update_hint_visibility(self) -> None:
        """Show the hint on the info / how-to slides, not the icon slide."""
        self._hint.setVisible(self._stack.currentIndex() != 0)

    def changeEvent(self, event) -> None:
        """Close the dialog when it loses focus (user clicks elsewhere in app)."""
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            self.close()
        super().changeEvent(event)

    def mousePressEvent(self, event) -> None:
        """Cycle through all pages on click."""
        current = self._stack.currentIndex()
        total = self._stack.count()
        self._stack.setCurrentIndex((current + 1) % total)
        self._update_hint_visibility()
