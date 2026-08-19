"""Main application window."""

import logging
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

from src.analysis import history as analysis_history
from src import library
from src.library import playlist_export
from src.analysis.keycode import render_key
from src.analysis.result import SUPPORTED_EXTENSIONS, AnalysisResult
from src.metadata import (
    stores_tags,
    update_bpm_key,
    update_comment_with_energy,
    write_energy,
)
from src.renamer import (
    AddPrefix,
    AddSuffix,
    RenameOperation,
    RenamePreview,
    RenameSession,
    has_changes,
    has_conflicts,
    list_sessions,
    preview_rename,
)

from src.utils.args import shell_sorted
from src.utils.config import AppConfig, load_config, save_config
from src.utils.paths import normalize_track_path

from .models import TrackState, TrackStore
from .models.undo_stack import UndoStack
from .styles.theme import NoFocusDelegate, Theme
from .window_sizer import CurrentPageStack, WindowSizer
from src.conversion.result import ConversionResult

from .widgets.analysis_panel import AnalysisPanel
from .widgets.conversion_panel import ConversionPanel
from .widgets.dialogs.about_dialog import AboutDialog
from .widgets.header_bar import HeaderBar
from .widgets.history_panel import HistoryPanel
from .widgets.metadata_panel import MetadataPanel
from .widgets.keyboard_panel import KeyboardPanel
from .widgets.player_panel import PlayerPanel
from .widgets.playlist_tree import PlaylistTreePanel
from .widgets.rename_panel import RenamePanel
from .widgets.settings_panel import SettingsPanel
from .widgets.sidebar import PLAYLISTS_SHORTCUT, Sidebar
from .widgets.spectrum_panel import SpectrumPanel
from .workers import (
    AnalysisProgress,
    AnalysisThread,
    ConversionProgress,
    ConversionThread,
    RenameThread,
    UndoThread,
)


# How long ``open_files`` waits for the rest of a multi-file open before
# acting on what it has. The measured spread on Windows was 43 ms for five
# files, so this is roughly seven times the gap it exists to close — chosen
# because the two failure directions are wildly asymmetric. Too long is a
# pause before playback on a single-file open, and 300 ms is already lost in a
# 5.5 s cold start; too short splits one selection into two batches, which
# reloads Scratch, re-sorts around a file that is already in the list and
# starts playing the wrong track. Not user-configurable: it is a property of
# how the shells launch us, not a preference.
OPEN_BATCH_MS = 300

# How long closeEvent waits for an analysis thread to unwind. A cancel is only
# honoured between librosa passes, and the HPSS pass alone measured 5.6 s on a
# 4-minute track — so the old 3 s budget expired mid-call on any full-length
# file and the QThread was then destroyed while still running, which is
# undefined behaviour. Sized for a long track on a slow machine; it is an upper
# bound, not a delay, since the wait returns as soon as the thread does.
_ANALYSIS_JOIN_MS = 15000


def apply_scratch_policy(lib: "library.Library", persist: bool) -> None:
    """Empty Scratch at startup unless the user asked to keep it.

    Scratch is the disposable working list the Player opens on, so a session
    starts clean and anything worth keeping is kept with Save Playlist. Only
    its membership rows go: the node is reserved and always exists, and the
    library's own GC keeps any track that a saved playlist still holds.
    """
    if not persist:
        lib.set_items(library.SCRATCH_NODE_ID, [])


class MainWindow(QMainWindow):
    """Main application window for Mixed in P."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(self.tr("Mixed in P"))

        # Create track store
        self._store = TrackStore(self)

        # Analysis thread reference
        self._analysis_thread: AnalysisThread | None = None
        # Cancelled analysis threads, detached from the UI but still running
        # out their current file. Held only so closeEvent can join them.
        self._orphaned_analysis_threads: list[AnalysisThread] = []
        self._analyzing_track_ids: list[str] = []

        # Conversion thread reference
        self._conversion_thread: ConversionThread | None = None

        # Rename thread reference
        self._rename_thread: RenameThread | None = None
        self._undo_thread: UndoThread | None = None
        self._last_session: RenameSession | None = None
        # None = no pipeline running; list = pipeline triggered from Rename panel
        self._pending_rename_operations: list[RenameOperation] | None = None

        # Track current page for context-aware file routing
        self._current_page: str = "player"

        # Files the OS hands us arrive one at a time; this collects them.
        self._setup_open_batch()

        # Load persisted config
        self._config: AppConfig = load_config()

        self._setup_ui()
        # Coordinates per-panel minimum sizes, the keyboard resize-to-fit,
        # geometry persistence, and responsive reflow. Applied for real on the
        # first showEvent (so it measures a laid-out sidebar).
        self._sizer = WindowSizer(self)
        self._geometry_restored = False
        # Sidebar width while in playlists mode. Deliberately session-only
        # (not in config): also sidesteps restoring an oversized sidebar
        # onto a smaller screen.
        self._playlists_sidebar_w = Theme.SIDEBAR_PLAYLISTS_DEFAULT
        # Session write-freeze (Analyze panel's Freeze toggle). Deliberately
        # session-only and never read from or written to AppConfig: because the
        # stored settings are never touched, "restore what was on when the
        # freeze ends" is satisfied by construction — there is nothing to
        # restore, and a crash mid-freeze cannot strand a half-restored setting.
        # Always starts unfrozen.
        self._analysis_writes_frozen = False
        self._connect_signals()
        self._analysis_panel.set_auto_analyze(self._config.auto_analyze)
        self._analysis_panel.set_auto_write_bpm(self._config.auto_write_bpm)
        self._analysis_panel.set_auto_write_key(self._config.auto_write_key)
        self._analysis_panel.set_key_notation(self._config.key_notation)
        self._keyboard_panel.set_key_notation(self._config.key_notation)
        self._player_panel.set_key_notation(self._config.key_notation)
        self._player_panel.set_waveform_color(self._effective_waveform_color())
        self._player_panel.set_text_size(self._config.player_text_size)
        self._player_panel.set_artwork_view(self._config.player_artwork_view)
        self._apply_visualization_settings()
        self._sidebar.set_auto_analyze_badge(self._config.auto_analyze)
        self._spectrum_panel.set_dynamic_range(self._config.spectrum_dynamic_range)
        # Playlist library: one shared main-thread connection. Opened at
        # startup (creating the database on first run) because Scratch
        # persistence — the Player's list surviving a restart — needs it.
        self._library = library.Library()
        self._playlists_panel.set_library(self._library)
        self._player_panel.set_library(self._library)
        # Playlist edits auto-save, so Cmd/Ctrl+Z is the only way back (§11).
        # One stack for both views: a delete in the tree and a Clear in the
        # Player are the same kind of mistake and undo in the same order.
        self._undo_stack = UndoStack(self)
        self._playlists_panel.set_undo_stack(self._undo_stack)
        self._player_panel.set_undo_stack(self._undo_stack)
        self._undo_stack.undone.connect(self._on_undone)
        undo_sc = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo_sc.activated.connect(self._on_undo_shortcut)
        # Cleared before the Player reads it, so the session opens on an empty
        # working list. Done at startup rather than on close so a crash can't
        # strand yesterday's list, and through the library API rather than the
        # panel so it lands before the undo stack is live — otherwise the
        # clear would be undoable and yesterday's Scratch could come back.
        apply_scratch_policy(self._library, self._config.persist_scratch)
        self._player_panel.load_node(library.SCRATCH_NODE_ID)
        self._load_last_session()

    def _setup_ui(self) -> None:
        """Set up the main window UI layout."""
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout (vertical: header + content)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header bar
        self._header = HeaderBar()
        main_layout.addWidget(self._header)

        # Content area (horizontal: sidebar | pages). A splitter rather than a
        # box layout so the sidebar is user-resizable in playlists mode; in nav
        # mode the sidebar's fixed width keeps the handle immobile, preserving
        # the old behavior exactly.
        self._sidebar = Sidebar()
        self._playlists_panel = PlaylistTreePanel()
        self._sidebar.playlists_layout.addWidget(self._playlists_panel)

        # Stacked widget for pages. CurrentPageStack reports only the active
        # page's size hints so a hidden large panel (the keyboard) can't inflate
        # the window minimum on every other page.
        self._pages = CurrentPageStack()

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self._sidebar)
        self._splitter.addWidget(self._pages)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.splitterMoved.connect(self._on_splitter_moved)
        main_layout.addWidget(self._splitter)

        # Create pages
        self._create_pages()
        # Open on the Player panel (top of the sidebar) rather than the
        # stacked widget's first-added page (Rename, index 0).
        self._pages.setCurrentWidget(self._player_panel)

        # Remove native focus rectangles from all table widgets. Skip the player
        # playlist: its NoElideDelegate already suppresses the focus rect AND
        # disables '…' elision, so overriding it here would bring the ellipsis
        # back (NoElideDelegate must stay the default delegate on that table).
        delegate = NoFocusDelegate(self)
        player_table = self._player_panel._table
        for table in self.findChildren(QTableWidget):
            if table is player_table:
                continue
            table.setItemDelegate(delegate)

    def _create_pages(self) -> None:
        """Create all pages."""
        self._page_widgets: dict[str, QWidget] = {}

        # Rename panel (index 0)
        self._rename_panel = RenamePanel(self._store)
        self._page_widgets["rename"] = self._rename_panel
        self._pages.addWidget(self._rename_panel)

        # Conversion panel (index 1)
        self._conversion_panel = ConversionPanel(self._store)
        self._page_widgets["convert"] = self._conversion_panel
        self._pages.addWidget(self._conversion_panel)

        # Analysis panel (index 2)
        self._analysis_panel = AnalysisPanel(self._store)
        self._page_widgets["analysis"] = self._analysis_panel
        self._pages.addWidget(self._analysis_panel)

        # Player panel (index 3)
        self._player_panel = PlayerPanel()
        self._page_widgets["player"] = self._player_panel
        self._pages.addWidget(self._player_panel)

        # Keyboard panel (index 4)
        self._keyboard_panel = KeyboardPanel()
        self._page_widgets["keyboard"] = self._keyboard_panel
        self._pages.addWidget(self._keyboard_panel)

        # Metadata panel (index 5)
        self._metadata_panel = MetadataPanel()
        self._page_widgets["metadata"] = self._metadata_panel
        self._pages.addWidget(self._metadata_panel)

        # Spectrum panel (index 6)
        self._spectrum_panel = SpectrumPanel()
        self._page_widgets["spectrum"] = self._spectrum_panel
        self._pages.addWidget(self._spectrum_panel)

        # History panel (index 7)
        self._history_panel = HistoryPanel()
        self._history_panel.set_history_limit(self._config.history_display_limit)
        self._page_widgets["history"] = self._history_panel
        self._pages.addWidget(self._history_panel)

        # Settings panel (index 8)
        self._settings_panel = SettingsPanel()
        self._settings_panel.load_config(self._config)
        self._page_widgets["settings"] = self._settings_panel
        self._pages.addWidget(self._settings_panel)

    def _connect_signals(self) -> None:
        """Connect signals to slots."""
        # Header signals
        self._header.add_files_clicked.connect(self._on_add_files)
        self._header.add_folder_clicked.connect(self._on_add_folder)
        self._header.about_clicked.connect(self._on_about)
        self._header.now_playing_clicked.connect(self._on_header_now_playing_clicked)

        # Sidebar signals
        self._sidebar.page_changed.connect(self._on_page_changed)
        self._sidebar.files_dropped_on_page.connect(self._on_sidebar_drop)
        self._sidebar.playlists_toggled.connect(self._on_playlists_toggled)
        self._sidebar.collapsed_changed.connect(lambda _c: self._apply_playlists_splitter())
        self._apply_playlists_splitter()  # start with the handle locked
        # Shift+Tab shows/hides the playlists tree from anywhere in the window.
        # See PLAYLISTS_SHORTCUT for what this key costs and why it is still it.
        #
        # WindowShortcut is the scope, matching the undo shortcut above — but
        # note what it is *not* doing, because the obvious assumption is wrong
        # and was written here before it was checked: it is not what stops the
        # hotkey firing behind a modal. Qt's modal event blocking does that on
        # its own, and an ApplicationShortcut is blocked identically (measured
        # — the dialog test passes under both, so it does not pin this line).
        # The context is about scope alone: this belongs to the main window.
        playlists_sc = QShortcut(PLAYLISTS_SHORTCUT, self)
        playlists_sc.setContext(Qt.ShortcutContext.WindowShortcut)
        playlists_sc.activated.connect(self._sidebar.toggle_playlists_mode)
        self._playlists_panel.tree.playlist_activated.connect(self._on_playlist_activated)
        self._playlists_panel.tree.tracks_added.connect(self._on_tracks_added)
        self._playlists_panel.tree.nodes_changed.connect(
            self._player_panel.refresh_playing_playlist
        )
        self._player_panel.playlist_saved.connect(self._on_playlist_saved)
        self._player_panel.tree_highlight_changed.connect(self._on_tree_highlight)
        self._player_panel.playing_playlist_clicked.connect(
            self._on_playing_playlist_clicked
        )
        self._player_panel.now_playing_changed.connect(self._sync_header_now_playing)

        # Rename panel signals (file drop + full pipeline)
        self._rename_panel.files_dropped.connect(self._add_files)
        self._rename_panel.analyze_and_rename.connect(self._analyze_and_rename_files)

        # Conversion panel signals
        self._conversion_panel.start_conversion.connect(self._start_conversion)
        self._conversion_panel.cancel_conversion.connect(self._cancel_conversion)
        self._conversion_panel.send_to_analyze.connect(self._send_convert_to_analyze)
        self._conversion_panel.send_to_rename.connect(self._send_convert_to_rename)
        self._conversion_panel.send_to_player.connect(self._on_send_to_player)

        # Analysis panel signals
        self._analysis_panel.files_dropped.connect(self._add_and_analyze_files)
        self._analysis_panel.cancel_analysis.connect(self._cancel_analysis)
        self._analysis_panel.send_to_player.connect(self._on_send_to_player)
        self._analysis_panel.send_to_convert.connect(self._send_analyze_to_convert)
        self._analysis_panel.start_analysis.connect(self._on_manual_analyze)
        self._analysis_panel.auto_analyze_toggled.connect(self._on_auto_analyze_toggled)
        self._analysis_panel.write_freeze_toggled.connect(self._on_write_freeze_toggled)

        # Rename panel signals
        self._rename_panel.apply_rename.connect(self._start_rename)
        self._rename_panel.undo_last.connect(self._undo_last_rename)
        self._rename_panel.send_to_convert.connect(self._send_rename_to_convert)

        # History panel signals
        self._history_panel.undo_session.connect(self._undo_session_from_history)
        self._history_panel.history_limit_changed.connect(
            self._on_history_limit_changed
        )

        # Player panel signals
        self._player_panel.files_dropped.connect(self._add_files_to_player)
        self._player_panel.open_in_metadata.connect(self._open_in_metadata_panel)
        self._player_panel.slice_expanded.connect(self._sizer.on_slicer_expanded)
        self._player_panel.compat_panel_toggled.connect(self._sizer.on_compat_panel_toggled)

        # Spectrum panel signals
        self._spectrum_panel.files_dropped.connect(self._add_files)
        self._spectrum_panel.sensitivity_changed.connect(self._on_spectrum_sensitivity)

        # Settings panel signals
        self._settings_panel.settings_changed.connect(self._on_settings_changed)
        self._settings_panel.export_all_playlists.connect(
            self._on_export_all_playlists
        )

    def _load_last_session(self) -> None:
        """Load the most recent rename session for undo."""
        try:
            sessions = list_sessions(limit=1)
            if sessions:
                self._last_session = sessions[0]
                self._rename_panel.set_undo_enabled(True)
        except Exception:
            pass

    def _on_page_changed(self, page_id: str) -> None:
        """Handle page navigation."""
        page_indices = {
            "rename": 0,
            "convert": 1,
            "analysis": 2,
            "player": 3,
            "keyboard": 4,
            "metadata": 5,
            "spectrum": 6,
            "history": 7,
            "settings": 8,
        }
        if page_id in page_indices:
            self._current_page = page_id
            self._pages.setCurrentIndex(page_indices[page_id])

        # Stop keyboard audio when navigating away
        if page_id != "keyboard":
            self._keyboard_panel.stop_audio()

        # Refresh panels when switching to them
        if page_id == "rename":
            self._rename_panel.refresh()
        elif page_id == "convert":
            self._conversion_panel.refresh()
        elif page_id == "player":
            self._player_panel.refresh()
        elif page_id == "history":
            self._history_panel.refresh()

        # The header's now-playing line is for the panels that aren't the
        # Player, so which page is showing is half of what decides it.
        self._sync_header_now_playing()

        # Apply the panel's window minimum (and keyboard resize-to-fit). Done
        # after the page is current so size hints reflect the new panel.
        if self._geometry_restored:
            self._sizer.on_page_changed(page_id)

    def _on_playlists_toggled(self, on: bool) -> None:
        if on:
            self._playlists_panel.ensure_loaded()
        self._apply_playlists_splitter()

    def _on_playlist_activated(self, node_id: int) -> None:
        """A playlist (or Scratch) clicked in the tree loads into the Player."""
        self._player_panel.load_node(node_id)
        self._sidebar.set_current_page("player")
        self._on_page_changed("player")

    def _sync_header_now_playing(self) -> None:
        """Put what's playing in the header — unless the Player is showing it.

        Two inputs, so this is called from both: which page is current, and
        what the Player has loaded.
        """
        if self._current_page == "player":
            self._header.set_now_playing("")
            return
        self._header.set_now_playing(self._player_panel.playing_track_name())

    def _on_header_now_playing_clicked(self) -> None:
        """The header's now-playing line: take the user to what's playing.

        To the playlist it came from where there is one — the same destination
        as the Player's own "In Playlist" link, reached from a panel that
        isn't the Player. A track played out of a search result set has no
        playlist to go to, so that falls back to just opening the Player,
        which is still the thing the user was asking for.
        """
        node_id = self._player_panel.playing_node_id
        if node_id is not None and not self._player_panel.is_showing_node(node_id):
            self._player_panel.load_node(node_id)
        if node_id is not None:
            self._playlists_panel.tree.select_node(node_id)
        self._sidebar.set_current_page("player")
        self._on_page_changed("player")

    def _on_playing_playlist_clicked(self, node_id: int) -> None:
        """The Player's "In Playlist" link: go to the list the track plays from.

        Routed here rather than handled in the panel so the tree's selection
        follows too — the same end state as clicking that playlist in the tree,
        reached from the other direction. Already on the Player page by
        construction (the link lives there), so no page switch.
        """
        if not self._player_panel.is_showing_node(node_id):
            self._player_panel.load_node(node_id)
        self._playlists_panel.tree.select_node(node_id)

    def _on_tracks_added(self, node_id: int) -> None:
        """Tracks were dropped into a playlist in the tree.

        Only interesting when it is the list the Player is showing: its
        visible rows are now stale, and the next auto-save would write them
        back over the drop, silently undoing it.
        """
        if node_id == self._player_panel.loaded_node_id:
            self._player_panel.load_node(node_id)

    def _on_playlist_saved(self, _node_id: int) -> None:
        """Save Playlist created a node — make sure the tree shows it."""
        self._playlists_panel.ensure_loaded()
        self._playlists_panel.tree.refresh()

    def _on_export_all_playlists(self) -> None:
        """Settings → Export All Playlists… (§7d): the whole tree as files.

        This is the backup story, deliberately made of plain playlist files
        rather than a proprietary blob — there is nothing to restore *from*,
        because any app can already read what it writes. Scratch comes along:
        it survives restarts and can hold real work.
        """
        directory = QFileDialog.getExistingDirectory(
            self, self.tr("Export All Playlists")
        )
        if not directory:
            return
        try:
            # Folder name is data, not UI prose — left untranslated so
            # exports from any language land in the same place.
            target = playlist_export.unique_path(
                directory, "Mixed in P Playlists", ""
            )
            target.mkdir(parents=True)
            playlists, tracks = playlist_export.export_tree(
                self._library,
                target,
                absolute=self._config.export_absolute_paths,
                include_scratch=True,
            )
        except (OSError, ValueError) as exc:
            logger.error("Export all playlists failed: %s", exc)
            QMessageBox.warning(
                self,
                self.tr("Export failed"),
                self.tr("Could not write the file:\n{0}").format(exc),
            )
            return
        if not playlists:
            target.rmdir()  # don't leave an empty folder behind
            QMessageBox.information(
                self,
                self.tr("Export All Playlists"),
                self.tr("There are no playlists to export yet."),
            )
            return
        QMessageBox.information(
            self,
            self.tr("Export complete"),
            self.tr("Exported {0} playlists ({1} tracks) to:\n{2}").format(
                playlists, tracks, target
            ),
        )

    def _on_undo_shortcut(self) -> None:
        """Cmd/Ctrl+Z: text editing first, then the playlist undo stack (§11).

        A window-level shortcut is consumed before the key reaches the
        focused widget, so without this hand-off Cmd+Z would stop undoing
        *typing* — in the tree's inline rename editor, the Player's search
        field, and every metadata field. Text editors keep their own undo;
        the playlist stack only gets the keystroke when no editor has focus.
        """
        widget = QApplication.focusWidget()
        if isinstance(widget, QAbstractSpinBox):
            widget = widget.findChild(QLineEdit)
        if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit)):
            widget.undo()
            return
        self._undo_stack.undo()

    def _on_undone(self, _label: str) -> None:
        """An undo rewrote library state — resync both views onto it.

        The entries themselves only touch the database, so this is the one
        place that knows how to show the result: the tree re-reads, and the
        Player reloads its node (which is a no-op for content that didn't
        change, and falls back to Scratch if that node is gone).
        """
        self._playlists_panel.tree.refresh()
        node_id = self._player_panel.loaded_node_id
        if self._library.get_node(node_id) is None:
            node_id = library.SCRATCH_NODE_ID
        self._player_panel.load_node(node_id)

    def _on_tree_highlight(self, playlist_ids, folder_counts) -> None:
        """A search selection changed — light (or clear) the tree's trail.

        The tree stores the state even before its first load, so there is
        no ensure_loaded here: opening playlists mode later paints it."""
        self._playlists_panel.tree.set_highlight(playlist_ids, folder_counts)

    def _apply_playlists_splitter(self) -> None:
        """Sync the splitter with the sidebar's mode.

        Expanded playlists mode gets a live handle and the session's
        remembered width; every other state locks the handle and lets the
        sidebar's fixed width dictate the split.
        """
        live = self._sidebar.playlists_mode and not self._sidebar.collapsed
        handle = self._splitter.handle(1)
        if handle is not None:
            handle.setEnabled(live)
        # Widen the handle's grab area while it's draggable — a 2px sliver is
        # too fiddly to hit. Width lives here (QSS width would override it);
        # the playlistsLive property drives the handle's colors in the QSS.
        self._splitter.setHandleWidth(10 if live else 2)
        if self._splitter.property("playlistsLive") != live:
            self._splitter.setProperty("playlistsLive", live)
            self._splitter.style().unpolish(self._splitter)
            self._splitter.style().polish(self._splitter)
        total = sum(self._splitter.sizes())
        if live:
            width = min(
                max(self._playlists_sidebar_w, Theme.SIDEBAR_PLAYLISTS_MIN),
                Theme.SIDEBAR_PLAYLISTS_MAX,
            )
        elif self._sidebar.collapsed:
            width = Theme.SIDEBAR_WIDTH_COLLAPSED
        else:
            width = Theme.SIDEBAR_WIDTH
        # Explicit setSizes even in the pinned states: changing a child's
        # fixed width does not make the splitter re-layout on its own.
        self._splitter.setSizes([width, max(0, total - width)])

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        """Remember the user's chosen sidebar width (session only)."""
        if self._sidebar.playlists_mode and not self._sidebar.collapsed:
            self._playlists_sidebar_w = self._splitter.sizes()[0]

    def _on_sidebar_drop(self, page_id: str, file_paths: list[str]) -> None:
        """Handle files dropped on a sidebar button."""
        self._sidebar.set_current_page(page_id)
        self._on_page_changed(page_id)
        self._add_files(file_paths)

    def _on_add_files(self) -> None:
        """Open file dialog to add audio files."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            self.tr("Select Audio Files"),
            "",
            "Audio Files (*.mp3 *.wav *.flac *.aiff *.aif *.m4a *.ogg);;All Files (*)",
        )
        if files:
            self._add_files(files)

    def _on_add_folder(self) -> None:
        """Open folder dialog to add all audio files from a directory."""
        folder = QFileDialog.getExistingDirectory(
            self,
            self.tr("Select Folder"),
            "",
        )
        if folder:
            self._add_folder(folder)

    def _add_files(self, file_paths: list[str]) -> None:
        """Route files to the currently active panel."""
        page = self._current_page

        if page == "convert":
            self._conversion_panel.add_files(file_paths)
        elif page == "analysis":
            self._add_and_analyze_files(file_paths)
        elif page == "player":
            self._add_files_to_player(file_paths)
        elif page == "metadata":
            self._metadata_panel._load_file(file_paths[0])
        elif page == "spectrum":
            self._spectrum_panel._load_file(file_paths[0])
        else:
            # Default: rename panel (also handles settings, keycode, history)
            self._add_files_to_rename(file_paths)

    def _add_files_to_rename(self, file_paths: list[str]) -> None:
        """Add files to the rename panel via TrackStore."""
        added = 0
        self._store.begin_batch_update()
        for path in file_paths:
            track = self._store.add_from_path(path)
            if track is None:
                # Already in the store (e.g. dragged from Analyze, which shares this
                # TrackStore) — re-queue it so it moves into the Rename view instead
                # of being a no-op.
                track = self._store.get_by_path(path)
                if track is not None and track.state != TrackState.QUEUED:
                    self._store.update(track.id, state=TrackState.QUEUED)
            if track is not None:
                added += 1
        self._store.end_batch_update()

        if added > 0:
            self._sidebar.set_current_page("rename")
            self._on_page_changed("rename")

    def _setup_open_batch(self) -> None:
        """The buffer that turns several one-file arrivals into one batch.

        Wired in one place so the tests can stand up the same machinery
        against a stub instead of re-describing it.
        """
        self._open_batch: list[str] = []
        self._open_batch_timer = QTimer(self)
        self._open_batch_timer.setSingleShot(True)
        self._open_batch_timer.timeout.connect(self._flush_open_batch)

    def open_files(self, file_paths: list[str]) -> None:
        """Take on files handed to us by the OS. The one funnel for every route.

        Everything that means "the user picked these in Finder or Explorer"
        ends here — argv on a cold start, a ``QFileOpenEvent`` on macOS, and a
        secondary process's handoff on a warm one — so the behaviour cannot
        drift between them.

        **A multi-file open is not one call.** Windows spawns one process per
        file (measured 2026-08-06: five files, five processes, 25–43 ms apart)
        and macOS sends one event per file, so the files land here a few
        milliseconds apart, in a racing order. Rather than act on each, the
        paths are collected for ``OPEN_BATCH_MS`` and handled once, in
        ``_flush_open_batch`` — which is what lets the list be sorted and the
        *first* file be the one that plays. Without the wait the app would
        commit to playing whichever process happened to win.

        Coming to the front is the exception and happens immediately: a
        relaunch carrying no files at all (double-clicking the app while it
        runs) means "show me", and that answer should not wait on a batch that
        will turn out to be empty.

        Unsupported files are dropped rather than refused: a selection of a
        folder's worth of files should add the audio and ignore the artwork,
        not fail. argv arrivals were filtered already — this repeats it
        because ``QFileOpenEvent`` and the IPC handoff have no such guarantee.
        """
        self._raise_to_front()

        paths = [
            p for p in file_paths if Path(p).suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        if not paths:
            return

        self._open_batch.extend(paths)
        # Started, not restarted: the window runs from the *first* file, so a
        # steady trickle of arrivals cannot postpone playback indefinitely.
        if not self._open_batch_timer.isActive():
            self._open_batch_timer.start(OPEN_BATCH_MS)

    def _flush_open_batch(self) -> None:
        """Add everything that arrived in the window, and play the first.

        The order of the steps is the substance:

        1. **Load Scratch first.** Without this, a file arriving while a saved
           playlist is showing would append to the user's set list and
           auto-save it. Scratch is the disposable working list; that is what
           makes this feature safe to trigger from a right-click.
        2. **Sort as the shell showed them.** Arrival order is a race result
           and means nothing to the user; see ``shell_sorted``.
        3. **Force duplicates.** The alternative is the duplicate prompt, and
           that prompt is deferred off a zero-delay timer — during app launch
           it could land before the window is even mapped. A modal nobody
           asked for is worse than a repeated row in a disposable list.
        4. **Play only if idle.** A cold start always plays, because that is
           the point — the owner's words: "the user wants to listen to them
           right away, which is what Open with is supposed to provide". A file
           arriving mid-track does not, because cutting off playback in a DJ
           app is a real-world harm.
        """
        paths = shell_sorted(self._open_batch)
        self._open_batch = []
        if not paths:
            return

        self._player_panel.load_node(library.SCRATCH_NODE_ID)
        self._sidebar.set_current_page("player")
        self._on_page_changed("player")
        # No scroll to the end: the first of these files is about to start
        # playing, and its row is at the top.
        self._add_files_to_player(paths, allow_duplicates=True, scroll_to_end=False)

        # add_tracks resolves synchronously when the policy is forced, so the
        # tracks are in the list by now and this can act on the first of them.
        # Normalized separately, and identically, to the copy _add_files_to_player
        # stored — matching on the raw string would silently never find the row.
        self._player_panel.play_path_if_idle(normalize_track_path(paths[0]))

    def _raise_to_front(self) -> None:
        """Bring the window up and give it focus, from whatever state it is in.

        ``show()`` alone leaves a minimized window minimized, and ``raise_()``
        alone leaves a raised window unfocused — a file opened from Finder has
        to land somewhere the user is actually looking.
        """
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def _add_files_to_player(
        self,
        file_paths: list[str],
        allow_duplicates: bool | None = None,
        *,
        scroll_to_end: bool = True,
    ) -> None:
        """Add files directly to the player panel, reading metadata from tags.

        Paths are normalized here because this is where the un-normalized ones
        arrive: QFileDialog returns forward slashes on every platform (so
        ``C:/music/a.mp3`` on Windows) while ``find_audio_files`` and argv
        return native separators, and both land in the library as literal
        strings. Drops already normalize in their own handlers. See
        src/utils/paths.py.

        ``allow_duplicates`` is passed straight through to ``add_tracks``; the
        default ``None`` consults the user's setting, which may put the
        question to them in a modal. ``open_files`` forces ``True`` — see
        there for why a prompt is unacceptable on that path.

        ``scroll_to_end`` likewise goes straight through. ``open_files`` turns
        it off: that path plays the first of the files it just added, and the
        row that is playing is the one the user must be able to see.
        """
        from src.metadata.tags import read_metadata

        tracks = []
        for raw in file_paths:
            p = normalize_track_path(raw)
            track: dict[str, str] = {
                "file_path": p,
                "display_name": Path(p).name,
            }
            try:
                meta = read_metadata(p)
                if meta.artist:
                    track["artist"] = meta.artist
                if meta.title:
                    track["title"] = meta.title
                if meta.album:
                    track["album"] = meta.album
                if meta.genre:
                    track["genre"] = meta.genre
                if meta.bpm:
                    track["bpm"] = f"{meta.bpm:.1f}"
                if meta.key:
                    track["key"] = meta.key
                if meta.comment:
                    track["comment"] = meta.comment
                if meta.year:
                    track["year"] = str(meta.year)
                if meta.track_number:
                    track["track_number"] = str(meta.track_number)
                if meta.label:
                    track["label"] = meta.label
                if meta.bitrate:
                    track["bitrate"] = str(meta.bitrate)
                if meta.energy:
                    track["energy"] = str(meta.energy)
                if meta.duration and meta.duration > 0:
                    track["duration"] = meta.duration
            except Exception:
                pass  # proceed without metadata
            tracks.append(track)
        self._player_panel.add_tracks(
            tracks, allow_duplicates=allow_duplicates, scroll_to_end=scroll_to_end
        )

    def _add_folder(self, folder_path: str) -> None:
        """Add all audio files from folder."""
        try:
            from src.analysis.result import find_audio_files

            files = find_audio_files(folder_path, recursive=True)
            if files:
                self._add_files(files)
            else:
                QMessageBox.information(
                    self,
                    self.tr("No Audio Files"),
                    self.tr("No audio files found in:\n{0}").format(folder_path),
                )
        except NotADirectoryError:
            QMessageBox.warning(
                self,
                self.tr("Invalid Folder"),
                self.tr("Not a valid directory:\n{0}").format(folder_path),
            )

    def _add_and_analyze_files(self, file_paths: list[str]) -> None:
        """Add files and start analysis (immediately if auto-analyze is on)."""
        track_ids: list[str] = []
        self._store.begin_batch_update()
        for path in file_paths:
            track = self._store.add_from_path(path)
            if track is None:
                # File already in store — reuse existing track
                track = self._store.get_by_path(path)
            if track is not None:
                track_ids.append(track.id)
                if not self._config.auto_analyze:
                    # Mark as PENDING inside the batch so the model sees
                    # them when the batch reset fires
                    self._store.update(track.id, state=TrackState.PENDING)
        self._store.end_batch_update()

        if track_ids:
            # Switch to analysis page
            self._sidebar.set_current_page("analysis")
            self._on_page_changed("analysis")
            self._pending_rename_operations = []  # enable auto-rename gate
            if self._config.auto_analyze:
                self._start_analysis(track_ids)

    def _start_analysis(self, track_ids: list[str]) -> None:
        """Start analysis for the given tracks."""
        if self._analysis_thread is not None and self._analysis_thread.isRunning():
            # A batch is already running. Rather than blocking the user with a
            # warning, enqueue these tracks (mark them PENDING so they show in the
            # Analyze table) and leave them to be analyzed later. In auto mode
            # _start_pending_analysis picks them up as soon as the current batch
            # finishes; in manual mode they wait in the queue until the user
            # presses Analyze again. Tracks that are already queued/analysing are
            # left untouched, so re-dropping in-flight files is a no-op rather
            # than a duplicate.
            for track_id in track_ids:
                track = self._store.get(track_id)
                if track and track.state == TrackState.QUEUED:
                    self._store.update(track_id, state=TrackState.PENDING)
            return

        # Get file paths and mark as pending
        file_paths: list[str] = []
        self._analyzing_track_ids = []

        for track_id in track_ids:
            track = self._store.get(track_id)
            # QUEUED = freshly added (auto-analyze path); PENDING = waiting in the
            # Analyze panel for a manual trigger (auto-analyze off). Both are ready
            # to analyze — accepting only QUEUED made the manual Analyze button a
            # no-op when auto-analyze was off.
            if track and track.state in (TrackState.QUEUED, TrackState.PENDING):
                file_paths.append(track.file_path)
                self._analyzing_track_ids.append(track_id)
                self._store.update(track_id, state=TrackState.PENDING)

        if not file_paths:
            return

        # Switch to analysis page
        self._sidebar.set_current_page("analysis")
        self._on_page_changed("analysis")

        # Start progress panel
        self._analysis_panel.progress_panel.start(len(file_paths))

        # Create and start analysis thread
        self._analysis_thread = AnalysisThread(
            file_paths,
            min_bpm=self._config.min_bpm,
            max_bpm=self._config.max_bpm,
            parent=self,
        )
        self._analysis_thread.analysis_started.connect(self._on_analysis_started)
        self._analysis_thread.analysis_progress.connect(self._on_analysis_progress)
        self._analysis_thread.analysis_finished.connect(self._on_analysis_finished)
        self._analysis_thread.analysis_cancelled.connect(self._on_analysis_cancelled)
        self._analysis_thread.start()
        self._analysis_panel.set_analyzing(True)
        self._sidebar.set_page_busy("analysis", True)

    def _analyze_and_rename_files(
        self, track_ids: list[str], operations: list[RenameOperation]
    ) -> None:
        """Start the full pipeline: analyze → metadata → auto-rename."""
        self._pending_rename_operations = operations
        self._start_analysis(track_ids)

    def _cancel_analysis(self) -> None:
        """Cancel the current analysis and report it cancelled immediately.

        The worker cannot be stopped promptly. On a warm run roughly 97% of a
        file's analysis is one uninterruptible HPSS call inside librosa, so a
        cancel landing mid-file is not honoured until that call returns — several
        seconds on a full-length track. Blocking the UI on that is the bug this
        fixes: the button looked dead and the run then reported success.

        So the UI is detached from the worker here. Its signals are disconnected,
        the run is reported cancelled at once, and the orphaned thread winds down
        in the background with its results discarded. The cooperative checkpoints
        in analyze_file still stop it before it starts on another file, so a
        cancelled batch does not chew through the rest of the queue.
        """
        thread = self._analysis_thread
        if thread is None or not thread.isRunning():
            return

        # Detach before anything else: whatever this thread emits from here on
        # describes a run the user has already ended, and _on_analysis_finished
        # would otherwise overwrite the cancelled state with "Complete".
        # These are always connected in _start_analysis and this runs at most
        # once per thread (the guard above returns on the second call), so the
        # disconnects succeed; the guard is for a thread whose C++ side has
        # already gone, which raises RuntimeError.
        for signal in (
            thread.analysis_started,
            thread.analysis_progress,
            thread.analysis_finished,
            thread.analysis_cancelled,
        ):
            try:
                signal.disconnect()
            except RuntimeError:
                pass

        thread.cancel()
        # Keep a reference so closeEvent can join it; a QThread destroyed while
        # still running is undefined behaviour. Earlier orphans that have since
        # unwound are dropped here so repeated cancelling can't grow the list.
        self._orphaned_analysis_threads = [
            t for t in self._orphaned_analysis_threads if t.isRunning()
        ]
        self._orphaned_analysis_threads.append(thread)
        self._analysis_thread = None
        self._on_analysis_cancelled()

    def _on_analysis_started(self) -> None:
        """Handle analysis started."""
        self._analysis_panel.progress_panel.set_status(self.tr("Analyzing..."))

    def _on_analysis_progress(self, progress: AnalysisProgress) -> None:
        """Handle analysis progress update."""
        self._analysis_panel.progress_panel.set_progress(progress.completed, progress.total)
        self._analysis_panel.progress_panel.set_current_file(progress.current_file)

        if progress.result:
            self._update_track_from_result(progress.result)
        else:
            # No result yet means this file is just starting. TrackState.ANALYSING
            # was styled, filtered and counted everywhere but never actually
            # assigned, so the Status column sat on "Pending" for the whole run
            # and nothing showed which file was being worked on.
            track = self._store.get_by_path(progress.current_file)
            if track is not None and track.state == TrackState.PENDING:
                self._store.update(track.id, state=TrackState.ANALYSING)

    def _on_analysis_finished(self, results: list[AnalysisResult]) -> None:
        """Handle analysis finished."""
        # Process any results not already handled via progress signals
        for result in results:
            track = self._store.get_by_path(result.file_path)
            if track and track.state not in (TrackState.ANALYSED, TrackState.ERROR):
                self._update_track_from_result(result)

        # Update progress panel
        success_count = len([r for r in results if not r.error])
        error_count = len([r for r in results if r.error])

        if error_count > 0:
            self._analysis_panel.progress_panel.complete(
                self.tr("Complete: {0} analyzed, {1} errors").format(success_count, error_count)
            )
        else:
            self._analysis_panel.progress_panel.complete(
                self.tr("Complete: {0} files analyzed").format(success_count)
            )

        # Refresh the analysis table
        self._analysis_panel.refresh_table()

        # Clean up
        self._analyzing_track_ids = []
        self._analysis_thread = None
        # Re-enable the manual Analyze button (re-armed here; if auto-mode
        # chaining kicks off a new batch below it flips back on). Same for the
        # sidebar spinner — _start_pending_analysis restarts it in place, and
        # the frame counter carries across so the glyph doesn't visibly jump.
        self._analysis_panel.set_analyzing(False)
        self._sidebar.set_page_busy("analysis", False)

        # Auto-rename pipeline: only for tracks just analyzed in this batch
        if (
            self._pending_rename_operations is not None
            and self._config.auto_rename
            and not self._analysis_writes_frozen
        ):
            self._auto_rename_after_analysis(results)
        self._pending_rename_operations = None

        # Pick up anything dropped into the panel while this batch was running.
        self._start_pending_analysis()

    def _start_pending_analysis(self) -> None:
        """Analyze tracks that were enqueued while a previous batch was running.

        Files dropped into (or sent to) the Analyze panel during an active
        auto-analysis are marked PENDING rather than rejected; once the running
        batch finishes we start a fresh batch for whatever is still waiting so
        each track is analyzed when its turn comes.
        """
        if not self._config.auto_analyze:
            return
        if self._analysis_thread is not None and self._analysis_thread.isRunning():
            return
        pending_ids = [t.id for t in self._store.get_by_state(TrackState.PENDING)]
        if pending_ids:
            self._pending_rename_operations = []  # enable auto-rename gate
            self._start_analysis(pending_ids)

    def _on_analysis_cancelled(self) -> None:
        """Handle analysis cancelled.

        A cancel stops the *remaining* work; it does not undo what already
        finished. Files analysed before the cancel have had their tags written
        by _update_track_from_result already, so they must also go through
        auto-rename — otherwise cancelling left them tagged with BPM and key
        but still under their original filename, which is a half-applied result
        the user never asked for.
        """
        self._analysis_panel.progress_panel.cancelled()

        batch = [
            track
            for track in (self._store.get(tid) for tid in self._analyzing_track_ids)
            if track is not None
        ]
        completed = [t for t in batch if t.state == TrackState.ANALYSED]

        # Whatever never ran stays PENDING — it is still queued in the Analyze
        # panel and has to stay visible there. Resetting it to QUEUED (as this
        # used to) made the tracks vanish from the panel mid-batch: QUEUED is
        # the *Rename* panel's working set, and the Analyze table filters it
        # out, so a cancelled batch silently emptied the list it was shown in.
        for track in batch:
            if track.state == TrackState.ANALYSING:
                self._store.update(track.id, state=TrackState.PENDING)

        self._analyzing_track_ids = []
        self._analysis_thread = None
        self._analysis_panel.set_analyzing(False)
        self._sidebar.set_page_busy("analysis", False)
        self._analysis_panel.refresh_table()

        # Same auto-rename gate as the finished path, over just what completed
        # — including the write-freeze, since a cancel's follow-through writes
        # to disk exactly like a normal finish does.
        if (
            completed
            and self._pending_rename_operations is not None
            and self._config.auto_rename
            and not self._analysis_writes_frozen
        ):
            self._auto_rename_after_analysis(
                [AnalysisResult(
                    file_path=t.file_path,
                    bpm=t.bpm or 0.0,
                    bpm_confidence=t.bpm_confidence or 0.0,
                    key=t.key or "",
                    key_confidence=t.key_confidence or 0.0,
                    keycode=t.keycode or "",
                ) for t in completed]
            )
        self._pending_rename_operations = None

    def _auto_rename_after_analysis(self, current_results: list[AnalysisResult]) -> None:
        """Build rename previews for the current analysis batch and start rename thread."""
        # Only rename tracks from this batch, not all previously-analyzed tracks
        successful_paths = {r.file_path for r in current_results if not r.error}
        all_analysed = self._store.get_by_state(TrackState.ANALYSED)
        analysed_tracks = [t for t in all_analysed if t.file_path in successful_paths]
        if not analysed_tracks:
            return

        analysis_dict = {
            t.file_path: AnalysisResult(
                file_path=t.file_path,
                bpm=t.bpm or 0.0,
                bpm_confidence=t.bpm_confidence or 0.0,
                key=t.key or "",
                key_confidence=t.key_confidence or 0.0,
                keycode=t.keycode or "",
            )
            for t in analysed_tracks
        }

        # Apply per-track: user ops + auto BPM/Key prefix or suffix
        all_previews: list[RenamePreview] = []
        for track in analysed_tracks:
            bpm_str = f"{round(track.bpm)}" if track.bpm else "0"
            key_str = render_key(track.key or "", track.keycode or "", self._config.key_notation)
            auto_op = self._build_analysis_rename_op(bpm_str, key_str, self._config.naming_preference)
            ops = list(self._pending_rename_operations) + [auto_op]
            track_previews = preview_rename([track.file_path], ops, analysis_dict)
            all_previews.extend(track_previews)

        if not all_previews or has_conflicts(all_previews):
            return
        if not has_changes(all_previews):
            return

        self._start_rename(all_previews, [])

    @staticmethod
    def _build_analysis_rename_op(bpm_str: str, keycode_str: str, pref: str) -> RenameOperation:
        """Return the appropriate rename operation for the naming preference."""
        match pref:
            case "tempo_key_prefix":
                text = f"{bpm_str} {keycode_str} - " if keycode_str else f"{bpm_str} - "
                return AddPrefix(text)
            case "key_tempo_prefix":
                text = f"{keycode_str} {bpm_str} - " if keycode_str else f"{bpm_str} - "
                return AddPrefix(text)
            case "key_prefix":
                text = f"{keycode_str} - " if keycode_str else f"{bpm_str} - "
                return AddPrefix(text)
            case "suffix_key_tempo":
                text = f" - {keycode_str} {bpm_str}" if keycode_str else f" - {bpm_str}"
                return AddSuffix(text)
            case "suffix_key":
                text = f" - {keycode_str}" if keycode_str else f" - {bpm_str}"
                return AddSuffix(text)
            case _:
                text = f"{bpm_str} {keycode_str} - " if keycode_str else f"{bpm_str} - "
                return AddPrefix(text)

    # Conversion operations

    def _start_conversion(
        self,
        file_paths: list[str],
        target_format: str,
        bitrate: int = 320,
        sample_rate: int | None = 44100,
        bit_depth: int | None = 16,
        output_dir: str = "",
    ) -> None:
        """Start the conversion operation.

        sample_rate / bit_depth are None for "Keep source", which the engine
        reads as "leave this axis alone" — don't coerce them to a number.
        output_dir is "" for "beside each source file", which the engine spells
        None; the panel has already checked the folder is writable.
        """
        if self._conversion_thread is not None and self._conversion_thread.isRunning():
            QMessageBox.warning(
                self,
                self.tr("Conversion in Progress"),
                self.tr("A conversion is already running. Please wait."),
            )
            return

        if not file_paths:
            return

        # Start progress
        self._conversion_panel.progress_panel.start(len(file_paths))
        # Flag every queued row "Converting" up front; each flips to Done as
        # its per-file progress event arrives.
        self._conversion_panel.mark_converting(file_paths)

        # Create and start conversion thread
        self._conversion_thread = ConversionThread(
            file_paths,
            target_format,
            bitrate,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            output_dir=output_dir or None,
            parent=self,
        )
        self._conversion_thread.conversion_started.connect(self._on_conversion_started)
        self._conversion_thread.conversion_progress.connect(self._on_conversion_progress)
        self._conversion_thread.conversion_finished.connect(self._on_conversion_finished)
        self._conversion_thread.conversion_error.connect(self._on_conversion_error)
        self._conversion_thread.conversion_cancelled.connect(self._on_conversion_cancelled)
        self._conversion_thread.start()
        self._sidebar.set_page_busy("convert", True)

    def _cancel_conversion(self) -> None:
        """Cancel the current conversion.

        Unlike analysis, one file's conversion is a bounded encode rather than a
        multi-second uninterruptible library call, so this waits for the worker
        to reach its own cancellation check rather than detaching from it.
        """
        if self._conversion_thread is not None and self._conversion_thread.isRunning():
            self._conversion_thread.cancel()

    def _on_conversion_cancelled(self) -> None:
        """Handle conversion cancelled."""
        self._conversion_panel.progress_panel.cancelled()
        # Empty results: rows that finished before the cancel keep their Done
        # status (they were discarded from _converting as they landed), and
        # rows still marked Converting revert to Ready.
        self._conversion_panel.mark_converted([])
        self._conversion_thread = None
        self._sidebar.set_page_busy("convert", False)

    def _on_conversion_started(self) -> None:
        """Handle conversion started."""
        self._conversion_panel.progress_panel.set_status(self.tr("Converting..."))

    def _on_conversion_progress(self, progress: ConversionProgress) -> None:
        """Handle conversion progress update."""
        self._conversion_panel.progress_panel.set_progress(progress.completed, progress.total)
        self._conversion_panel.progress_panel.set_current_file(progress.current_file)
        # Flip the just-finished file's row to Done/Error immediately.
        self._conversion_panel.mark_file_result(progress.result)

    def _on_conversion_finished(self, results: list) -> None:
        """Handle conversion finished."""
        success_count = sum(1 for r in results if not r.error and not r.skipped)
        error_count = sum(1 for r in results if r.error)

        if error_count > 0:
            self._conversion_panel.progress_panel.complete(
                self.tr("Complete: {0} converted, {1} errors").format(success_count, error_count)
            )
        else:
            self._conversion_panel.progress_panel.complete(
                self.tr("Complete: {0} files converted").format(success_count)
            )

        self._conversion_panel.mark_converted(results)
        self._conversion_thread = None
        self._sidebar.set_page_busy("convert", False)

    def _on_conversion_error(self, error: str) -> None:
        """Handle conversion error."""
        self._conversion_panel.progress_panel.set_error(error)
        self._conversion_thread = None
        self._sidebar.set_page_busy("convert", False)

    def _on_spectrum_sensitivity(self, dr: float) -> None:
        """Persist the spectrum colour sensitivity when the slider is released."""
        self._config.spectrum_dynamic_range = dr
        self._persist_config()

    def _on_history_limit_changed(self, limit: int) -> None:
        """Persist the History panel's row-count choice. The panel has already
        redrawn itself; this only records the selection for next launch."""
        self._config.history_display_limit = limit
        self._persist_config()

    def _on_auto_analyze_toggled(self, enabled: bool) -> None:
        """Handle the Analyze panel's Auto toggle: persist and sync other views.

        The Analyze panel already updated its own state; here we persist the
        change and mirror it onto the Settings checkbox and the sidebar badge so
        every view stays in agreement.
        """
        self._config.auto_analyze = enabled
        self._persist_config()
        self._settings_panel.set_auto_analyze(enabled)
        self._sidebar.set_auto_analyze_badge(enabled)

    def _on_write_freeze_toggled(self, frozen: bool) -> None:
        """Handle the Analyze panel's Freeze toggle.

        Nothing is persisted and no setting is changed: this bool is the single
        gate in front of every write the analysis flow makes to a file (BPM/key
        tags, the energy/key comment, and auto-rename on both the finished and
        the cancelled path). Manual edits in the Metadata panel and Apply in the
        Rename panel are untouched — the user clicked those.
        """
        self._analysis_writes_frozen = frozen

    def _effective_waveform_color(self) -> str:
        """The full-length waveform colour to actually paint.

        If the user has chosen a custom colour, it's respected on every theme.
        If it's still the factory default (i.e. untouched), defer to the active
        theme's own default so e.g. the light theme paints a colour that reads
        on its pale waveform background instead of the dark-theme neon yellow.
        """
        if self._config.waveform_color == AppConfig.waveform_color:
            return Theme.WAVEFORM_DEFAULT
        return self._config.waveform_color

    def _on_settings_changed(self) -> None:
        """Persist settings whenever the user changes anything in the panel."""
        self._config = self._settings_panel.get_config(self._config)
        self._persist_config()
        self._analysis_panel.set_auto_analyze(self._config.auto_analyze)
        self._analysis_panel.set_auto_write_bpm(self._config.auto_write_bpm)
        self._analysis_panel.set_auto_write_key(self._config.auto_write_key)
        self._analysis_panel.set_key_notation(self._config.key_notation)
        self._keyboard_panel.set_key_notation(self._config.key_notation)
        self._player_panel.set_key_notation(self._config.key_notation)
        self._player_panel.set_waveform_color(self._effective_waveform_color())
        self._player_panel.set_text_size(self._config.player_text_size)
        self._player_panel.set_artwork_view(self._config.player_artwork_view)
        self._apply_visualization_settings()
        self._sidebar.set_auto_analyze_badge(self._config.auto_analyze)

    def _apply_visualization_settings(self) -> None:
        """Push the visualizations switch (and waveform color) to every consumer.

        The Player shows/hides its visuals dropdown based on the switch. The
        Analyze and Convert progress panels always show their moving waveform
        (it's core progress feedback, not an opt-in visual), so the switch
        doesn't gate them — only the waveform colour is pushed. Rename shares the
        same ProgressPanel widget but is intentionally left plain.
        """
        enabled = self._config.visualizations_enabled
        color = self._effective_waveform_color()
        self._player_panel.set_visualizations_enabled(enabled)
        for panel in (self._analysis_panel, self._conversion_panel):
            panel.progress_panel.set_activity_color(color)

    def _update_track_from_result(self, result: AnalysisResult) -> None:
        """Update a track with analysis results."""
        track = self._store.get_by_path(result.file_path)
        if track is None:
            return

        if result.error:
            self._store.update(
                track.id,
                state=TrackState.ERROR,
                error_message=result.error,
            )
        else:
            self._store.update(
                track.id,
                state=TrackState.ANALYSED,
                bpm=result.bpm,
                bpm_confidence=result.bpm_confidence,
                key=result.key,
                key_confidence=result.key_confidence,
                keycode=result.keycode,
                key_alternatives=result.key_alternatives,
                energy=result.energy,
            )

            # Record in the persistent analysis history (best-effort)
            try:
                from datetime import datetime

                analysis_history.add_entry({
                    "file_path": result.file_path,
                    "timestamp": datetime.now().isoformat(),
                    "bpm": result.bpm,
                    "bpm_confidence": result.bpm_confidence,
                    "key": result.key,
                    "key_confidence": result.key_confidence,
                    "keycode": result.keycode,
                    "key_alternatives": result.key_alternatives,
                    "energy": result.energy,
                })
            except Exception as e:
                logger.warning(f"Failed to record analysis history: {e}")

            # Session write-freeze (the Analyze panel's Freeze toggle): hold
            # every file-touching side effect of analysis. Everything above
            # still happens — the track row, the results table and the history
            # JSON are not writes to the user's files. Everything below this
            # point is, so the freeze is one gate here.
            if self._analysis_writes_frozen:
                return

            # Auto-write metadata — BPM and key are independently toggleable.
            # Skipped outright for a format with nowhere to put them: the write
            # otherwise reports success while discarding the value, which logged
            # a run of "Failed to set bpm tag" warnings for a file that was
            # never going to keep them. The Analyze panel flags such rows.
            write_bpm = self._analysis_panel.auto_write_bpm
            write_key = self._analysis_panel.auto_write_key
            if not stores_tags(result.file_path):
                write_bpm = write_key = False
            if write_bpm or write_key:
                try:
                    bpm_value = result.bpm if write_bpm else None
                    key_value = (
                        render_key(result.key or "", result.keycode or "", self._config.key_notation)
                        if write_key else None
                    )
                    logger.info(f"Writing metadata: BPM={bpm_value}, Key={key_value} to {Path(result.file_path).name}")
                    success = update_bpm_key(result.file_path, bpm=bpm_value, key=key_value)
                    if success:
                        logger.info(f"Metadata written successfully to {Path(result.file_path).name}")
                    else:
                        logger.warning(f"Metadata write returned False for {Path(result.file_path).name}")
                except Exception as e:
                    logger.error(f"Failed to write metadata to {Path(result.file_path).name}: {e}")
                    logger.error(f"Error type: {type(e).__name__}")
                    import traceback
                    logger.debug(traceback.format_exc())

            # Write energy and/or key to comment tag based on independent
            # settings — skipped for the same reason as the BPM/key write above.
            energy_on = (
                self._config.energy_tag_enabled
                and result.energy is not None
                and stores_tags(result.file_path)
            )
            key_on = (
                self._config.key_in_comment_enabled
                and (result.key or result.keycode)
                and stores_tags(result.file_path)
            )
            if energy_on or key_on:
                try:
                    key_value = None
                    if key_on:
                        key_value = render_key(result.key or "", result.keycode or "", self._config.key_notation)
                    logger.info(
                        f"Writing comment tag (key={key_value}, energy={result.energy if energy_on else None}) "
                        f"to {Path(result.file_path).name}"
                    )
                    update_comment_with_energy(
                        result.file_path,
                        energy=result.energy if energy_on else None,
                        fmt=self._config.energy_tag_format,
                        mode=self._config.energy_tag_mode,
                        key=key_value,
                        energy_written_first=self._config.energy_written_first,
                    )
                except Exception as e:
                    logger.error(f"Failed to write comment tag to {Path(result.file_path).name}: {e}")

            # The energy's own field, independent of the comment above and of
            # its format settings — this one is never parsed back out of prose,
            # which is the whole reason it exists.
            if (
                self._config.energy_field_enabled
                and result.energy is not None
                and stores_tags(result.file_path)
            ):
                try:
                    write_energy(result.file_path, result.energy)
                except Exception as e:
                    logger.error(
                        f"Failed to write energy field to {Path(result.file_path).name}: {e}"
                    )

    # Rename operations

    def _start_rename(self, previews: list[RenamePreview], operations: list[RenameOperation]) -> None:
        """Start the rename operation."""
        if self._rename_thread is not None and self._rename_thread.isRunning():
            QMessageBox.warning(
                self,
                self.tr("Rename in Progress"),
                self.tr("A rename operation is already running."),
            )
            return

        # Count actual renames
        rename_count = len([p for p in previews if p.original_name != p.new_name and not p.will_conflict])
        if rename_count == 0:
            return

        # Rename is near-instant, so there's no progress bar: completed rows
        # are highlighted with a green tint + "Changed" pill by the panel once
        # _on_rename_finished lands (see RenamePanel.mark_renamed).
        self._rename_thread = RenameThread(previews, operations, parent=self)
        self._rename_thread.rename_finished.connect(self._on_rename_finished)
        self._rename_thread.rename_error.connect(self._on_rename_error)
        self._rename_thread.start()

    def _on_rename_finished(self, session: RenameSession) -> None:
        """Handle rename finished."""
        self._last_session = session
        self._rename_panel.set_undo_enabled(True)

        # Update track paths in store
        for record in session.records:
            track = self._store.get_by_path(record.original_path)
            if track:
                new_name = Path(record.new_path).name
                self._store.update(
                    track.id,
                    file_path=record.new_path,
                    display_name=new_name,
                )

        # Keep analysis history pointing at the renamed files (best-effort)
        try:
            analysis_history.update_paths(
                [(r.original_path, r.new_path) for r in session.records]
            )
        except Exception as e:
            logger.warning(f"Failed to update analysis history paths: {e}")

        # Keep saved playlists pointing at the renamed files (best-effort;
        # no-op until the user has a playlist library)
        try:
            library.update_paths(
                [(r.original_path, r.new_path) for r in session.records]
            )
        except Exception as e:
            logger.warning(f"Failed to update library paths: {e}")

        # Refresh preview (paths updated in store), then mark renamed rows
        self._rename_panel.refresh()
        self._rename_panel.mark_renamed(session)
        self._rename_panel._clear_operations()
        self._rename_thread = None

    def _on_rename_error(self, error: str) -> None:
        """Handle rename error."""
        QMessageBox.critical(self, self.tr("Rename Failed"), error)
        self._rename_thread = None

    def _undo_last_rename(self) -> None:
        """Undo the last rename operation."""
        if self._last_session is None:
            QMessageBox.warning(self, self.tr("No Session"), self.tr("No rename session to undo."))
            return

        if self._undo_thread is not None and self._undo_thread.isRunning():
            return

        # Confirm undo
        reply = QMessageBox.question(
            self,
            self.tr("Confirm Undo"),
            self.tr("Undo renaming of {0} files?").format(self._last_session.file_count),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Start undo (near-instant, no progress bar — see _start_rename).
        self._undo_thread = UndoThread(self._last_session, parent=self)
        self._undo_thread.undo_finished.connect(self._on_undo_finished)
        self._undo_thread.undo_error.connect(self._on_undo_error)
        self._undo_thread.start()

    def _on_undo_finished(self, success_count: int, error_count: int) -> None:
        """Handle undo finished."""
        if error_count > 0:
            QMessageBox.warning(
                self,
                self.tr("Undo Rename"),
                self.tr("Undone: {0} files, {1} errors").format(success_count, error_count),
            )

        # Update track paths in store
        if self._last_session:
            for record in self._last_session.records:
                track = self._store.get_by_path(record.new_path)
                if track:
                    original_name = Path(record.original_path).name
                    self._store.update(
                        track.id,
                        file_path=record.original_path,
                        display_name=original_name,
                    )

            # Point saved playlists back at the restored names (best-effort)
            try:
                library.update_paths(
                    [(r.new_path, r.original_path) for r in self._last_session.records]
                )
            except Exception as e:
                logger.warning(f"Failed to update library paths: {e}")

        self._last_session = None
        self._rename_panel.set_undo_enabled(False)
        self._rename_panel.refresh()
        self._undo_thread = None

    def _on_undo_error(self, error: str) -> None:
        """Handle undo error."""
        QMessageBox.critical(self, self.tr("Undo Failed"), error)
        self._undo_thread = None

    def _undo_session_from_history(self, session: RenameSession) -> None:
        """Undo a session selected from history panel."""
        self._last_session = session
        self._undo_last_rename()

    def _send_convert_to_analyze(self, file_paths: list[str]) -> None:
        """Receive files from Convert panel and start analysis."""
        self._add_and_analyze_files(file_paths)

    def _send_convert_to_rename(self, file_paths: list[str]) -> None:
        """Receive files from Convert panel into the Rename panel."""
        self._add_files_to_rename(file_paths)

    def _on_manual_analyze(self) -> None:
        """Handle manual Analyze button click — start analysis for all pending tracks."""
        pending = self._store.get_by_state(TrackState.PENDING)
        track_ids = [t.id for t in pending]
        if track_ids:
            self._pending_rename_operations = []
            self._start_analysis(track_ids)

    def _send_analyze_to_convert(self, file_paths: list[str]) -> None:
        """Receive files from Analyze panel into Convert panel."""
        self._conversion_panel.add_files(file_paths)
        self._sidebar.set_current_page("convert")
        self._on_page_changed("convert")

    def _send_rename_to_convert(self, file_paths: list[str]) -> None:
        """Receive files from Rename panel into Convert panel."""
        self._conversion_panel.add_files(file_paths)
        self._sidebar.set_current_page("convert")
        self._on_page_changed("convert")

    def _on_send_to_player(self, tracks: list[dict]) -> None:
        """Send tracks from analysis to the player panel."""
        self._player_panel.add_tracks(tracks)
        self._sidebar.set_current_page("player")
        self._on_page_changed("player")

    def _open_in_metadata_panel(self, file_path: str) -> None:
        """Load a file into the metadata panel and switch to it (from Player right-click)."""
        self._metadata_panel._load_file(file_path)
        self._sidebar.set_current_page("metadata")
        self._on_page_changed("metadata")

    def _on_about(self) -> None:
        """Show about dialog."""
        dialog = AboutDialog(self)
        dialog.show()

    def showEvent(self, event) -> None:
        """Restore saved geometry and per-panel sizing on first show."""
        super().showEvent(event)
        if not self._geometry_restored:
            self._geometry_restored = True
            self._sizer.restore_on_startup()

    def resizeEvent(self, event) -> None:
        """Drive width-based responsive reflow (sidebar collapse, desc wrap)."""
        super().resizeEvent(event)
        if self._geometry_restored:
            self._sizer.on_resize()

    def _persist_config(self) -> None:
        """Save this window's config snapshot without clobbering fields that
        other panels persist independently.

        ``self._config`` is loaded once at startup and is the source of truth
        for window/settings fields, but the Convert and Player panels write
        their own fields straight to disk as the user changes them. Re-read
        those from the latest on-disk config before saving so a wholesale write
        here (e.g. on close) doesn't revert them to stale startup values.
        """
        disk = load_config()
        self._config.convert_target_format = disk.convert_target_format
        self._config.convert_mp3_bitrate = disk.convert_mp3_bitrate
        self._config.convert_sample_rate = disk.convert_sample_rate
        self._config.convert_bit_depth = disk.convert_bit_depth
        # These two are one value in two fields and must always be copied
        # together: the folder is remembered even while the Source toggle is
        # on, so carrying one across without the other resurrects a stale
        # destination — or silently drops the folder the user meant to keep.
        self._config.convert_output_dir = disk.convert_output_dir
        self._config.convert_use_source_dir = disk.convert_use_source_dir
        self._config.player_edit_locked = disk.player_edit_locked
        # These three are one value in three fields and must always be copied
        # together: the count says how many sections the state describes (a
        # state carried across with a stale count is read next launch as
        # covering the wrong columns), and the version says which generation of
        # the shipped defaults it sits on top of — reverted to the startup
        # value, the one-time layout migration would run again on every launch,
        # discarding the layout of the session that just ended.
        self._config.player_column_state = disk.player_column_state
        self._config.player_column_count = disk.player_column_count
        self._config.player_column_defaults_version = disk.player_column_defaults_version
        self._config.visualization_mode = disk.visualization_mode
        save_config(self._config)

    def closeEvent(self, event) -> None:
        """Handle window close event."""
        # Persist the window geometry (non-keyboard) for next launch.
        self._sizer.save_geometry()
        self._persist_config()

        # Stop media players
        self._player_panel.stop_playback()
        self._keyboard_panel.stop_audio()

        # ...and the threads still *reading* files. Stopping playback does not
        # stop a decode or a render in flight, and a QThread destroyed while
        # running is undefined behaviour (plus, on Windows, an open handle on a
        # file the user may be about to rename).
        self._player_panel.shutdown_workers()
        self._spectrum_panel.shutdown_workers()

        # Cancel any running analysis — including runs the user already
        # cancelled, which are detached from the UI but may still be inside the
        # HPSS call they were cancelled during.
        for thread in [self._analysis_thread, *self._orphaned_analysis_threads]:
            if thread is not None and thread.isRunning():
                thread.cancel()
                thread.wait(_ANALYSIS_JOIN_MS)
        self._orphaned_analysis_threads.clear()

        # Cancel and wait for conversion thread
        if self._conversion_thread is not None and self._conversion_thread.isRunning():
            self._conversion_thread.cancel()
            self._conversion_thread.wait(3000)

        # Wait for rename threads
        if self._rename_thread is not None and self._rename_thread.isRunning():
            self._rename_thread.wait(3000)

        if self._undo_thread is not None and self._undo_thread.isRunning():
            self._undo_thread.wait(3000)

        event.accept()
