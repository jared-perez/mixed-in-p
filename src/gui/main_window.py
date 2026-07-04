"""Main application window."""

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

from src.analysis.keycode import render_key
from src.analysis.result import AnalysisResult
from src.metadata import update_bpm_key, update_comment_with_energy
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

from src.utils.config import AppConfig, load_config, save_config

from .models import TrackState, TrackStore
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
from .widgets.rename_panel import RenamePanel
from .widgets.settings_panel import SettingsPanel
from .widgets.sidebar import Sidebar
from .widgets.spectrum_panel import SpectrumPanel
from .workers import (
    AnalysisProgress,
    AnalysisThread,
    ConversionProgress,
    ConversionThread,
    RenameProgress,
    RenameThread,
    UndoThread,
)


class MainWindow(QMainWindow):
    """Main application window for Mixed in P."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(self.tr("Mixed in P"))

        # Create track store
        self._store = TrackStore(self)

        # Analysis thread reference
        self._analysis_thread: AnalysisThread | None = None
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

        # Load persisted config
        self._config: AppConfig = load_config()

        self._setup_ui()
        # Coordinates per-panel minimum sizes, the keyboard resize-to-fit,
        # geometry persistence, and responsive reflow. Applied for real on the
        # first showEvent (so it measures a laid-out sidebar).
        self._sizer = WindowSizer(self)
        self._geometry_restored = False
        self._connect_signals()
        self._analysis_panel.set_auto_analyze(self._config.auto_analyze)
        self._analysis_panel.set_auto_write_bpm(self._config.auto_write_bpm)
        self._analysis_panel.set_auto_write_key(self._config.auto_write_key)
        self._keyboard_panel.set_key_notation(self._config.key_notation)
        self._player_panel.set_waveform_color(self._effective_waveform_color())
        self._apply_visualization_settings()
        self._sidebar.set_auto_analyze_badge(self._config.auto_analyze)
        self._spectrum_panel.set_dynamic_range(self._config.spectrum_dynamic_range)
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

        # Content area (horizontal: sidebar + pages)
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Sidebar
        self._sidebar = Sidebar()
        content_layout.addWidget(self._sidebar)

        # Stacked widget for pages. CurrentPageStack reports only the active
        # page's size hints so a hidden large panel (the keyboard) can't inflate
        # the window minimum on every other page.
        self._pages = CurrentPageStack()
        content_layout.addWidget(self._pages)

        main_layout.addWidget(content_widget)

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

        # Sidebar signals
        self._sidebar.page_changed.connect(self._on_page_changed)
        self._sidebar.files_dropped_on_page.connect(self._on_sidebar_drop)

        # Rename panel signals (file drop + full pipeline)
        self._rename_panel.files_dropped.connect(self._add_files)
        self._rename_panel.analyze_and_rename.connect(self._analyze_and_rename_files)

        # Conversion panel signals
        self._conversion_panel.start_conversion.connect(self._start_conversion)
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

        # Rename panel signals
        self._rename_panel.apply_rename.connect(self._start_rename)
        self._rename_panel.undo_last.connect(self._undo_last_rename)
        self._rename_panel.send_to_convert.connect(self._send_rename_to_convert)

        # History panel signals
        self._history_panel.undo_session.connect(self._undo_session_from_history)

        # Player panel signals
        self._player_panel.files_dropped.connect(self._add_files_to_player)
        self._player_panel.open_in_metadata.connect(self._open_in_metadata_panel)
        self._player_panel.slice_expanded.connect(self._sizer.on_slicer_expanded)

        # Spectrum panel signals
        self._spectrum_panel.files_dropped.connect(self._add_files)
        self._spectrum_panel.sensitivity_changed.connect(self._on_spectrum_sensitivity)

        # Settings panel signals
        self._settings_panel.settings_changed.connect(self._on_settings_changed)

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

        # Apply the panel's window minimum (and keyboard resize-to-fit). Done
        # after the page is current so size hints reflect the new panel.
        if self._geometry_restored:
            self._sizer.on_page_changed(page_id)

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

    def _add_files_to_player(self, file_paths: list[str]) -> None:
        """Add files directly to the player panel, reading metadata from tags."""
        from src.metadata.tags import read_metadata

        tracks = []
        for p in file_paths:
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
                if meta.bpm:
                    track["bpm"] = f"{meta.bpm:.1f}"
                if meta.key:
                    track["key"] = meta.key
                if meta.comment:
                    track["comment"] = meta.comment
                if meta.year:
                    track["year"] = str(meta.year)
                if meta.duration and meta.duration > 0:
                    track["duration"] = meta.duration
            except Exception:
                pass  # proceed without metadata
            tracks.append(track)
        self._player_panel.add_tracks(tracks)

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
            QMessageBox.warning(
                self,
                self.tr("Analysis in Progress"),
                self.tr("An analysis is already running. Please wait or cancel it first."),
            )
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

    def _analyze_and_rename_files(
        self, track_ids: list[str], operations: list[RenameOperation]
    ) -> None:
        """Start the full pipeline: analyze → metadata → auto-rename."""
        self._pending_rename_operations = operations
        self._start_analysis(track_ids)

    def _cancel_analysis(self) -> None:
        """Cancel the current analysis."""
        if self._analysis_thread is not None and self._analysis_thread.isRunning():
            self._analysis_thread.cancel()

    def _on_analysis_started(self) -> None:
        """Handle analysis started."""
        self._analysis_panel.progress_panel.set_status(self.tr("Analyzing..."))

    def _on_analysis_progress(self, progress: AnalysisProgress) -> None:
        """Handle analysis progress update."""
        self._analysis_panel.progress_panel.set_progress(progress.completed, progress.total)
        self._analysis_panel.progress_panel.set_current_file(progress.current_file)

        # Update track state if we have a result
        if progress.result:
            self._update_track_from_result(progress.result)

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

        # Auto-rename pipeline: only for tracks just analyzed in this batch
        if self._pending_rename_operations is not None and self._config.auto_rename:
            self._auto_rename_after_analysis(results)
        self._pending_rename_operations = None

    def _on_analysis_cancelled(self) -> None:
        """Handle analysis cancelled."""
        self._analysis_panel.progress_panel.set_error(self.tr("Cancelled"))

        # Reset pending tracks back to queued
        for track_id in self._analyzing_track_ids:
            track = self._store.get(track_id)
            if track and track.state in (TrackState.PENDING, TrackState.ANALYSING):
                self._store.update(track_id, state=TrackState.QUEUED)

        self._analyzing_track_ids = []
        self._analysis_thread = None

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
        sample_rate: int = 44100,
        bit_depth: int = 16,
    ) -> None:
        """Start the conversion operation."""
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
            parent=self,
        )
        self._conversion_thread.conversion_started.connect(self._on_conversion_started)
        self._conversion_thread.conversion_progress.connect(self._on_conversion_progress)
        self._conversion_thread.conversion_finished.connect(self._on_conversion_finished)
        self._conversion_thread.conversion_error.connect(self._on_conversion_error)
        self._conversion_thread.start()

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

    def _on_conversion_error(self, error: str) -> None:
        """Handle conversion error."""
        self._conversion_panel.progress_panel.set_error(error)
        self._conversion_thread = None

    def _on_spectrum_sensitivity(self, dr: float) -> None:
        """Persist the spectrum colour sensitivity when the slider is released."""
        self._config.spectrum_dynamic_range = dr
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
        self._keyboard_panel.set_key_notation(self._config.key_notation)
        self._player_panel.set_waveform_color(self._effective_waveform_color())
        self._apply_visualization_settings()
        self._sidebar.set_auto_analyze_badge(self._config.auto_analyze)

    def _apply_visualization_settings(self) -> None:
        """Push the visualizations switch (and waveform color) to every consumer.

        The Player shows/hides its visuals dropdown; the Analyze and Convert
        progress panels gate their animated activity waveform. Rename shares
        the same ProgressPanel widget but is intentionally left plain.
        """
        enabled = self._config.visualizations_enabled
        color = self._effective_waveform_color()
        self._player_panel.set_visualizations_enabled(enabled)
        for panel in (self._analysis_panel, self._conversion_panel):
            panel.progress_panel.set_activity_enabled(enabled)
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
                energy=result.energy,
            )

            # Auto-write metadata — BPM and key are independently toggleable.
            write_bpm = self._analysis_panel.auto_write_bpm
            write_key = self._analysis_panel.auto_write_key
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

            # Write energy and/or key to comment tag based on independent settings
            energy_on = self._config.energy_tag_enabled and result.energy is not None
            key_on = self._config.key_in_comment_enabled and (result.key or result.keycode)
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

        # Start progress
        self._rename_panel.progress_panel.start(rename_count)

        # Create and start rename thread
        self._rename_thread = RenameThread(previews, operations, parent=self)
        self._rename_thread.rename_started.connect(self._on_rename_started)
        self._rename_thread.rename_progress.connect(self._on_rename_progress)
        self._rename_thread.rename_finished.connect(self._on_rename_finished)
        self._rename_thread.rename_error.connect(self._on_rename_error)
        self._rename_thread.start()

    def _on_rename_started(self) -> None:
        """Handle rename started."""
        self._rename_panel.progress_panel.set_status(self.tr("Renaming files..."))

    def _on_rename_progress(self, progress: RenameProgress) -> None:
        """Handle rename progress."""
        self._rename_panel.progress_panel.set_progress(progress.completed, progress.total)
        self._rename_panel.progress_panel.set_current_file(progress.current_file)

    def _on_rename_finished(self, session: RenameSession) -> None:
        """Handle rename finished."""
        self._last_session = session
        self._rename_panel.set_undo_enabled(True)
        self._rename_panel.progress_panel.complete(
            self.tr("Renamed {0} files").format(session.file_count)
        )

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

        # Refresh preview (paths updated in store), then mark renamed rows
        self._rename_panel.refresh()
        self._rename_panel.mark_renamed(session)
        self._rename_panel._clear_operations()
        self._rename_thread = None

    def _on_rename_error(self, error: str) -> None:
        """Handle rename error."""
        self._rename_panel.progress_panel.set_error(error)
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

        # Start undo
        self._rename_panel.progress_panel.start(self._last_session.file_count)
        self._rename_panel.progress_panel.set_status(self.tr("Undoing rename..."))

        self._undo_thread = UndoThread(self._last_session, parent=self)
        self._undo_thread.undo_progress.connect(self._on_undo_progress)
        self._undo_thread.undo_finished.connect(self._on_undo_finished)
        self._undo_thread.undo_error.connect(self._on_undo_error)
        self._undo_thread.start()

    def _on_undo_progress(self, progress: RenameProgress) -> None:
        """Handle undo progress."""
        self._rename_panel.progress_panel.set_progress(progress.completed, progress.total)
        self._rename_panel.progress_panel.set_current_file(progress.current_file)

    def _on_undo_finished(self, success_count: int, error_count: int) -> None:
        """Handle undo finished."""
        if error_count > 0:
            self._rename_panel.progress_panel.complete(
                self.tr("Undone: {0} files, {1} errors").format(success_count, error_count)
            )
        else:
            self._rename_panel.progress_panel.complete(
                self.tr("Undone {0} files").format(success_count)
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

        self._last_session = None
        self._rename_panel.set_undo_enabled(False)
        self._rename_panel.refresh()
        self._undo_thread = None

    def _on_undo_error(self, error: str) -> None:
        """Handle undo error."""
        self._rename_panel.progress_panel.set_error(error)
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
        self._config.player_edit_locked = disk.player_edit_locked
        self._config.player_column_state = disk.player_column_state
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

        # Cancel any running analysis
        if self._analysis_thread is not None and self._analysis_thread.isRunning():
            self._analysis_thread.cancel()
            self._analysis_thread.wait(3000)

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
