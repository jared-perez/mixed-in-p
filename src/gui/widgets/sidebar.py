"""Sidebar navigation widget."""

from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.utils.config import load_config
from ..styles.theme import Theme
from .drop_zone import AUDIO_EXTENSIONS
from .droppable_table import SOURCE_PAGE_MIME
from .nav_icons import nav_icon

# Display size for the sidebar nav glyphs.
_NAV_ICON_SIZE = QSize(30, 30)

# Which panel-to-panel drags are allowed, and whether the drop removes the rows
# from the source (True = move; False = copy, leaves them).
# True is used when source and destination hold independent lists (mirrors "Send
# To"). False is used when removing would be wrong: Metadata (non-destructive,
# first-file-only), Player -> Metadata (don't stop a playing track), and the
# Rename<->Analyze pair which share one TrackStore — there a "move" is a track
# state change done by the destination intake, not an add+remove (removing would
# delete the only copy).
#   source_page: { destination_page: remove_from_source }
DRAG_ROUTES: dict[str, dict[str, bool]] = {
    "rename":   {"convert": True, "analysis": False, "player": True, "metadata": False, "spectrum": False},
    "convert":  {"analysis": True, "rename": True, "player": True, "metadata": False, "spectrum": False},
    "analysis": {"convert": True, "rename": False, "player": True, "metadata": False, "spectrum": False},
    "player":   {"rename": True, "convert": True, "analysis": True, "metadata": False, "spectrum": False},
}


class _DroppableSidebarButton(QPushButton):
    """Sidebar button that accepts audio file drops and panel-to-panel drags."""

    files_dropped = Signal(list)

    def __init__(self, text: str, page_id: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._page_id = page_id
        self.setAcceptDrops(True)

    @staticmethod
    def _source_page(event) -> str:
        """Page id of an internal panel drag, or '' for an external OS drop."""
        mime = event.mimeData()
        if mime.hasFormat(SOURCE_PAGE_MIME):
            return bytes(mime.data(SOURCE_PAGE_MIME)).decode("utf-8", "ignore")
        return ""

    def _drag_policy(self, event) -> tuple[bool, "Qt.DropAction | None"]:
        """Decide whether to accept this drag and with which action.

        Internal panel drags are gated by DRAG_ROUTES (and use Move/Copy per the
        remove-source policy); external OS drags are accepted as a plain Copy add.
        """
        mime = event.mimeData()
        if not mime.hasUrls():
            return False, None
        src = self._source_page(event)
        if src:
            routes = DRAG_ROUTES.get(src, {})
            if self._page_id not in routes:
                return False, None
            return True, (Qt.DropAction.MoveAction if routes[self._page_id] else Qt.DropAction.CopyAction)
        for url in mime.urls():
            path = Path(url.toLocalFile())
            if path.is_dir() or path.suffix.lower() in AUDIO_EXTENSIONS:
                return True, Qt.DropAction.CopyAction
        return False, None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        accept, action = self._drag_policy(event)
        if accept:
            event.setDropAction(action)
            event.accept()
            self.setStyleSheet(f"border: 2px solid {Theme.NEON_YELLOW};")
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        accept, action = self._drag_policy(event)
        if accept:
            event.setDropAction(action)
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self.setStyleSheet("")

    def dropEvent(self, event: QDropEvent) -> None:
        self.setStyleSheet("")
        accept, action = self._drag_policy(event)
        if not accept:
            event.ignore()
            return

        audio_files: list[str] = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.name.startswith("."):
                continue  # skip macOS dot-files / hidden sidecars
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                audio_files.append(str(path.resolve()))
            elif path.is_dir():
                try:
                    for child in path.rglob("*"):
                        if child.name.startswith("."):
                            continue  # skip macOS dot-files / hidden sidecars
                        if child.is_file() and child.suffix.lower() in AUDIO_EXTENSIONS:
                            audio_files.append(str(child.resolve()))
                except PermissionError:
                    pass

        if not audio_files:
            event.ignore()
            return
        # External OS drops get a stable alpha order; internal panel drags keep the
        # user's selection order (so Metadata's first-file rule uses the first dragged).
        if not self._source_page(event):
            audio_files = sorted(audio_files)
        event.setDropAction(action)
        event.accept()
        self.files_dropped.emit(audio_files)


class Sidebar(QFrame):
    """Left sidebar with navigation buttons."""

    page_changed = Signal(str)
    files_dropped_on_page = Signal(str, list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(Theme.SIDEBAR_WIDTH)
        self._buttons: dict[str, QPushButton] = {}
        # Labels kept so collapse can swap each button's text out (to a tooltip)
        # and back without losing the original translated string.
        self._labels: dict[QPushButton, str] = {}
        self._collapsed = False
        self._auto_badge: QLabel | None = None
        self._auto_badge_enabled = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 16, 6, 16)
        layout.setSpacing(4)

        # Collapse/expand toggle, aligned with the nav icons below it.
        self._toggle_btn = QPushButton()
        self._toggle_btn.setObjectName("sidebarButton")
        self._toggle_btn.setIcon(nav_icon("collapse"))
        self._toggle_btn.setIconSize(_NAV_ICON_SIZE)
        self._toggle_btn.setToolTip(self.tr("Collapse sidebar"))
        self._toggle_btn.clicked.connect(self._toggle_collapsed)
        layout.addWidget(self._toggle_btn)

        # Thin divider separating the toggle from the nav buttons.
        divider = QFrame()
        divider.setObjectName("sidebarDivider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        layout.addSpacing(4)

        # Button group for exclusive selection
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        # Navigation buttons
        pages = [
            ("player", self.tr("Player")),
            ("rename", self.tr("Rename")),
            ("convert", self.tr("Convert")),
            ("analysis", self.tr("Analyze")),
            ("keyboard", self.tr("Keyboard")),
            ("metadata", self.tr("Metadata")),
            ("spectrum", self.tr("Spectrum")),
        ]

        _no_drop_pages = {"keyboard"}

        for page_id, label in pages:
            if page_id in _no_drop_pages:
                btn = QPushButton(label)
            else:
                btn = _DroppableSidebarButton(label, page_id)
                btn.files_dropped.connect(lambda files, pid=page_id: self.files_dropped_on_page.emit(pid, files))
            btn.setObjectName("sidebarButton")
            btn.setIcon(nav_icon(page_id))
            btn.setIconSize(_NAV_ICON_SIZE)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, pid=page_id: self._on_button_clicked(pid))
            self._button_group.addButton(btn)
            self._buttons[page_id] = btn
            self._labels[btn] = label
            layout.addWidget(btn)

        # Select first button by default (Player, now at the top)
        self._buttons["player"].setChecked(True)

        # Russian's "Rename" label ("Переименовать") is the one sidebar string
        # too wide to fit at the normal 16px. Shrink ONLY that button's font in
        # ru mode (via a property the QSS keys off) so the whole word shows; all
        # other languages/buttons keep the default size. It looks slightly off
        # next to its neighbours, but it's the least-bad fix for one outlier.
        if load_config().language == "ru":
            rename_btn = self._buttons["rename"]
            rename_btn.setProperty("compactLabel", True)
            self._repolish(rename_btn)

        # Spacer
        layout.addStretch()

        # Bottom section
        # Settings button (no drop support)
        self._settings_btn = QPushButton(self.tr("Settings"))
        self._settings_btn.setObjectName("sidebarButton")
        self._settings_btn.setIcon(nav_icon("settings"))
        self._settings_btn.setIconSize(_NAV_ICON_SIZE)
        self._settings_btn.setCheckable(True)
        self._settings_btn.clicked.connect(lambda: self._on_button_clicked("settings"))
        self._button_group.addButton(self._settings_btn)
        self._buttons["settings"] = self._settings_btn
        self._labels[self._settings_btn] = self.tr("Settings")
        layout.addWidget(self._settings_btn)

        # History button (no drop support)
        self._history_btn = QPushButton(self.tr("History"))
        self._history_btn.setObjectName("sidebarButton")
        self._history_btn.setIcon(nav_icon("history"))
        self._history_btn.setIconSize(_NAV_ICON_SIZE)
        self._history_btn.setCheckable(True)
        self._history_btn.clicked.connect(lambda: self._on_button_clicked("history"))
        self._button_group.addButton(self._history_btn)
        self._buttons["history"] = self._history_btn
        self._labels[self._history_btn] = self.tr("History")
        layout.addWidget(self._history_btn)

        # Some languages leave the rail under-filled at the default 16px, so bump
        # their nav labels up (via a property the QSS keys off). The amount is
        # per-language: English's words are short enough for a big jump, German's
        # are longer ("Einstellungen") so it gets a smaller bump that still fits
        # the 176px rail. Languages not listed keep the 16px default.
        _label_size_prop = {"en": "bigLabel", "de": "germanLabel"}.get(
            load_config().language
        )
        if _label_size_prop:
            for btn in self._buttons.values():
                btn.setProperty(_label_size_prop, True)
                self._repolish(btn)

    def _toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    @property
    def collapsed(self) -> bool:
        """Whether the rail is currently collapsed to icons only."""
        return self._collapsed

    def min_content_height(self) -> int:
        """Height needed to show every nav button without clipping.

        Sums each row's own size hint plus the layout spacing and margins —
        the layout's aggregate sizeHint under-reports here because the buttons
        compress, so we add them up explicitly.
        """
        layout = self.layout()
        margins = layout.contentsMargins()
        total = margins.top() + margins.bottom()
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget()
            total += widget.sizeHint().height() if widget is not None else item.sizeHint().height()
            total += layout.spacing()
        return total

    def set_collapsed(self, collapsed: bool) -> None:
        """Collapse the rail to icons only (labels move to tooltips), or expand
        it back to icon + label."""
        self._collapsed = collapsed
        for btn, label in self._labels.items():
            btn.setText("" if collapsed else label)
            btn.setToolTip(label if collapsed else "")
            btn.setProperty("collapsed", collapsed)
            self._repolish(btn)

        self._toggle_btn.setProperty("collapsed", collapsed)
        self._repolish(self._toggle_btn)
        self._toggle_btn.setIcon(nav_icon("expand" if collapsed else "collapse"))
        self._toggle_btn.setToolTip(
            self.tr("Expand sidebar") if collapsed else self.tr("Collapse sidebar")
        )

        self.setFixedWidth(
            Theme.SIDEBAR_WIDTH_COLLAPSED if collapsed else Theme.SIDEBAR_WIDTH
        )
        if self._auto_badge is not None:
            self._auto_badge.setVisible(self._auto_badge_enabled and not collapsed)
        self._position_auto_badge()

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        """Re-evaluate a widget's stylesheet after a dynamic property change."""
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _on_button_clicked(self, page_id: str) -> None:
        """Handle navigation button click."""
        self.page_changed.emit(page_id)

    def set_current_page(self, page_id: str) -> None:
        """Set the current active page."""
        if page_id in self._buttons:
            self._buttons[page_id].setChecked(True)

    def set_auto_analyze_badge(self, enabled: bool) -> None:
        """Show/hide a small 'Auto' badge on the Analyze nav button."""
        btn = self._buttons.get("analysis")
        if btn is None:
            return
        if self._auto_badge is None:
            badge = QLabel(self.tr("Auto"), btn)
            badge.setObjectName("autoBadge")
            badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            badge.setStyleSheet(
                f"color: {Theme.NEON_YELLOW}; font-size: 12px; font-weight: bold; "
                "background: transparent;"
            )
            self._auto_badge = badge
            btn.installEventFilter(self)
        self._auto_badge_enabled = enabled
        # Hidden while collapsed: it would overlap the icon on the narrow button.
        self._auto_badge.setVisible(enabled and not self._collapsed)
        self._position_auto_badge()

    def _position_auto_badge(self) -> None:
        """Pin the 'Auto' badge to the top-right corner of the Analyze button."""
        if self._auto_badge is None:
            return
        btn = self._buttons.get("analysis")
        if btn is None:
            return
        self._auto_badge.adjustSize()
        x = btn.width() - self._auto_badge.width() - 6
        self._auto_badge.move(max(0, x), 2)
        self._auto_badge.raise_()

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Resize and obj is self._buttons.get("analysis"):
            self._position_auto_badge()
        return super().eventFilter(obj, event)
