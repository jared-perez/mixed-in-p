"""Header bar widget with logo and action buttons."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QWidget,
)

from ..styles.theme import Theme

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _ASSETS = Path(sys._MEIPASS) / "src" / "gui" / "assets"
else:
    _ASSETS = Path(__file__).resolve().parent.parent / "assets"


class HeaderBar(QFrame):
    """Top header bar with logo, title, and action buttons."""

    add_files_clicked = Signal()
    add_folder_clicked = Signal()
    about_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("headerBar")
        self.setFixedHeight(Theme.HEADER_HEIGHT)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(1, 0, 16, 0)
        layout.setSpacing(4)

        # Logo image
        logo_pixmap = QPixmap(str(_ASSETS / "logo_title.png"))
        scaled = logo_pixmap.scaled(
            logo_pixmap.width(), 44,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._logo_label = QLabel()
        self._logo_label.setPixmap(scaled)
        self._logo_label.setObjectName("logoLabel")
        layout.addWidget(self._logo_label)

        # Subtitle. resizeEvent hides it if the header ever gets too narrow for
        # the logo + buttons (so 'Add Files' can't overlap it); otherwise it
        # renders at its natural width.
        self._subtitle = QLabel(self.tr("DJ Audio Analysis Toolkit"))
        self._subtitle.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 12px; margin-bottom: 8px;")
        layout.addWidget(self._subtitle, alignment=Qt.AlignmentFlag.AlignBottom)

        # Spacer
        layout.addStretch()

        # Single "Add" menu button: click reveals Files / Folder actions, which
        # emit the same signals the two old buttons did (wiring is unchanged in
        # main_window). Collapsing two buttons into one also keeps the subtitle
        # visible at narrower widths (see resizeEvent).
        self._add_btn = QToolButton()
        self._add_btn.setText(self.tr("Add"))
        # Font size lives in the stylesheet (#headerActionButton), not an inline
        # setStyleSheet, so it doesn't leak into the button's tooltip/menu font.
        self._add_btn.setObjectName("headerActionButton")
        self._add_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._add_btn.setToolTip(
            self.tr("Add files or a folder to the panel you're currently viewing")
        )

        add_menu = QMenu(self._add_btn)
        add_menu.addAction(self.tr("Files…"), self.add_files_clicked.emit)
        add_menu.addAction(self.tr("Folder…"), self.add_folder_clicked.emit)
        self._add_btn.setMenu(add_menu)
        layout.addWidget(self._add_btn)

        self._about_btn = QPushButton("?")
        self._about_btn.setFixedSize(36, 36)
        self._about_btn.setStyleSheet(
            "border-radius: 18px; font-size: 18px; font-weight: bold; padding: 0px;"
        )
        self._about_btn.clicked.connect(self.about_clicked.emit)
        layout.addWidget(self._about_btn)

    def set_subtitle_visible(self, visible: bool) -> None:
        """Show or hide the 'DJ Audio Analysis Toolkit' subtitle."""
        self._subtitle.setVisible(visible)

    def _subtitle_fits(self) -> int:
        """Width the header needs for the logo, subtitle, and buttons to coexist.

        Computed from the widgets' own size hints (ignoring current subtitle
        visibility) so the threshold stays stable as we toggle it — no flicker.
        """
        layout = self.layout()
        margins = layout.contentsMargins()
        spacing = layout.spacing()
        widgets = [
            self._logo_label,
            self._subtitle,
            self._add_btn,
            self._about_btn,
        ]
        total = margins.left() + margins.right() + spacing * (len(widgets) - 1)
        total += sum(w.sizeHint().width() for w in widgets)
        return total

    def resizeEvent(self, event) -> None:
        """Drop the subtitle before 'Add Files' would overlap it; restore it
        once there's room again (with a small dead-band to avoid jitter)."""
        super().resizeEvent(event)
        needed = self._subtitle_fits()
        if self._subtitle.isVisible():
            if self.width() < needed:
                self.set_subtitle_visible(False)
        else:
            if self.width() >= needed + 8:
                self.set_subtitle_visible(True)
