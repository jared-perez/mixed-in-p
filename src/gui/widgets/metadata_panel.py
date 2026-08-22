"""Metadata editor panel — drop a single audio file, view/edit tags inline."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QT_TRANSLATE_NOOP, Qt, QUrl, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtGui import (
    QDesktopServices,
    QFontMetrics,
    QGuiApplication,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
)

from src.metadata.tags import (
    TrackMetadata,
    read_metadata,
    write_metadata,
    write_comment,
    delete_metadata_fields,
)
from src.online import discogs
from src.online.discogs import RELEASE_PAGE, DiscogsProvider
from src.utils.paths import normalize_track_path
from src.utils.reveal import reveal_in_file_manager
from .. import lookup_flow
from ..lookup_flow import ARTWORK_FIELD
from ..styles.theme import BackgroundOverlay, Theme, panel_header_row
from ..workers import thread_keeper
from src.online.result import Candidate
from ..workers.lookup_worker import LookupJob, LookupThread
from .dialogs.lookup_review import LookupReviewDialog
from .elided_label import ElidedLabel, HuggingElidedLabel, LinkLabel
from .artwork_widget import ArtworkWidget, mime_for_path
from .drop_zone import AUDIO_EXTENSIONS

logger = logging.getLogger(__name__)

# Horizontal room a button needs beyond its text: the stylesheet's
# "padding: 8px 16px", its 1px border, and a little slack. The stylesheet is
# invisible to the native size hint, so a translated label would otherwise be
# cut at both ends — a QPushButton centres rather than elides.
# (Plain "#", not "#:" — lupdate harvests the latter as a note to translators.)
_BUTTON_CHROME = 44

# Fields displayed in the editor and their display labels.
# Labels are marked for translation extraction here (QT_TRANSLATE_NOOP returns
# the string unchanged); they are translated at display time via self.tr(label).
FIELD_ORDER = [
    ("title", QT_TRANSLATE_NOOP("MetadataPanel", "Title")),
    ("artist", QT_TRANSLATE_NOOP("MetadataPanel", "Artist")),
    ("album", QT_TRANSLATE_NOOP("MetadataPanel", "Album")),
    ("label", QT_TRANSLATE_NOOP("MetadataPanel", "Label")),
    ("genre", QT_TRANSLATE_NOOP("MetadataPanel", "Genre")),
    ("bpm", QT_TRANSLATE_NOOP("MetadataPanel", "BPM")),
    ("key", QT_TRANSLATE_NOOP("MetadataPanel", "Key")),
    ("year", QT_TRANSLATE_NOOP("MetadataPanel", "Year")),
    ("track_number", QT_TRANSLATE_NOOP("MetadataPanel", "Track #")),
    ("comment", QT_TRANSLATE_NOOP("MetadataPanel", "Comment")),
]

FIELD_LABELS = dict(FIELD_ORDER)

# Left margin applied to the form rows. A small indent keeps labels visually
# tucked in slightly while still extending the field column nearly to the artwork.
_FORM_LEFT_MARGIN = 8

# How wide the cover column is. A constant is safe here where it would not be
# for a text column: nothing in it is translated prose — the one string that
# lives there, the empty-state hint, wraps rather than clips (see
# ArtworkWidget). Sized for the cover itself plus a 4px margin.
_ART_COLUMN_WIDTH = 150

# Discogs tab spacing. Bigger than the tag form's on purpose: that is a column
# of edit boxes whose borders already separate the rows, and this is plain text
# where the only thing telling one fact from the next is the gap.
_SECTION_GAP = 14        # between one headed block and the next
_ROW_GAP = 7             # between rows inside a block
_SECTION_LABEL_GAP = 14  # between a row's label and its value
# Room for the vertical scrollbar, so the longest value is not drawn under it.
_DISCOGS_SCROLL_GUTTER = 12
# The per-row "write this into the tags" button. Square and icon-only: a
# QPushButton centres rather than elides, so a translated word here would be
# cut at both ends before it ever clipped.
_APPLY_BUTTON_SIDE = 24


def _format_duration(seconds: float) -> str:
    """Seconds as m:ss, the way a sleeve prints a running time."""
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _format_audio_props(path: str) -> str:
    """Return a short 'Sample Rate: 44.1 kHz   Bit Depth: 16-bit' summary."""
    try:
        from mutagen import File
        audio = File(path)
        info = getattr(audio, "info", None) if audio is not None else None
        if info is None:
            return ""
        sample_rate = getattr(info, "sample_rate", None)
        bit_depth = (
            getattr(info, "bits_per_sample", None)
            or getattr(info, "sample_size", None)
        )
        sr_text = f"{sample_rate / 1000:g} kHz" if sample_rate else "—"
        bd_text = f"{int(bit_depth)}-bit" if bit_depth else "—"
        return f"Sample Rate: {sr_text}    Bit Depth: {bd_text}"
    except Exception:
        return ""


class MetadataPanel(QWidget):
    """Panel for viewing and editing audio file metadata tags."""

    files_dropped = Signal(list)
    # "Play in Player" from the path's context menu. A signal rather than a
    # reach into the player: this panel owns a file, not the transport, and
    # MainWindow is where every other cross-panel route is already wired.
    play_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._file_path: str | None = None
        self._field_edits: dict[str, QLineEdit] = {}
        self._saving = False  # guard against re-entrant saves
        # Online lookup state. Off until MainWindow pushes the setting down —
        # while off the button is hidden, not greyed, so the app looks as
        # offline as it is.
        self._online_enabled = False
        self._discogs_token = ""
        self._fetch_artwork = True
        self._lookup_thread: LookupThread | None = None
        self._review_dialog: LookupReviewDialog | None = None
        # The result the review dialog is showing, kept so an apply can say
        # which release it wrote from. Set on every result — including the one
        # a candidate switch brings back, or the link would point at the
        # release the user rejected.
        self._last_result = None
        self._release_url = ""
        # Set by MainWindow, like the Player's and the playlist tree's. The
        # panel works without one — every use is guarded — because a file
        # dropped here need not be in the library at all.
        self._library = None
        self._release_id: int | None = None
        # Section label widgets, so they can be given one shared column width.
        self._discogs_keys: list[tuple[QLabel, str]] = []
        # Set for the length of one Refresh: the same thread path serves the
        # tab and the review dialog, and this is which of them asked.
        self._tab_refresh = False
        # Its sibling for "Find Cover Online": the answer goes to a review
        # dialog like an ordinary lookup's, but one showing the sleeve alone.
        # Same reason there is one flag and not a second thread path — a
        # second one would need its own cancel, keeper and shutdown to do what
        # this one already does.
        self._artwork_lookup = False
        self._threads: list = []
        self.setAcceptDrops(True)
        self._setup_ui()
        self._bg_overlay = BackgroundOverlay("bg_metadata.png", self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._bg_overlay.setGeometry(self.rect())

    # ------------------------------------------------------------------ UI

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            Theme.PADDING, Theme.PADDING, Theme.PADDING, Theme.PADDING
        )
        layout.setSpacing(Theme.SPACING)

        # Static title — always visible, yellow like other panels. Description
        # sits on the same line, flowing to the title's right.
        title = QLabel(self.tr("Metadata Editor"))
        title.setObjectName("sectionTitle")
        title.setStyleSheet(f"font-size: 24px; color: {Theme.NEON_YELLOW};")
        # Kept on the panel so it can be taken down once its instruction has
        # been followed: "Drop a single audio file" is an empty-state prompt,
        # and leaving it over a loaded file spends the widest row in the panel
        # telling the user to do the thing they have just done.
        self._desc_label = ElidedLabel(
            self.tr("Drop a single audio file to view and edit its metadata tags.")
        )
        self._desc_label.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        layout.addLayout(panel_header_row(title, self._desc_label))

        # File header row: filename (yellow) | Sample Rate / Bit Depth (secondary)
        file_row = QHBoxLayout()
        file_row.setContentsMargins(0, 0, 0, 0)
        file_row.setSpacing(Theme.PADDING)

        # The filename can be long; let it shrink and clip at the panel edge
        # rather than forcing the window wider than the Metadata minimum. The
        # info label keeps its natural width so the props stay readable.
        self._file_label = QLabel("")
        self._file_label.setStyleSheet(
            f"color: {Theme.NEON_YELLOW}; font-size: 15px; background: transparent;"
        )
        self._file_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        file_row.addWidget(self._file_label, 1)

        self._info_label = QLabel("")
        self._info_label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: 14px; background: transparent;"
        )
        file_row.addWidget(self._info_label)

        file_row.addStretch()

        # Second line: where the file actually is. The filename above is not
        # enough to tell two copies of a track apart, and the panel writes to
        # disk — so the path is worth showing, and worth being able to open.
        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(Theme.SPACING)

        # ElidedLabel, not QLabel: a path's length is not ours to control, and
        # a QLabel simply draws past its own edge. It also manages its own
        # tooltip from here on — full text while cut off, none while it fits.
        self._path_label = ElidedLabel("")
        self._path_label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: 13px; background: transparent;"
        )
        # The path is the one place in the panel that identifies the file
        # rather than describing it, so it is where "do something with this
        # file" belongs. Split from execution for the same reason the cover's
        # menu is: QMenu.exec cannot be patched out, so a test that drove a
        # combined handler would open a real modal menu and hang the suite.
        self._path_label.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._path_label.customContextMenuRequested.connect(self._on_path_menu)
        path_row.addWidget(self._path_label, 1)

        self._reveal_btn = QPushButton(self.tr("Open File Location"))
        self._reveal_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reveal_btn.setToolTip(
            self.tr("Show this file in Finder / File Explorer.")
        )
        self._reveal_btn.setMinimumWidth(
            self._reveal_btn.fontMetrics().horizontalAdvance(self._reveal_btn.text())
            + _BUTTON_CHROME
        )
        self._reveal_btn.clicked.connect(self._on_reveal_clicked)
        path_row.addWidget(self._reveal_btn)

        header_col = QVBoxLayout()
        header_col.setContentsMargins(0, 0, 0, 0)
        # Explicit: a widget's own layout falls back to the Qt default (6px),
        # not Theme.SPACING — and these two lines are one block about one file.
        header_col.setSpacing(2)
        header_col.addLayout(file_row)
        header_col.addLayout(path_row)

        self._file_header_widget = QWidget()
        self._file_header_widget.setLayout(header_col)
        # Transparent so the panel's background shows through instead of the dark
        # #1a1a1a fill the global QWidget QSS rule would otherwise paint here.
        self._file_header_widget.setObjectName("fileHeader")
        self._file_header_widget.setStyleSheet("#fileHeader { background: transparent; }")
        self._file_header_widget.setVisible(False)
        layout.addWidget(self._file_header_widget)

        # Body: horizontal split — text fields on left (2/3), artwork on right (1/3)
        body = QHBoxLayout()
        body.setSpacing(Theme.PADDING)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._form_container = QWidget()
        self._form_layout = QFormLayout(self._form_container)
        self._form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # macOS defaults QFormLayout to FieldsStayAtSizeHint, which leaves
        # QLineEdits at their tiny preferred width. Force them to fill the column.
        self._form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._form_layout.setSpacing(10)
        self._form_layout.setContentsMargins(_FORM_LEFT_MARGIN, 10, 0, 0)
        scroll.setWidget(self._form_container)
        self._scroll_area = scroll

        # Two jobs, two pages. Editing this file's tags is one thing; reading
        # what Discogs knows about the release is another, and bolting ten
        # read-only rows onto a form whose every row is an editable field
        # would destroy the distinction. The artwork column stays OUTSIDE the
        # tabs — the cover belongs to both jobs.
        self._tabs = QTabWidget()
        self._tabs.setObjectName("metadataTabs")
        # A QTabWidget's pane is a QFrame and its pages are bare QWidgets, so
        # both hit the global rules: the QWidget background paints BG_DARK
        # over the panel, and the QFrame border draws a box nobody asked for.
        # The pane's own background and border are handled in app.qss.template,
        # NOT here: a `#objectName::pane` rule set on the widget does not beat
        # the global `QTabWidget::pane` one, measured by sampling the rendered
        # pixel. Only the pages and the tab bar are the widget's business —
        # and the bar is left-aligned because the macOS style centres it,
        # which puts two tabs in the middle of a panel whose every other row
        # starts at the left margin.
        # qt_tabwidget_stackedwidget is the container QTabWidget builds for
        # itself, and it is the documented bare-QWidget trap wearing a name Qt
        # assigned: it takes BG_MEDIUM and paints it over the panel, which
        # neither the ::pane rule nor a rule on the pages can reach. Found by
        # sampling the rendered pixel and walking the children, because the
        # Tags page happened to cover it and only the Discogs page showed it.
        self._tabs.setStyleSheet(
            "#metadataTabs::tab-bar { alignment: left; }"
            " #metadataTabs > QWidget#qt_tabwidget_stackedwidget"
            " { background-color: transparent; }"
            " #metadataTagsPage, #metadataDiscogsPage"
            " { background-color: transparent; }"
        )
        tags_page = QWidget()
        tags_page.setObjectName("metadataTagsPage")
        tags_layout = QVBoxLayout(tags_page)
        tags_layout.setContentsMargins(0, 0, 0, 0)
        # A layout handed to a widget takes the Qt style default (6px), not
        # Theme.SPACING — the form's rows shift by 2px each without this.
        tags_layout.setSpacing(Theme.SPACING)
        tags_layout.addWidget(scroll)
        # Add field belongs to the *form*, not to the panel: it puts a new row
        # in the file's tags, which is the one job the Tags page does. Sitting
        # in the shared row under the tabs it stayed on screen over the Discogs
        # page, where there is no form to add anything to — and it read as an
        # offer to add a field to the release. Inside the page it comes and
        # goes with the page, for no visibility handling of its own.
        add_field_row = QHBoxLayout()
        add_field_row.setContentsMargins(_FORM_LEFT_MARGIN, 0, 0, 0)
        add_field_row.setSpacing(Theme.SPACING)
        self._add_combo = QComboBox()
        self._add_combo.addItem(self.tr("Add field..."))
        self._add_combo.setMinimumWidth(160)
        add_field_row.addWidget(self._add_combo)
        add_field_row.addStretch()
        tags_layout.addLayout(add_field_row)
        self._tabs.addTab(tags_page, self.tr("Tags"))
        # Not translated: a provider name, like the format codes and the
        # product name. DISPLAY_NAME rather than a literal so the tab and
        # the About credit cannot drift apart.
        self._tabs.addTab(self._build_discogs_page(), discogs.DISPLAY_NAME)
        self._tabs.setVisible(False)
        body.addWidget(self._tabs, 3)

        self._artwork = ArtworkWidget()
        self._artwork.artwork_changed.connect(self._on_artwork_changed)
        self._artwork.setVisible(False)
        # A fixed column, not a quarter of the panel. At 1:3 the cover column
        # was 225px wide for a cover that never rendered above 132 — and the
        # width it was taking is exactly what the Discogs tab beside it has
        # too little of. Top-aligned so the cover sits level with the top of
        # the tabs instead of floating in the middle of a 550px column.
        self._artwork.set_column_width(_ART_COLUMN_WIDTH)
        body.addWidget(self._artwork, 0, Qt.AlignmentFlag.AlignTop)

        layout.addLayout(body, 1)

        # Add Artwork, under the artwork column. Outside the tabs because the
        # cover belongs to both jobs, unlike Add field, which is part of the
        # Tags page above. Remove used to sit beside it and now lives on the
        # cover's own context menu: a rare destructive action on one thing,
        # which is what a context menu is for, and it was the row's whole
        # width pressure — Add Artwork is a full label in every language with
        # it gone.
        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(_FORM_LEFT_MARGIN, 0, 0, 0)
        controls_row.setSpacing(Theme.SPACING)
        controls_row.addStretch()

        self._add_artwork_btn = QPushButton(self.tr("Add Artwork…"))
        self._add_artwork_btn.clicked.connect(self._on_add_artwork_clicked)
        self._add_artwork_btn.setVisible(False)
        controls_row.addWidget(self._add_artwork_btn)

        self._controls_row_widget = QWidget()
        self._controls_row_widget.setLayout(controls_row)
        self._controls_row_widget.setVisible(False)
        layout.addWidget(self._controls_row_widget)

        # A file with no artist and no title gets an empty form and, until now,
        # no hint that the one feature built for exactly that case exists.
        # `query_for`'s filename fallback was written for this file. An offer
        # and not an action: looking it up on drop would spend the user's rate
        # limit without being asked.
        self._empty_hint = ElidedLabel("")
        self._empty_hint.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        self._empty_hint.setVisible(False)
        self._empty_hint.setContentsMargins(_FORM_LEFT_MARGIN, 0, 0, 0)
        layout.addWidget(self._empty_hint)

        # Eject button row (full-width)
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(_FORM_LEFT_MARGIN, 0, 0, 0)

        # Online lookup. Hidden entirely until the setting is on — see
        # _sync_lookup_button.
        self._lookup_btn = QPushButton(self.tr("Look Up Online…"))
        self._lookup_btn.setToolTip(
            self.tr("Search Discogs for this track's details, and review them.")
        )
        self._lookup_btn.setMinimumWidth(
            self._lookup_btn.fontMetrics().horizontalAdvance(self._lookup_btn.text())
            + _BUTTON_CHROME
        )
        self._lookup_btn.clicked.connect(self._on_lookup_clicked)
        self._lookup_btn.setVisible(False)
        btn_row.addWidget(self._lookup_btn)

        # The lookup's own line: what it is doing — including *why* it paused,
        # since a rate limit that reads as a stuck spinner is the thing to
        # avoid — and, after an apply, where the values came from.
        #
        # Both hug their text and share one trailing stretch inside their own
        # row. A stretchy label would take half the row's slack and leave the
        # link floating a couple of hundred pixels from the sentence it
        # belongs to; the same hugging the Player's now-playing line needs.
        status_row = QHBoxLayout()
        status_row.setSpacing(Theme.SPACING)
        self._lookup_status = HuggingElidedLabel()
        self._lookup_status.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        self._lookup_status.setVisible(False)
        status_row.addWidget(self._lookup_status)

        # Where the tags came from. ACCENT_TEXT rather than the raw accent:
        # it is the palette-aware "accent as readable text" token, and it is
        # the one that stays legible when a light palette inverts the role.
        self._release_link = LinkLabel()
        self._release_link.setText(self.tr("View release"))
        self._release_link.setStyleSheet(f"color: {Theme.ACCENT_TEXT};")
        self._release_link.setToolTip(
            self.tr("Open this release's page on Discogs in your browser.")
        )
        self._release_link.setVisible(False)
        self._release_link.clicked.connect(self._on_release_link_clicked)
        status_row.addWidget(self._release_link)
        status_row.addStretch()
        btn_row.addLayout(status_row, 1)

        btn_row.addStretch()
        # Reload re-reads the file's tags from disk and rebuilds the form —
        # used to pick up changes written elsewhere (e.g. the Player playlist).
        self._reload_btn = QPushButton(self.tr("Reload"))
        self._reload_btn.setMinimumWidth(120)
        self._reload_btn.clicked.connect(self._on_reload)
        self._reload_btn.setVisible(False)
        btn_row.addWidget(self._reload_btn)
        self._eject_btn = QPushButton(self.tr("Eject"))
        self._eject_btn.setMinimumWidth(120)
        self._eject_btn.clicked.connect(self._clear)
        self._eject_btn.setVisible(False)
        self._eject_btn.setStyleSheet(
            f"background-color: {Theme.NEON_YELLOW}; color: #000000; font-weight: bold;"
        )
        btn_row.addWidget(self._eject_btn)
        layout.addLayout(btn_row)

        # Spacer that keeps content pinned to the top in the empty state;
        # hidden when the body is shown so it doesn't steal space.
        self._bottom_spacer = QSpacerItem(
            0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
        )
        layout.addSpacerItem(self._bottom_spacer)

    def _build_discogs_page(self) -> QWidget:
        """The read-only half: everything Discogs told us about the release.

        Scrolls, because it is now long enough to. It shows what is *stored*
        for this release — one request's worth of answer, kept so that opening
        a file costs nothing — and every value is selectable, because the
        reason to look at a catalogue number or a runout is usually to paste
        it somewhere.
        """
        page = QWidget()
        page.setObjectName("metadataDiscogsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(_FORM_LEFT_MARGIN, 10, 0, 0)
        layout.setSpacing(Theme.SPACING)

        # The release's own name, above the scroll rather than in it: it is
        # what the tab is *about*, and it used to be printed twice — once here
        # and once as the first row of the table underneath.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # Never sideways: a long note or a runout etching must wrap into the
        # column, not push a scrollbar under the whole panel.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        # The documented bare-QWidget trap: the global QWidget rule paints
        # BG_DARK over the panel unless the container says otherwise.
        body.setObjectName("metadataDiscogsBody")
        body.setStyleSheet("#metadataDiscogsBody { background-color: transparent; }")
        self._discogs_body = QVBoxLayout(body)
        self._discogs_body.setContentsMargins(0, 0, _DISCOGS_SCROLL_GUTTER, 0)
        self._discogs_body.setSpacing(_SECTION_GAP)
        scroll.setWidget(body)

        # The heading sits *outside* the scroll so the release stays named
        # while its details scroll — but its two buttons then live in a
        # different coordinate space from the ones inside, and landed hard
        # against the pane edge with the section arrows 30px to their left.
        # Reserving the scrollbar's own width plus the body's gutter is what
        # puts all of them in one column; asked of the style rather than
        # guessed, because a scrollbar is not the same width on every platform.
        heading_gutter = (
            scroll.verticalScrollBar().sizeHint().width() + _DISCOGS_SCROLL_GUTTER
        )

        self._discogs_summary = ElidedLabel("")
        self._discogs_summary.setStyleSheet(
            f"color: {Theme.NEON_YELLOW}; font-size: 15px; background: transparent;"
        )
        self._album_apply_btn = self._heading_button()
        title_row = QHBoxLayout()
        title_row.setSpacing(Theme.SPACING)
        title_row.setContentsMargins(0, 0, heading_gutter, 0)
        title_row.addWidget(self._discogs_summary, 1)
        title_row.addWidget(self._album_apply_btn, 0)
        layout.addLayout(title_row)

        self._discogs_subtitle = ElidedLabel("")
        self._discogs_subtitle.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; background: transparent;"
        )
        self._discogs_subtitle.setVisible(False)
        self._artist_apply_btn = self._heading_button()
        artist_row = QHBoxLayout()
        artist_row.setSpacing(Theme.SPACING)
        artist_row.setContentsMargins(0, 0, heading_gutter, 0)
        artist_row.addWidget(self._discogs_subtitle, 1)
        artist_row.addWidget(self._artist_apply_btn, 0)
        layout.addLayout(artist_row)

        layout.addWidget(scroll, 1)

        # Two rows, not one. Four controls and a credit do not fit the tab's
        # 500px at the window's minimum width in any language — German was
        # already 32px over with three of them, and French wants 727px. A
        # QPushButton centres rather than elides, so the overflow is not an
        # ellipsis but two labels cut at both ends and drawn over each other.
        # The review dialog learned the same thing from its own button row:
        # the credit is the part that shares badly, and the buttons are the
        # part that must stay legible.
        row = QHBoxLayout()
        row.setSpacing(Theme.SPACING)
        self._discogs_refresh_btn = QPushButton(self.tr("Refresh from Discogs"))
        self._discogs_refresh_btn.setToolTip(
            self.tr("Read this release again and show what Discogs has on it.")
        )
        self._discogs_refresh_btn.setMinimumWidth(
            self._discogs_refresh_btn.fontMetrics().horizontalAdvance(
                self._discogs_refresh_btn.text()
            )
            + _BUTTON_CHROME
        )
        self._discogs_refresh_btn.clicked.connect(self._on_discogs_refresh)
        row.addWidget(self._discogs_refresh_btn)
        # Homed here rather than beside Add Artwork…: that row is already
        # [Add field ▾] [stretch] [Add Artwork…] [Remove], and a fourth
        # translated label on it is the width problem this tab exists to give
        # the feature a way out of.
        self._find_cover_btn = QPushButton(self.tr("Find Cover Online…"))
        self._find_cover_btn.setToolTip(
            self.tr("Search Discogs and pick which release's cover to use.")
        )
        self._find_cover_btn.setMinimumWidth(
            self._find_cover_btn.fontMetrics().horizontalAdvance(
                self._find_cover_btn.text()
            )
            + _BUTTON_CHROME
        )
        self._find_cover_btn.clicked.connect(self._on_find_cover_clicked)
        row.addWidget(self._find_cover_btn)
        row.addStretch()
        layout.addLayout(row)

        credit_row = QHBoxLayout()
        credit_row.setSpacing(Theme.SPACING)
        self._discogs_link = LinkLabel()
        self._discogs_link.setText(self.tr("View release"))
        self._discogs_link.setStyleSheet(f"color: {Theme.ACCENT_TEXT};")
        self._discogs_link.setToolTip(
            self.tr("Open this release's page on Discogs in your browser.")
        )
        self._discogs_link.clicked.connect(self._on_discogs_link_clicked)
        credit_row.addWidget(self._discogs_link)
        credit_row.addStretch()
        # The same credit the review dialog and the About box carry, on the
        # third surface that displays this data. Not translated: it is a
        # provider credit, like DISPLAY_NAME, and ATTRIBUTION is one constant
        # so the three cannot drift apart.
        self._discogs_credit = QLabel(discogs.ATTRIBUTION)
        self._discogs_credit.setStyleSheet(f"color: {Theme.TEXT_SECONDARY};")
        credit_row.addWidget(self._discogs_credit)
        layout.addLayout(credit_row)
        return page

    # ---------------------------------------------------------- tab drawing

    def _heading_button(self) -> QPushButton:
        """An empty arrow button for the heading, rewired on every redraw.

        Built once and kept, unlike the ones in the sections: the heading is
        not torn down and rebuilt, so a button created here would otherwise be
        connected again on every refresh and fire once per past redraw.
        """
        button = QPushButton("→")
        button.setObjectName("discogsApplyButton")
        button.setFixedSize(_APPLY_BUTTON_SIDE, _APPLY_BUTTON_SIDE)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setVisible(False)
        return button

    def _sync_heading_button(self, button: QPushButton, writes: dict) -> None:
        """Point a heading's button at the value beside it, now."""
        writes = {field: value for field, value in writes.items() if value}
        button.setVisible(bool(writes))
        if not writes:
            return
        field = next(iter(writes))
        current = self._writes_are_current(writes)
        button.setEnabled(not current)
        button.setToolTip(
            self.tr("Already in this file's tags.")
            if current
            else self.tr("Write this to the {0} tag.").format(
                self.tr(FIELD_LABELS.get(field, field))
            )
        )
        # Disconnected first: this runs on every redraw, and an accumulated
        # connection would write the release we were looking at three files ago.
        try:
            button.clicked.disconnect()
        except RuntimeError:
            pass
        button.clicked.connect(lambda _=False, w=dict(writes): self._apply_from_tab(w))

    def _clear_discogs_body(self) -> None:
        """Empty the scrolling area, widgets and nested layouts alike.

        `removeRow` is not available here — this is a QVBoxLayout of sections,
        not a form — and dropping the layout items alone would leave every
        widget parented to the body and still painted. Recursed, because a
        section is a layout containing labels.
        """
        def drain(layout) -> None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()
                elif item.layout() is not None:
                    drain(item.layout())
                    item.layout().deleteLater()

        drain(self._discogs_body)

    def _value_label(self, text: str) -> QLabel:
        """A value the user can select and copy.

        Selectable is the point of the whole tab: the reason to look at a
        catalogue number, a runout etching or a barcode is almost always to
        paste it into something else, and a label you cannot select makes a
        reader retype what is on screen in front of them.
        """
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        label.setStyleSheet("background: transparent;")
        return label

    def _add_section(
        self, title: str, rows: list[tuple[str, str]], *, align: bool = True
    ) -> None:
        """A headed block of label/value pairs, or nothing if it has no rows.

        An empty section is worse than a missing one: it says Discogs holds a
        kind of information about this record and then shows none of it.

        ``align=False`` keeps a section out of the shared label column. The
        distinction is whether the left-hand text is a *field name* or a
        *value*: "Catalogue Number" and "Barcode" line up with each other and
        should, but a tracklist position is data — stretching "A1" to the width
        of "Catalogue Number" puts 150px of nothing between a track and its
        own number.
        """
        # Rows are (label, value) or (label, value, {tag: value}). The third
        # element is what the arrow button writes — a dict rather than one
        # field, because a tracklist row is a title *and* a number and
        # applying half of it is not a thing anyone wants.
        rows = [
            (row[0], row[1], row[2] if len(row) > 2 else {})
            for row in rows
            if row[1]
        ]
        if not rows:
            return
        heading = QLabel(title)
        heading.setStyleSheet(
            f"color: {Theme.NEON_YELLOW}; font-weight: bold; background: transparent;"
        )
        self._discogs_body.addWidget(heading)

        form = QFormLayout()
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        # The macOS style's default form alignment is centred, which pushes
        # every row into the middle of the tab. The tag form above escapes it
        # only because its fields grow to fill the width; these are labels.
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        form.setHorizontalSpacing(_SECTION_LABEL_GAP)
        form.setVerticalSpacing(_ROW_GAP)
        form.setContentsMargins(0, 0, 0, 0)
        for label, value, writes in rows:
            key = QLabel(label)
            key.setStyleSheet(
                f"color: {Theme.TEXT_SECONDARY}; background: transparent;"
            )
            # Collected so every section can be given one label column below.
            # Each QFormLayout sizes its own otherwise, and the values then
            # start at a different x in each block — which reads as three
            # tables that failed to line up rather than as one panel.
            if align:
                self._discogs_keys.append((key, label))
            form.addRow(key, self._value_row(value, writes))
        self._discogs_body.addLayout(form)

    def _value_row(self, value: str, writes: dict) -> QWidget:
        """A value, plus the button that writes it into this file's tags.

        Wrapped in a widget rather than added as a third form column: the
        button belongs to its value, and a column of its own would leave a
        gutter of empty space down every row that has nothing to write.
        """
        holder = QWidget()
        holder.setObjectName("discogsValueRow")
        holder.setStyleSheet("#discogsValueRow { background: transparent; }")
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(Theme.SPACING)
        row.addWidget(self._value_label(value), 1)
        if writes:
            row.addWidget(self._apply_button(writes), 0, Qt.AlignmentFlag.AlignTop)
        return holder

    def _apply_button(self, writes: dict) -> QPushButton:
        """One click to put this value in the tag it belongs to.

        Disabled rather than hidden when the file already has the value: which
        rows are *available* to apply is worth seeing at a glance, and a button
        that comes and goes as the tags change is harder to read than one that
        greys out. Icon-only because a QPushButton centres rather than elides,
        so a translated word here would be cut at both ends before it clipped.
        """
        button = QPushButton("→")
        button.setObjectName("discogsApplyButton")
        button.setFixedSize(_APPLY_BUTTON_SIDE, _APPLY_BUTTON_SIDE)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if self._writes_are_current(writes):
            button.setEnabled(False)
            button.setToolTip(self.tr("Already in this file's tags."))
        elif len(writes) > 1:
            button.setToolTip(
                self.tr("Write this row's title and track number to the tags.")
            )
        else:
            field = next(iter(writes))
            button.setToolTip(
                self.tr("Write this to the {0} tag.").format(
                    self.tr(FIELD_LABELS.get(field, field))
                )
            )
        button.clicked.connect(lambda _=False, w=dict(writes): self._apply_from_tab(w))
        return button

    def _writes_are_current(self, writes: dict) -> bool:
        """Whether the file already holds exactly what this button would write.

        Compared against the *form*, not against a re-read of the file: the
        form is what the user is looking at, it is authoritative for unsaved
        edits, and re-reading a file per row on every redraw would put a dozen
        disk reads behind a tab switch.
        """
        for field, value in writes.items():
            edit = self._field_edits.get(field)
            if edit is None or edit.text().strip() != str(value).strip():
                return False
        return True

    def _apply_from_tab(self, writes: dict) -> None:
        """Write one row's worth of Discogs values into the file.

        Through `lookup_flow.apply_values`, the same path the review dialog
        takes, so the WAV guard and the Windows file-lock retries apply here
        for free rather than being reimplemented for a second entry point.
        """
        if self._file_path is None or not writes:
            return
        error = lookup_flow.apply_values(self._file_path, writes)
        if error:
            QMessageBox.warning(self, self.tr("Look Up Online"), error)
            return
        # Reload rather than trusting what we believe we wrote — and hold the
        # session result across it, because `_load_file` clears the provenance
        # for a *new* file and this is a reload of the same one.
        result = self._last_result
        self._load_file(self._file_path)
        self._last_result = result
        self._refresh_discogs_tab()

    def _add_text_section(self, title: str, text: str) -> None:
        """A headed block of prose, full width.

        Not a one-row form with a blank label: that indents the text to the
        label column and leaves a rectangle of nothing beside it. Release notes
        are a paragraph, not a field.
        """
        heading = QLabel(title)
        heading.setStyleSheet(
            f"color: {Theme.NEON_YELLOW}; font-weight: bold; background: transparent;"
        )
        self._discogs_body.addWidget(heading)
        self._discogs_body.addWidget(self._value_label(text))

    def _align_section_labels(self) -> None:
        """Give every section the same label column, measured not guessed.

        The widest label wins, and it is measured from the font rather than
        set as a constant, because these strings are translated — a number
        that fits "Catalogue Number" says nothing about "Katalognummer" or
        «Каталожный номер».
        """
        if not self._discogs_keys:
            return
        widest = max(
            QFontMetrics(key.font()).horizontalAdvance(text)
            for key, text in self._discogs_keys
        )
        for key, _text in self._discogs_keys:
            key.setMinimumWidth(widest)

    def _refresh_discogs_tab(self) -> None:
        """Redraw the tab from whatever we currently know about the release."""
        self._clear_discogs_body()
        self._discogs_keys: list[tuple[QLabel, str]] = []

        candidate = self._tab_candidate()
        # A lookup this session or a stored description is the rich case; a
        # stored id on its own is the honest one. Both beat a blank tab, which
        # reads as broken.
        if candidate is not None:
            self._discogs_summary.setText(candidate.album or self.tr("Unknown release"))
            self._discogs_summary.setToolTip(candidate.album)
            self._discogs_subtitle.setText(candidate.artist)
            self._discogs_subtitle.setVisible(bool(candidate.artist))
            # The heading is where the album and the artist live now, so it is
            # where their buttons have to live too — they are the two most
            # worth applying, and moving them out of the table to stop the
            # duplication must not cost them their arrow.
            self._sync_heading_button(
                self._album_apply_btn, {"album": candidate.album}
            )
            self._sync_heading_button(
                self._artist_apply_btn, {"artist": candidate.artist}
            )
            self._fill_release_sections(candidate)
            self._align_section_labels()
        elif self._release_id:
            self._discogs_summary.setText(
                self.tr("Tagged from Discogs release {0}.").format(self._release_id)
            )
            self._discogs_subtitle.setVisible(False)
            self._album_apply_btn.setVisible(False)
            self._artist_apply_btn.setVisible(False)
        elif self._online_enabled:
            self._discogs_summary.setText(
                self.tr("No release known for this file yet. Look it up online.")
            )
            self._discogs_subtitle.setVisible(False)
            self._album_apply_btn.setVisible(False)
            self._artist_apply_btn.setVisible(False)
        else:
            self._discogs_summary.setText(
                self.tr("Online lookup is switched off in Settings.")
            )
            self._discogs_subtitle.setVisible(False)
            self._album_apply_btn.setVisible(False)
            self._artist_apply_btn.setVisible(False)
        self._discogs_body.addStretch()
        known = bool(self._release_id or candidate is not None)
        self._discogs_refresh_btn.setVisible(self._online_enabled and known)
        self._discogs_link.setVisible(bool(self._discogs_page_url()))

    def _fill_release_sections(self, candidate) -> None:
        """Everything the provider gave us, grouped by what kind of fact it is.

        The grouping is what makes two of these readable at all. ``Year`` and
        ``Released`` are different facts that can legitimately disagree — the
        year prefers the *master*'s, so a DJ gets the year the record came out
        rather than the year this repress did, while the date is this
        pressing's own — and side by side under one heading they read as the
        panel contradicting itself. Under **Release** and **Pressing** they
        read as what they are.

        The title and artist are the heading above, not rows here: they were
        the tab's one visible duplication.
        """
        year = str(candidate.year) if candidate.year else ""
        # The genre tag is written from *styles* — "Electronic" is not a genre
        # a DJ sorts by and "Techno" is — so the arrow is on that row and not
        # on Genres, which is shown for reference. `_genre_from` is the same
        # function the lookup writes through, so the two cannot disagree.
        genre = discogs._genre_from(candidate.styles, candidate.genres)
        self._add_section(
            self.tr("Release"),
            [
                (self.tr("Label"), candidate.label, {"label": candidate.label}),
                (self.tr("Catalogue Number"), candidate.catalogue_number),
                (self.tr("Year"), year, {"year": year}),
                # Not translated: styles and genres are Discogs' own taxonomy,
                # the same reason the genre tag is written from them verbatim.
                (self.tr("Styles"), "; ".join(candidate.styles), {"genre": genre}),
                (self.tr("Genres"), "; ".join(candidate.genres)),
            ],
        )
        self._add_section(
            self.tr("Pressing"),
            [
                (self.tr("Format"), candidate.format_line()),
                (self.tr("Country"), candidate.country),
                (self.tr("Released"), candidate.released),
            ],
        )
        self._add_section(
            self.tr("Tracklist"), self._tracklist_rows(candidate), align=False
        )
        self._add_section(self.tr("Credits"), self._credit_rows(candidate.credits))
        self._add_section(self.tr("Identifiers"), list(candidate.identifiers))
        self._add_section(self.tr("Community"), self._community_rows(candidate))
        if candidate.notes:
            self._add_text_section(self.tr("Notes"), candidate.notes)

    def _tracklist_rows(self, candidate) -> list[tuple[str, str]]:
        """Each playable row: where it sits, what it is, how long, who remixed it.

        The position is the label because that is how a record is read — "B1"
        is where you put the needle. It falls back to the ordinal for a CD,
        where there is no side to name.
        """
        rows: list[tuple[str, str]] = []
        for entry in candidate.tracklist:
            head = entry.position.strip() or (str(entry.ordinal) if entry.ordinal else "")
            parts = [entry.title]
            if entry.artist:
                parts.insert(0, f"{entry.artist} —")
            if entry.duration:
                parts.append(f"({_format_duration(entry.duration)})")
            for name, role in self._grouped_credits(entry.credits):
                parts.append(f"· {role}: {name}")
            # Title and number together: which row of a release a file is, is
            # one fact, and a title written without its number leaves the file
            # claiming to be track 1 of a twelve-track compilation.
            writes = {"title": entry.title}
            if entry.number:
                writes["track_number"] = str(entry.number)
            rows.append((head, " ".join(p for p in parts if p), writes))
        return rows

    def _credit_rows(self, credits) -> list[tuple[str, str]]:
        """Credits as role → the people who did it."""
        return [(role, name) for name, role in self._grouped_credits(credits)]

    @staticmethod
    def _grouped_credits(credits) -> list[tuple[str, str]]:
        """(names, role) pairs, one per role, in the order Discogs gave them.

        Grouped because a release routinely credits three people as Written-By
        and one row each turns the section into a list of repetitions of the
        word. Roles are never translated — they are values out of Discogs'
        taxonomy, like the styles.
        """
        by_role: dict[str, list[str]] = {}
        for credit in credits or ():
            by_role.setdefault(credit.role, []).append(credit.name)
        return [(", ".join(names), role) for role, names in by_role.items()]

    def _tab_candidate(self):
        """The best description of this file's release that we have.

        This session's lookup first, because it is the freshest and because a
        candidate switch has to be reflected before the user presses anything.
        Otherwise the stored description, which is the whole reason the tab can
        say something about a file the moment it is loaded — before v7, a file
        whose release was perfectly well known still got a release *number*
        and an invitation to look it up.
        """
        candidate = getattr(self._last_result, "chosen", None)
        if candidate is not None:
            return candidate
        return lookup_flow.cached_candidate(self._library, self._release_id)

    def _community_rows(self, candidate) -> list[tuple[str, str]]:
        """Have / want / rating — not tags, and not a match signal either.

        They are how two pressings of one title are told apart when everything
        printed on them reads the same.
        """
        rating = ""
        if candidate.rating:
            rating = f"{candidate.rating:.2f}"
            if candidate.rating_count:
                rating = f"{rating} ({candidate.rating_count})"
        return [
            (self.tr("Have"), str(candidate.have) if candidate.have else ""),
            (self.tr("Want"), str(candidate.want) if candidate.want else ""),
            (self.tr("Rating"), rating),
        ]

    def _discogs_page_url(self) -> str:
        """The release page, from the best description we have or the stored id."""
        candidate = self._tab_candidate()
        if candidate is not None and candidate.page_url:
            return candidate.page_url
        if self._release_id:
            return RELEASE_PAGE.format(id=self._release_id)
        return ""

    def _on_discogs_link_clicked(self) -> None:
        url = self._discogs_page_url()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _on_discogs_refresh(self) -> None:
        """Read the known release again, into the tab rather than the dialog.

        One thread path, not two: the same `_start_lookup` the button uses,
        with a flag saying where the answer goes. A second async path would
        need its own cancel, its own thread_keeper handling and its own
        shutdown, all to do what this one already does.
        """
        if self._file_path is None or self._lookup_thread is not None:
            return
        candidate = self._tab_candidate()
        if candidate is None and self._release_id:
            candidate = Candidate(
                provider=discogs.PROVIDER_NAME, release_id=self._release_id
            )
        if candidate is None:
            return
        self._tab_refresh = True
        self._start_lookup(
            LookupJob(
                path=self._file_path,
                query=self._current_query(),
                candidate=candidate,
                want_artwork=False,
            )
        )

    # ---------------------------------------------------------- drop handling

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if Path(url.toLocalFile()).suffix.lower() in AUDIO_EXTENSIONS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        pass

    def dropEvent(self, event: QDropEvent) -> None:
        if not event.mimeData().hasUrls():
            return
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                event.acceptProposedAction()
                self._load_file(normalize_track_path(path))
                return

    def _load_file(self, path: str) -> None:
        """Load metadata from *path* and populate the form."""
        # Before anything else: a file that has just arrived has no
        # provenance, and inheriting the previous file's would read as having
        # been looked up. _apply_lookup_values re-states it after this returns.
        self._clear_provenance()
        self._file_path = path
        self._file_label.setText(Path(path).name)
        self._path_label.setText(path)
        # Set here rather than left to the label's own resize handling, which
        # only runs on a resize — otherwise a shorter path inherits the
        # previous file's tooltip until the panel happens to change width.
        self._path_label.setToolTip(path)
        self._info_label.setText(_format_audio_props(path))
        self._file_header_widget.setVisible(True)

        try:
            meta = read_metadata(path)
        except Exception as e:
            logger.error("Failed to read metadata: %s", e)
            self._file_label.setText(self.tr("Error: {0}").format(e))
            self._info_label.setText("")
            return

        self._populate_form(meta)
        # After the form, so _refresh_discogs_tab sees the finished state.
        self._sync_release_memory()
        # Programmatic load — don't fire artwork_changed (would re-save the same bytes).
        self._artwork.set_artwork(meta.artwork, meta.artwork_mime, emit=False)

    # ------------------------------------------------------------- form build

    def _populate_form(self, meta: TrackMetadata) -> None:
        """Build (or rebuild) form rows for all populated fields."""
        # Tear down old rows
        self._disconnect_fields()
        self._field_edits.clear()
        while self._form_layout.rowCount():
            self._form_layout.removeRow(0)

        meta_dict = meta.to_dict()

        # Show rows for fields that have values
        shown_fields: set[str] = set()
        for field_key, label in FIELD_ORDER:
            value = meta_dict.get(field_key)
            if value is not None:
                self._add_field_row(field_key, label, str(value))
                shown_fields.add(field_key)

        # Populate the "Add field" combo with remaining fields
        self._add_combo.blockSignals(True)
        self._add_combo.clear()
        self._add_combo.addItem(self.tr("Add field..."))
        for field_key, label in FIELD_ORDER:
            if field_key not in shown_fields:
                self._add_combo.addItem(self.tr(label), field_key)
        self._add_combo.blockSignals(False)

        # Reconnect combo
        try:
            self._add_combo.currentIndexChanged.disconnect()
        except RuntimeError:
            pass
        self._add_combo.currentIndexChanged.connect(self._on_add_field_selected)

        # Show editor widgets and collapse the bottom spacer
        self._set_empty_state(False)
        self._tabs.setVisible(True)
        self._controls_row_widget.setVisible(True)
        self._reload_btn.setVisible(True)
        self._eject_btn.setVisible(True)
        self._artwork.setVisible(True)
        self._add_artwork_btn.setVisible(True)
        self._sync_lookup_button()
        self._bottom_spacer.changeSize(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

    def _add_field_row(self, field_key: str, label: str, value: str = "") -> None:
        edit = QLineEdit(value)
        edit.setObjectName(f"metaField_{field_key}")
        edit.editingFinished.connect(self._on_editing_finished)
        self._field_edits[field_key] = edit
        row_label = QLabel(self.tr(label))
        row_label.setMinimumWidth(80)
        self._form_layout.addRow(row_label, edit)

    def _disconnect_fields(self) -> None:
        for edit in self._field_edits.values():
            try:
                edit.editingFinished.disconnect(self._on_editing_finished)
            except RuntimeError:
                pass

    # --------------------------------------------------------- add-field combo

    def _on_add_field_selected(self, index: int) -> None:
        if index <= 0:
            return
        field_key = self._add_combo.itemData(index)
        if field_key and field_key not in self._field_edits:
            label = FIELD_LABELS.get(field_key, field_key)
            self._add_field_row(field_key, label, "")
            # Remove from combo
            self._add_combo.blockSignals(True)
            self._add_combo.removeItem(index)
            self._add_combo.setCurrentIndex(0)
            self._add_combo.blockSignals(False)
            # Focus the new field
            self._field_edits[field_key].setFocus()

    # ------------------------------------------------------------ auto-save

    def _on_editing_finished(self) -> None:
        """Auto-save when a field loses focus."""
        self._save_metadata()
        # Typing a title is the other way out of the empty state, and the offer
        # has to notice: a hint saying the file has no tags, beside a Title the
        # user has just filled in, is the panel arguing with itself.
        self._sync_lookup_button()

    # --------------------------------------------------------------- save

    def _save_metadata(self) -> None:
        if self._file_path is None or self._saving:
            return
        self._saving = True
        try:
            self._do_save()
        finally:
            self._saving = False

    def _do_save(self) -> None:
        meta = TrackMetadata()
        fields_to_write: list[str] = []
        fields_to_delete: list[str] = []

        for field_key, edit in self._field_edits.items():
            text = edit.text().strip()
            if not text:
                fields_to_delete.append(field_key)
                continue
            if field_key == "bpm":
                try:
                    meta.bpm = float(text)
                    fields_to_write.append("bpm")
                except ValueError:
                    pass
            elif field_key == "year":
                try:
                    meta.year = int(text)
                    fields_to_write.append("year")
                except ValueError:
                    pass
            elif field_key == "track_number":
                try:
                    meta.track_number = int(text)
                    fields_to_write.append("track_number")
                except ValueError:
                    pass
            elif field_key == "comment":
                meta.comment = text
                fields_to_write.append("comment")
            else:
                setattr(meta, field_key, text)
                fields_to_write.append(field_key)

        if not fields_to_write and not fields_to_delete:
            return

        try:
            # Delete cleared fields from the file
            if fields_to_delete:
                delete_metadata_fields(self._file_path, fields_to_delete)
                logger.info("Deleted tags %s from %s", fields_to_delete, Path(self._file_path).name)

            # write_metadata handles artist/title/album/genre/year/track_number/bpm/key
            standard_fields = [f for f in fields_to_write if f != "comment"]
            if standard_fields:
                write_metadata(self._file_path, meta, standard_fields)

            # Comment needs special handling — write via mutagen directly
            if "comment" in fields_to_write and meta.comment is not None:
                self._write_comment(self._file_path, meta.comment)

            logger.info("Metadata saved for %s", Path(self._file_path).name)
        except Exception as e:
            logger.error("Failed to save metadata: %s", e)

    @staticmethod
    def _write_comment(file_path: str, comment: str) -> None:
        """Write a comment tag to *file_path* (delegates to the shared helper)."""
        write_comment(file_path, comment)

    # --------------------------------------------------------------- reload

    def _on_reload(self) -> None:
        """Re-read tags from disk and rebuild the form.

        Discards any in-progress edit in the focused field (auto-save already
        persisted committed fields). Used to pick up changes written from
        another panel — confirming the "stale until reloaded" model.
        """
        if self._file_path is not None:
            self._load_file(self._file_path)

    # --------------------------------------------------------------- reveal

    def _on_reveal_clicked(self) -> None:
        """Show the loaded file in the OS file manager, selected.

        ``reveal_in_file_manager`` selects the file itself; the ``openUrl``
        variant in three other panels only opens the containing folder, which
        leaves the user hunting for it in a directory of a thousand tracks.
        A miss means the file moved since it was loaded — an explanation, not
        an error.
        """
        if not self._file_path:
            return
        if not reveal_in_file_manager(self._file_path):
            QMessageBox.information(
                self,
                self.tr("Open File Location"),
                self.tr(
                    "This file can't be found — it may have been moved, "
                    "renamed, or deleted."
                ),
            )

    # ----------------------------------------------------------- path menu

    def build_path_menu(self) -> tuple[QMenu, dict]:
        """What can be done with the file this panel is editing.

        Open File Location repeats the button beside it on purpose: the button
        is discoverable and the menu entry is where a user who right-clicked a
        path expects to find it, and the alternative — a menu that pointedly
        omits the obvious entry — reads as an oversight.
        """
        menu = QMenu(self)
        actions = {
            "reveal": menu.addAction(self.tr("Open File Location")),
            "play": menu.addAction(self.tr("Play in Player")),
            "copy": menu.addAction(self.tr("Copy File Path")),
        }
        for action in actions.values():
            action.setEnabled(bool(self._file_path))
        return menu, actions

    def _on_path_menu(self, pos) -> None:
        if not self._file_path:
            return
        menu, actions = self.build_path_menu()
        chosen = menu.exec(self._path_label.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is actions["reveal"]:
            self._on_reveal_clicked()
        elif chosen is actions["play"]:
            self.play_requested.emit(self._file_path)
        elif chosen is actions["copy"]:
            self.copy_path_to_clipboard()

    def copy_path_to_clipboard(self) -> None:
        """Put the full path on the clipboard.

        The whole path, not the elided text on screen: what the label shows is
        a rendering decision, and pasting `/Users/…/a track.flac` into a
        terminal would be worse than pasting nothing.
        """
        if not self._file_path:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._file_path)

    # --------------------------------------------------------------- clear

    def _set_empty_state(self, empty: bool) -> None:
        """Show or hide the two things that only belong to the drop state.

        Both say the same thing in different registers — "there is no file
        here yet" — and both keep saying it over a file that is plainly
        loaded. The description is a prompt to do what the user has already
        done; the watermark is a panel-sized icon behind a form. Hidden
        together so the loaded panel is the tags and nothing else.

        The overlay is shared by every panel (``BackgroundOverlay``), and this
        makes Metadata the only one that takes it down. That is deliberate and
        limited to here: it is also the only panel whose content routinely
        fills the space the watermark occupies.
        """
        self._desc_label.setVisible(empty)
        self._bg_overlay.setVisible(empty)

    def _clear(self) -> None:
        """Reset panel to drop state."""
        self._clear_provenance()
        self._file_path = None
        self._disconnect_fields()
        self._field_edits.clear()
        while self._form_layout.rowCount():
            self._form_layout.removeRow(0)

        self._artwork.clear_artwork(emit=False)
        self._set_empty_state(True)
        self._file_header_widget.setVisible(False)
        self._info_label.setText("")
        self._path_label.setText("")
        self._path_label.setToolTip("")
        self._tabs.setVisible(False)
        self._controls_row_widget.setVisible(False)
        self._reload_btn.setVisible(False)
        self._eject_btn.setVisible(False)
        self._artwork.setVisible(False)
        self._add_artwork_btn.setVisible(False)
        self._sync_lookup_button()
        # Restore the bottom spacer so empty state stays pinned to top
        self._bottom_spacer.changeSize(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        self.layout().invalidate()

    # ------------------------------------------------------- online lookup

    def set_library(self, library) -> None:
        """Hand the panel the library, so a lookup can be remembered.

        Only ever *read and updated* through here — never added to. A file
        dropped on this panel is not a library import, and calling `add_track`
        from here would quietly turn the tag editor into one.
        """
        self._library = library
        self._sync_release_memory()

    def _sync_release_memory(self) -> None:
        """Read back the release this file was tagged from, if we know it."""
        self._release_id = None
        if self._library is not None and self._file_path is not None:
            try:
                # `release_for_path`, not the track row: a file dragged
                # straight onto this panel has no row — the ordinary case
                # here, and the one whose lookups were forgotten the instant
                # they were applied.
                self._release_id = self._library.release_for_path(self._file_path)
            except Exception as exc:  # noqa: BLE001 — no memory is not an error
                logger.debug("Could not read the release memory: %s", exc)
        self._refresh_discogs_tab()

    def _remember_release(self, release_id: int | None) -> None:
        """Store the approved release, and what Discogs said about it.

        Through `lookup_flow.remember_lookup`, which the Player's batch review
        also calls: the release memory shipped written by one of the two
        lookup paths and read by neither, and one helper is what stops that
        happening a third time.
        """
        self._release_id = release_id
        if self._file_path is None or not release_id:
            return
        candidate = getattr(self._last_result, "chosen", None)
        if candidate is None or candidate.release_id != release_id:
            # Nothing to describe — record the identity alone rather than
            # cache a description of a different release.
            if self._library is not None:
                try:
                    self._library.remember_release_for_path(
                        self._file_path, release_id
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Could not remember the release: %s", exc)
            return
        lookup_flow.remember_lookup(self._library, self._file_path, candidate)

    def set_online_lookup(
        self, enabled: bool, token: str = "", fetch_artwork: bool = True
    ) -> None:
        """Push the Settings state down. Called by MainWindow, not by the user."""
        self._online_enabled = bool(enabled)
        self._discogs_token = (token or "").strip()
        self._fetch_artwork = bool(fetch_artwork)
        self._sync_lookup_button()
        self._refresh_discogs_tab()

    def _sync_lookup_button(self) -> None:
        """The button exists only when the feature is on and a file is loaded."""
        visible = self._online_enabled and self._file_path is not None
        self._lookup_btn.setVisible(visible)
        # Same rule, so the same call: the cover search is not gated on a
        # known release the way Refresh is — a file with no release at all is
        # the one most likely to be missing its sleeve. Set here rather than
        # in `_refresh_discogs_tab` because `_clear` redraws the tab *before*
        # it drops the file path, so a button synced there survived the eject.
        self._find_cover_btn.setVisible(visible)
        self._sync_empty_hint(visible)
        if not visible:
            self._lookup_status.setVisible(False)
            self._lookup_status.setText("")
            # The link has to follow the sentence it belongs to: a provenance
            # line surviving the feature being switched off would credit
            # Discogs on a panel with no Discogs on it.
            self._release_link.setVisible(False)

    def _sync_empty_hint(self, lookup_offered: bool) -> None:
        """Offer the lookup on a file that has nothing to show.

        Tied to the button's own visibility, not just to the file's tags: a
        sentence naming Discogs on a panel with the feature switched off
        advertises something the user cannot reach, the same rule the
        provenance link follows.
        """
        blank = lookup_offered and not any(
            self._field_edits[key].text().strip()
            for key in ("artist", "title")
            if key in self._field_edits
        )
        if blank:
            text = self.tr("No tags on this file — look it up on Discogs?")
            self._empty_hint.setText(text)
            self._empty_hint.setToolTip(text)
        self._empty_hint.setVisible(blank)

    def _current_query(self):
        """What we know about the loaded file, filename fallback included."""
        # The form, not the file: an edit the user has just made is the better
        # description of the track, and it is already saved to disk anyway.
        values = {key: edit.text().strip() for key, edit in self._field_edits.items()}
        duration = None
        try:
            duration = read_metadata(self._file_path).duration
        except Exception:  # noqa: BLE001 — a duration is a nicety, not a need
            pass
        return lookup_flow.query_for(
            self._file_path,
            artist=values.get("artist"),
            title=values.get("title"),
            album=values.get("album"),
            duration=duration,
        )

    def _usable_query(self, title: str):
        """The search query, or None having said why there isn't one.

        Shared by both buttons that search: the reason a file cannot be looked
        up does not change with what the user meant to get out of it, and the
        sentence is the same one either way — only the title over it differs,
        so it names the button that was pressed.
        """
        query = self._current_query()
        if query.is_usable():
            return query
        QMessageBox.information(
            self,
            title,
            self.tr(
                "This file has no artist or title to search with, and its "
                "name doesn't give one either. Fill in the Title field and "
                "try again."
            ),
        )
        return None

    def _on_lookup_clicked(self) -> None:
        if self._file_path is None or self._lookup_thread is not None:
            return
        query = self._usable_query(self.tr("Look Up Online"))
        if query is None:
            return
        self._start_lookup(
            LookupJob(
                path=self._file_path,
                query=query,
                want_artwork=self._fetch_artwork,
                prefer_release_id=self._release_id,
            )
        )

    def _on_find_cover_clicked(self) -> None:
        """Search for this track and review the sleeve alone.

        ``want_artwork=True`` whatever Settings says. That checkbox reads
        "Fetch cover art with lookups" and governs the cover that rides along
        with a *metadata* lookup; this is the cover, asked for by name, and a
        button that answered "no covers, you turned them off" would be
        refusing to do the only thing it offers.

        The search runs even when the release is already known, because the
        point is usually that *this* pressing has no scan. ``prefer_release_id``
        opens the dialog on the known one when the search returns it, so the
        default answer stays the release the file was tagged from and the
        switcher is what moves off it.
        """
        if self._file_path is None or self._lookup_thread is not None:
            return
        query = self._usable_query(self.tr("Find Cover Online"))
        if query is None:
            return
        self._artwork_lookup = True
        self._start_lookup(
            LookupJob(
                path=self._file_path,
                query=query,
                want_artwork=True,
                prefer_release_id=self._release_id,
            )
        )

    def _start_lookup(self, job: LookupJob) -> None:
        provider = DiscogsProvider(token=self._discogs_token)
        thread = LookupThread(provider, [job], self)
        thread.result_ready.connect(self._on_lookup_result)
        thread.waiting.connect(self._on_lookup_waiting)
        thread.finished.connect(self._on_lookup_finished)
        # Hold the wrapper until its C++ object is actually gone; reassigning
        # the attribute alone can drop the last reference mid-teardown.
        thread_keeper.keep_alive(self._threads, thread)
        self._lookup_thread = thread
        # All three, not just the one on the Tags page: the status line lives
        # there too, so a lookup started from the Discogs tab has nothing else
        # to show for itself, and a button that swallows clicks in silence
        # reads as broken rather than as busy.
        self._set_lookup_controls_enabled(False)
        self._set_lookup_status(self.tr("Looking up…"))
        thread.start()

    def _set_lookup_controls_enabled(self, enabled: bool) -> None:
        for button in (
            self._lookup_btn,
            self._discogs_refresh_btn,
            self._find_cover_btn,
        ):
            button.setEnabled(enabled)

    def _set_lookup_status(self, text: str) -> None:
        self._lookup_status.setText(text)
        self._lookup_status.setToolTip(text)
        self._lookup_status.setVisible(bool(text))

    def _on_lookup_waiting(self, seconds: float) -> None:
        self._set_lookup_status(self.tr("Waiting for the Discogs rate limit…"))

    def _on_lookup_finished(self) -> None:
        # Clear the slot only if a newer lookup has not already taken it —
        # a superseded thread finishing is the normal case, and an unguarded
        # clear would wipe the live one's reference.
        thread = self.sender()
        if thread is self._lookup_thread:
            self._lookup_thread = None
        self._set_lookup_controls_enabled(True)

    def _on_lookup_result(self, result) -> None:
        if self._file_path is None or result.path != self._file_path:
            # The user ejected or dropped another file while it ran.
            self._set_lookup_status("")
            self._tab_refresh = False
            self._artwork_lookup = False
            return
        if not result.ok:
            self._set_lookup_status("")
            self._tab_refresh = False
            # Safe unconditionally: a failed *candidate switch* arrives with a
            # dialog already open, and opening it is what consumed the flag.
            self._artwork_lookup = False
            if self._review_dialog is not None:
                # A candidate switch that failed. Leaving the combo on a
                # release we could not read would have it naming one pressing
                # over fields describing another — the mismatch the switcher
                # exists to escape.
                self._review_dialog.restore_candidate()
            QMessageBox.information(
                self, self.tr("Look Up Online"), self._lookup_error_text(result.error)
            )
            return
        self._set_lookup_status("")
        # Before the branch below, not after it: a candidate switch arrives
        # through that return, and the release the apply credits has to be the
        # one the user ended up looking at.
        self._last_result = result
        # Every reading of a release is worth keeping, whether or not anything
        # is applied: without this, Refresh showed fresh values this session
        # and the stored ones on the next load, with nothing to tell them
        # apart. The *identity* is still only recorded on approval.
        lookup_flow.cache_description(self._library, result.chosen)
        # The tab follows *every* result, not only an applied one. It reports
        # what Discogs knows about this file, and a review the user cancels —
        # or one where every field already matched, so there was nothing left
        # to tick — has still answered the question the tab asks. Before the
        # dialog, because exec() blocks until it closes.
        self._refresh_discogs_tab()
        if self._tab_refresh:
            # A Refresh, not a re-tag: fill the tab and open nothing.
            self._tab_refresh = False
            return
        if self._review_dialog is not None:
            # A candidate switch: the dialog is open and waiting for this.
            self._review_dialog.set_result(result)
            return
        # Spent here, at the one point it turns into a dialog: the two returns
        # above are a Refresh and a candidate switch, neither of which can be
        # holding it — a switch arrives with the dialog that consumed it
        # already open.
        artwork_only = self._artwork_lookup
        self._artwork_lookup = False
        self._show_review_dialog(result, artwork_only=artwork_only)

    def _lookup_error_text(self, kind: str) -> str:
        """One sentence per failure kind (shared with the Player's batch run)."""
        return lookup_flow.error_text(kind)

    def _show_review_dialog(self, result, artwork_only: bool = False) -> None:
        try:
            current = read_metadata(self._file_path)
        except Exception as exc:
            logger.error("Could not re-read tags before review: %s", exc)
            return
        values = dict(current.to_dict())
        values[ARTWORK_FIELD] = current.artwork
        dialog = LookupReviewDialog(
            file_path=self._file_path,
            current=values,
            result=result,
            allow_artwork=self._fetch_artwork,
            parent=self,
            artwork_only=artwork_only,
        )
        dialog.candidate_requested.connect(self._on_candidate_requested)
        self._review_dialog = dialog
        try:
            accepted = dialog.exec()
        finally:
            self._review_dialog = None
        if accepted:
            self._apply_lookup_values(dialog.selected_values())

    def _on_candidate_requested(self, candidate) -> None:
        """The user picked a different release; read that one instead."""
        if self._file_path is None or self._lookup_thread is not None:
            return
        # A cover review switching pressing has to pull *that* release's
        # sleeve down, whatever the Settings checkbox says: without this the
        # preview keeps showing the previous release's cover under the new
        # release's name, which is the same mismatch the switcher exists to
        # escape, moved from the fields onto the picture.
        review = self._review_dialog
        want_artwork = self._fetch_artwork or bool(
            getattr(review, "artwork_only", False)
        )
        self._start_lookup(
            LookupJob(
                path=self._file_path,
                query=self._current_query(),
                candidate=candidate,
                want_artwork=want_artwork,
            )
        )

    def _apply_lookup_values(self, values: dict) -> None:
        """Write the approved fields, and remember the release either way.

        **Approving zero fields is not approving nothing.** On a file that was
        tagged from Discogs in an earlier session every field already matches,
        so the diff offers nothing to tick — and that is precisely the file
        whose release identity is most clearly known and, before this, the one
        case where it was never recorded. Pressing Apply is the user saying
        this is the right release; whether it also changed a tag is a separate
        question. Cancel still records nothing, because a review is cancelled
        when the match was *wrong*, and remembering it would seed the next
        lookup with it.
        """
        if self._file_path is None:
            return
        # Read the release *before* any reload: _load_file clears the
        # provenance, which is what stops a newly dropped file wearing the
        # previous one's.
        proposed = getattr(self._last_result, "proposed", None)
        url = getattr(proposed, "source_url", "") or ""
        chosen = getattr(self._last_result, "chosen", None)
        release_id = getattr(chosen, "release_id", 0) or None
        result = self._last_result
        self._remember_release(release_id)
        if values:
            error = lookup_flow.apply_values(self._file_path, values)
            if error:
                QMessageBox.warning(self, self.tr("Look Up Online"), error)
                return
            # Reload rather than trusting what we believe we wrote.
            self._load_file(self._file_path)
            # Both restored by hand, because _load_file legitimately clears
            # them for a *new* file and this is the one reload of the same
            # one. The release id especially: _sync_release_memory answers
            # from the library, and a file dropped straight onto this panel
            # has no row there — so what the user just approved would be
            # forgotten the instant it was applied.
            self._last_result = result
            self._release_id = release_id
            # Only when something really was written: a provenance line over
            # an unchanged file would be claiming a write that never happened.
            self._show_provenance(url)
        self._refresh_discogs_tab()

    def _show_provenance(self, url: str) -> None:
        """Say the values came from Discogs, and offer the release page.

        Survives until the file is ejected or another is loaded — a tag editor
        with no history of its own is otherwise silent about where a value it
        is now showing came from.

        **No field count**, deliberately. "Applied %n field(s)" is what a Qt
        plural ships as its own source text, and an untranslated language falls
        back to that source — so English, the default, would read "Applied 5
        field(s)", which is not English. Spelling the two forms out instead
        (the branch `compatible_panel._sync_seed_label` takes) fixes English
        and breaks Russian and Polish, which need a third form for 2–4 and
        would get the plural one. The count is the least load-bearing part of
        the sentence — the form beside it has just been rebuilt from disk and
        shows every value that changed — so dropping it is what makes the line
        correct in all twelve languages at once.
        """
        sentence = self.tr("Applied from Discogs")
        self._release_url = url
        self._set_lookup_status(f"{sentence} ·" if url else sentence)
        self._release_link.setVisible(bool(url))

    def _clear_provenance(self) -> None:
        """Forget the last lookup: a new file has nothing to do with it.

        The release *id* goes too, and always did need to: `_clear` never
        reset it, so an ejected file left its release behind and the empty
        panel went on reporting one. That was survivable while the tab could
        only print a number and is not now that it can describe the record.
        `_load_file` re-reads it from the library immediately afterwards, so
        the only state this can lose is state that belonged to another file.
        """
        self._last_result = None
        self._release_id = None
        self._release_url = ""
        self._release_link.setVisible(False)
        self._set_lookup_status("")
        # The tab reads `_last_result` first, so it has to be redrawn here or
        # a newly dropped file shows the previous one's release.
        self._refresh_discogs_tab()

    def _on_release_link_clicked(self) -> None:
        if self._release_url:
            QDesktopServices.openUrl(QUrl(self._release_url))

    def shutdown_workers(self) -> None:
        """Wait for a lookup in flight before the window goes away.

        A urllib request is one long blocking call, so there is nothing to
        interrupt — but a QThread destroyed while running is undefined
        behaviour, and a worker emitting into a deleted panel is worse.
        """
        if self._lookup_thread is not None:
            self._lookup_thread.cancel()
        thread_keeper.wait_for_threads(self._threads)

    def closeEvent(self, event) -> None:
        self.shutdown_workers()
        super().closeEvent(event)

    # ----------------------------------------------------------- artwork actions

    def _on_add_artwork_clicked(self) -> None:
        if self._file_path is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select cover art"),
            "",
            "Images (*.jpg *.jpeg *.png)",
        )
        if not path:
            return
        try:
            data = Path(path).read_bytes()
        except OSError as e:
            logger.error("Could not read image %s: %s", path, e)
            return
        mime = mime_for_path(path)
        self._artwork.set_artwork(data, mime, emit=True)

    def _on_artwork_changed(self, data, mime) -> None:
        """Persist artwork changes from a drop, Add Artwork, or the cover menu."""
        if self._file_path is None or self._saving:
            return
        self._saving = True
        try:
            if data:
                meta = TrackMetadata(artwork=bytes(data), artwork_mime=str(mime) if mime else None)
                write_metadata(self._file_path, meta, fields=["artwork"])
                logger.info("Wrote artwork (%d bytes) to %s", len(data), Path(self._file_path).name)
            else:
                delete_metadata_fields(self._file_path, ["artwork"])
                logger.info("Removed artwork from %s", Path(self._file_path).name)
        except Exception as e:
            logger.error("Failed to save artwork: %s", e)
        finally:
            self._saving = False
