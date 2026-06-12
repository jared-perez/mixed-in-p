"""Window sizing coordinator.

Owns everything about how the main window's minimum size and geometry react to
what the user is doing: per-panel minimum widths applied on page switch (the
window grows to fit but never shrinks, so the size carries over between panels),
the player slicer's wider minimum while expanded, geometry persistence across
restarts, and the width-driven responsive reflow (sidebar auto-collapse,
panel-description wrap cutoff).

All of this funnels through one object so the rules live in a single place and
the window's effective minimum is always set explicitly by us — never dictated
by a hidden panel (see :class:`CurrentPageStack`).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, QSize, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QStackedWidget

from .styles.theme import Theme, set_description_wrap

logger = logging.getLogger(__name__)

# Window width at/below which the sidebar auto-collapses; it auto-expands again
# at/above the upper bound. The dead-band between the two prevents flicker while
# the user drags the edge across the threshold.
_SIDEBAR_COLLAPSE_W = 950
_SIDEBAR_EXPAND_W = 980

# Panel-header descriptions wrap while the window is at least this wide; below
# the lower bound they switch to a single clipped line (dead-band as above).
_DESC_WRAP_ON_W = 1200
_DESC_WRAP_OFF_W = 1180

# Default opening size when there is no saved geometry.
_DEFAULT_W = 1120
_DEFAULT_H = 855

# Minimum window heights are floored here so a stray early size hint can't pin
# the window absurdly short before the real sidebar height is measured.
_MIN_HEIGHT_FLOOR = 480

# Fixed window minimum widths per panel (window width, sidebar included). Panels
# whose minimum is computed from their own controls (rename, convert) and the
# keyboard (resize-to-fit) are handled separately.
_PANEL_MIN_WIDTH = {
    "player": 600,
    "analysis": 600,
    "metadata": 750,
    "spectrum": 600,
    "history": 600,
    "settings": 600,
    "rename": 850,
    "convert": 850,
}

# Slack added to a computed panel-content width for the window frame + a possible
# vertical scrollbar, so the controls never sit flush against the edge.
_SLACK = 24


class CurrentPageStack(QStackedWidget):
    """A QStackedWidget whose size hints reflect only the *current* page.

    The default stack reports the maximum hint over all children, so a large
    hidden page (the keyboard panel's fixed-width piano) would inflate the
    window's minimum on every other page. Reporting just the current page lets
    the window shrink to whatever the active panel needs.
    """

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()


class WindowSizer:
    """Coordinates the main window's minimum size and geometry."""

    def __init__(self, window) -> None:
        self.window = window
        # Whether the player's loop slicer is currently expanded (raises the
        # player's minimum width to fit its controls).
        self._slice_expanded = False
        # Re-entrancy guard for sizer-initiated resizes.
        self._applying = False
        # True between startup and the deferred first responsive sync, so a
        # transient startup size can't sticky-collapse the sidebar.
        self._startup_settling = False
        # Lazily measured: header + full sidebar button stack height.
        self._min_height = _MIN_HEIGHT_FLOOR
        self._measured_height = False
        # Responsive-state trackers (None = not yet decided).
        self._sidebar_band: str | None = None  # "narrow" | "wide"
        self._wrap_on = True

    # ---------------------------------------------------------------- helpers

    def _ensure_min_height(self) -> None:
        """Measure the minimum height once the sidebar has a real layout."""
        if self._measured_height:
            return
        sidebar = self.window._sidebar
        # Height at which every nav button stays visible (header + full rail).
        needed = Theme.HEADER_HEIGHT + sidebar.min_content_height()
        self._min_height = max(_MIN_HEIGHT_FLOOR, needed)
        self._measured_height = True

    def _min_width_for(self, page_id: str) -> int:
        """Window minimum width for a panel.

        Floored by the header bar's own minimum width so the window can never be
        sized narrower than the logo + subtitle + buttons need — otherwise the
        header gets squeezed and the logo is clipped (the subtitle renders at its
        natural width and is not shrinkable, so it pins this minimum).
        """
        if page_id == "player":
            base = _PANEL_MIN_WIDTH["player"]
            if self._slice_expanded:
                row = self.window._player_panel.slice_time_row_min_width()
                base = max(base, Theme.SIDEBAR_WIDTH + row + _SLACK)
        else:
            base = _PANEL_MIN_WIDTH.get(page_id, 600)
        return max(base, self.window._header.minimumSizeHint().width())

    def _apply_page_min(self, page_id: str) -> None:
        self._ensure_min_height()
        self.window.setMinimumSize(self._min_width_for(page_id), self._min_height)

    def _guarded(self, fn) -> None:
        """Run a window-geometry mutation without re-entering the resize pass."""
        self._applying = True
        try:
            fn()
        finally:
            self._applying = False

    def _grow_to_min(self) -> None:
        """Enlarge the window if it's smaller than the current minimum.

        Only ever grows — switching to a narrower-min panel leaves the user's
        size untouched. Skipped while maximized/fullscreen.
        """
        w = self.window
        if w.isMaximized() or w.isFullScreen():
            return
        cur = w.size()
        tw = max(cur.width(), w.minimumWidth())
        th = max(cur.height(), w.minimumHeight())
        if tw != cur.width() or th != cur.height():
            self._guarded(lambda: w.resize(tw, th))

    # ------------------------------------------------------------- page switch

    def on_page_changed(self, page_id: str) -> None:
        # Every panel (keyboard included) just applies its own minimum and grows
        # the window only if it's smaller — so the size carries over from the
        # previously active panel.
        self._apply_page_min(page_id)
        self._grow_to_min()

    # ----------------------------------------------------------------- slicer

    def on_slicer_expanded(self, expanded: bool) -> None:
        self._slice_expanded = expanded
        # Only matters while the player is the active page.
        if self.window._current_page == "player":
            self._apply_page_min("player")
            self._grow_to_min()

    # ------------------------------------------------------------ persistence

    def restore_on_startup(self) -> None:
        """Restore saved geometry (or open at the default), then sync responsive
        state. Called once from the window's first showEvent."""
        # Suppress the responsive pass for the whole startup: applying the page
        # minimum and growing the window fire resize events at transient narrow
        # sizes that would otherwise sticky-collapse the sidebar before the
        # final size is in place.
        self._startup_settling = True
        self._ensure_min_height()
        self._apply_page_min(self.window._current_page)
        data = self.window._config.window_geometry
        restored = False
        if data:
            try:
                geo = QByteArray.fromBase64(data.encode("ascii"))
                self._guarded(lambda: self.window.restoreGeometry(geo))
                restored = True
            except Exception as exc:  # malformed config — fall back to default
                logger.warning("Failed to restore window geometry: %s", exc)
        if restored:
            self._ensure_on_screen()
        else:
            self._guarded(lambda: self.window.resize(_DEFAULT_W, _DEFAULT_H))
            self._center_on_primary()
        self._grow_to_min()
        # Run the first responsive sync once the event loop has applied the
        # final geometry (settling stays True until then), so it sees the real
        # opening width rather than a transient startup size.
        QTimer.singleShot(0, self._finish_startup)

    def _finish_startup(self) -> None:
        self._startup_settling = False
        self.on_resize()

    def _ensure_on_screen(self) -> None:
        """If the restored window isn't on any connected screen, re-center it."""
        frame = self.window.frameGeometry()
        for screen in QGuiApplication.screens():
            if screen.availableGeometry().intersects(frame):
                return
        self._center_on_primary()

    def _center_on_primary(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        frame = self.window.frameGeometry()
        frame.moveCenter(avail.center())
        self._guarded(lambda: self.window.move(frame.topLeft()))

    def save_geometry(self) -> None:
        """Persist the current window geometry. Called from closeEvent."""
        geo = self.window.saveGeometry()
        self.window._config.window_geometry = bytes(geo.toBase64()).decode("ascii")

    # ------------------------------------------------------------- responsive

    def on_resize(self) -> None:
        """Width-driven reflow. Called from the window's resizeEvent."""
        if self._applying or self._startup_settling:
            return
        width = self.window.width()
        self._update_sidebar(width)
        self._update_description_wrap(width)

    def _update_sidebar(self, width: int) -> None:
        """Auto-collapse the sidebar when the window enters the narrow band.

        Collapsing is sticky: widening never auto-expands — once collapsed the
        rail stays that way until the user clicks the expand button. Acting only
        on band *transitions* also leaves a manual expand within the narrow band
        alone (it won't be re-collapsed until the width leaves and re-enters).
        """
        if width <= _SIDEBAR_COLLAPSE_W:
            band = "narrow"
        elif width >= _SIDEBAR_EXPAND_W:
            band = "wide"
        else:
            return  # dead-band: hold current state
        if band == self._sidebar_band:
            return
        self._sidebar_band = band
        if band == "narrow":
            sidebar = self.window._sidebar
            if not sidebar.collapsed:
                self._guarded(lambda: sidebar.set_collapsed(True))

    def _update_description_wrap(self, width: int) -> None:
        if self._wrap_on and width < _DESC_WRAP_OFF_W:
            self._wrap_on = False
            set_description_wrap(False)
        elif not self._wrap_on and width >= _DESC_WRAP_ON_W:
            self._wrap_on = True
            set_description_wrap(True)
