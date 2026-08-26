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
from .elided_label import LinkLabel
from .pipeline_cluster import PipelineCluster

# The header's now-playing line elides rather than pushing the Add button off
# the bar, and floors out at roughly "Playing: <a few characters>…" — below
# that it says nothing the user couldn't get from the tab strip.
_NOW_PLAYING_MIN_WIDTH = 90
_NOW_PLAYING_GAP = 16

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _ASSETS = Path(sys._MEIPASS) / "src" / "gui" / "assets"
else:
    _ASSETS = Path(__file__).resolve().parent.parent / "assets"


class HeaderBar(QFrame):
    """Top header bar with logo, title, and action buttons."""

    add_files_clicked = Signal()
    add_folder_clicked = Signal()
    about_clicked = Signal()
    # The now-playing line was clicked: take the user to what's playing.
    now_playing_clicked = Signal()

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

        # What's playing, for every panel that isn't the Player. Playback
        # outlives the Player being on screen, so from anywhere else in the app
        # there was no way to tell what was running short of switching back —
        # and switching back is exactly what this saves. Hidden on the Player
        # itself, which says it better one line above the slicer.
        #
        # Same bottom alignment and margin as the subtitle so the two sit on one
        # baseline rather than reading as two rows that failed to line up.
        # A wider gap than the layout's 4px: this is a separate fact from the
        # tagline, not more of it, and at 4px the two read as one sentence.
        layout.addSpacing(_NOW_PLAYING_GAP)

        self._now_playing = LinkLabel(min_width=_NOW_PLAYING_MIN_WIDTH)
        self._now_playing.setObjectName("headerNowPlaying")
        self._now_playing.setStyleSheet(
            f"color: {Theme.ACCENT_TEXT}; font-size: 12px; margin-bottom: 8px;"
        )
        self._now_playing.setToolTip(
            self.tr("Go to the playlist the current track is playing from")
        )
        self._now_playing.clicked.connect(self.now_playing_clicked.emit)
        self._now_playing.hide()
        layout.addWidget(self._now_playing, alignment=Qt.AlignmentFlag.AlignBottom)

        # Spacer
        layout.addStretch()

        # The pipeline's shape, left of Add: three mini step toggles and the
        # playlist every run ends in. Here rather than in a panel because a run
        # can start from any of three panels and belongs to none of them.
        self._pipeline = PipelineCluster()
        self._pipeline.shape_changed.connect(self._apply_subtitle_rule)
        layout.addWidget(self._pipeline, alignment=Qt.AlignmentFlag.AlignVCenter)

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

    @property
    def pipeline(self) -> PipelineCluster:
        """The step toggles and target playlist. MainWindow owns their state."""
        return self._pipeline

    def set_subtitle_visible(self, visible: bool) -> None:
        """Show or hide the 'DJ Audio Analysis Toolkit' subtitle."""
        self._subtitle.setVisible(visible)

    def set_now_playing(self, track_name: str) -> None:
        """Name the playing track in the header, or hide the line when empty.

        Takes the bare filename and words it here rather than being handed a
        finished sentence: the copy belongs with the widget that shows it, and
        this keeps the phrasing one string instead of the same English written
        out in two contexts for translators to keep in step.
        """
        if track_name:
            self._now_playing.setText(self.tr("Playing: {0}").format(track_name))
            self._now_playing.show()
        else:
            self._now_playing.hide()
        # It joins the row the subtitle is competing for, so the threshold
        # below has just moved.
        self._apply_subtitle_rule()

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
        total = margins.left() + margins.right()
        total += sum(w.sizeHint().width() for w in widgets)
        gaps = len(widgets) - 1
        # As wide as the cluster is right now: the target field appears with
        # the first step switched on, and reserving its width while it is
        # hidden would take the subtitle away from everyone who never turns
        # the pipeline on. shape_changed re-runs this when it moves.
        total += self._pipeline.width_hint()
        gaps += 1
        # The now-playing spacer is a QSpacerItem, so it holds its width whether
        # or not the label beside it is showing.
        total += _NOW_PLAYING_GAP
        gaps += 1
        if not self._now_playing.isHidden():
            # Its *floor*, not its hint: it elides, so a long filename must not
            # be what takes the subtitle away — only a header with no room for
            # even a stub of it should.
            total += self._now_playing.minimumSizeHint().width()
            gaps += 1
        return total + spacing * gaps

    def _apply_subtitle_rule(self) -> None:
        """Drop the subtitle before 'Add' would overlap it; restore it once
        there's room again (with a small dead-band to avoid jitter)."""
        needed = self._subtitle_fits()
        if self._subtitle.isVisible():
            if self.width() < needed:
                self.set_subtitle_visible(False)
        elif self.width() >= needed + 8:
            self.set_subtitle_visible(True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_subtitle_rule()
