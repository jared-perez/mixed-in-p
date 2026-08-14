"""The optional Art column: thumbnails read off the main thread.

Reading embedded art is a full tag parse per file, so the column is hidden
until asked for and, once shown, only ever reads the rows actually on screen.
Everything else here follows from that: a cache so scrolling back is free, a
record of which files have no art at all (so they are not re-read forever),
one reader at a time, and a size that follows the row height.

The painting is checked by sampling a render rather than by asserting on
DecorationRole. A model-level assertion would pass against a build that draws
nothing — which is exactly how the row-tint bug in the Analyze panel survived
ten passing tests.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage

from src.gui.widgets.player_panel import PlayerPanel
from src.metadata.tags import TrackMetadata, write_metadata

ART_COLUMN = 15
COVER = "#ff00ff"  # magenta: nothing else in the theme is close


@pytest.fixture
def sf():
    return pytest.importorskip("soundfile")


@pytest.fixture
def cover_bytes(tmp_path):
    image = QImage(200, 200, QImage.Format.Format_RGB32)
    image.fill(QColor(COVER))
    path = tmp_path / "cover.png"
    image.save(str(path))
    return path.read_bytes()


def make_track(sf, tmp_path, name, cover=None):
    path = tmp_path / name
    sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
    if cover is not None:
        write_metadata(
            str(path),
            TrackMetadata(title=name, artwork=cover, artwork_mime="image/png"),
        )
    return str(path)


@pytest.fixture
def player(qtbot):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    panel.resize(900, 400)
    panel.show()
    qtbot.waitExposed(panel)
    return panel


def add(player, qtbot, *paths):
    player.add_tracks(
        [{"file_path": p, "display_name": Path(p).name} for p in paths],
        allow_duplicates=True,
    )
    qtbot.wait(10)


def show_art(player, qtbot):
    """Reveal the column and wait for the read to land.

    The debounce timer is stopped and the load driven directly, rather than
    waiting for it: waiting on "a thread appeared" races the 120 ms timer, and
    waiting on "no thread" is satisfied instantly by the state *before* it
    starts. Called this way the reference is set before the call returns (the
    finished handler cannot run until the event loop does), so the wait below
    has something real to wait for.

    It waits on the panel dropping its reader references rather than on the
    thread's isRunning(): by then the QThread's C++ object is gone, and
    touching the Python wrapper that outlives it raises.
    """
    player._set_column_visible(ART_COLUMN, True)
    pump_art(player, qtbot)


def pump_art(player, qtbot):
    """Run one artwork load to completion, without racing the debounce.

    The wait comes first, not last: a scroll that has not been processed yet
    leaves rowAt() reading the old viewport, so the load would ask for the
    rows that *were* on screen. (CLAUDE.md: anything Qt computes lazily from
    layout is stale until the event loop has run.)
    """
    qtbot.wait(10)
    player._art_timer.stop()
    player._load_visible_artwork()
    if player._art_thread is not None:
        qtbot.waitUntil(lambda: player._art_thread is None, timeout=5000)
    qtbot.wait(10)


class TestItStaysOutOfTheWayUntilAsked:
    def test_the_column_is_hidden_to_begin_with(self, player):
        assert player._table.isColumnHidden(ART_COLUMN)

    def test_nothing_is_read_while_it_is_hidden(self, player, qtbot, sf, tmp_path, cover_bytes):
        """The whole point of it being optional: a thousand-track playlist
        should not pay a thousand tag parses for a column nobody opened."""
        add(player, qtbot, make_track(sf, tmp_path, "a.flac", cover_bytes))
        qtbot.wait(50)

        assert player._art_worker is None
        assert not player._art_cache

    def test_revealing_it_starts_the_read(self, player, qtbot, sf, tmp_path, cover_bytes):
        add(player, qtbot, make_track(sf, tmp_path, "a.flac", cover_bytes))

        show_art(player, qtbot)

        assert len(player._art_cache) == 1


class TestOnlyTheRowsOnScreen:
    """The claim the whole design rests on. A tag parse per file is not
    something a long playlist can pay all at once, so a playlist taller than
    the viewport must read a fraction of itself."""

    def _long_playlist(self, player, qtbot, sf, tmp_path, cover_bytes, count=60):
        paths = [
            make_track(sf, tmp_path, f"t{i:02d}.flac", cover_bytes)
            for i in range(count)
        ]
        add(player, qtbot, *paths)
        return paths

    def test_a_long_playlist_reads_only_what_fits(
        self, player, qtbot, sf, tmp_path, cover_bytes
    ):
        paths = self._long_playlist(player, qtbot, sf, tmp_path, cover_bytes)
        visible = len(player._visible_rows())
        assert 0 < visible < len(paths), "the fixture must overflow the viewport"

        show_art(player, qtbot)

        assert len(player._art_cache) == visible

    def test_scrolling_reads_the_rows_that_arrive(
        self, player, qtbot, sf, tmp_path, cover_bytes
    ):
        """Scrolls UP, because an add leaves the view at the end of the list
        (W0-1) — so the rows nobody has read yet are the ones above."""
        self._long_playlist(player, qtbot, sf, tmp_path, cover_bytes)
        show_art(player, qtbot)
        first_pass = len(player._art_cache)

        player._table.scrollToTop()
        pump_art(player, qtbot)

        assert len(player._art_cache) > first_pass

    def test_scrolling_back_costs_nothing(
        self, player, qtbot, sf, tmp_path, cover_bytes
    ):
        """What the cache is for: the rows are already known, so no reader
        starts at all."""
        self._long_playlist(player, qtbot, sf, tmp_path, cover_bytes)
        show_art(player, qtbot)
        player._table.scrollToTop()
        pump_art(player, qtbot)

        player._table.scrollToBottom()
        qtbot.wait(10)
        player._art_timer.stop()
        player._load_visible_artwork()

        assert player._art_thread is None, "re-read rows it already had"


class TestWhatItPaints:
    def _art_pixel(self, player, row):
        """Sample inside the thumbnail itself.

        The icon is drawn at the left of the cell, so the centre of the *cell*
        misses it — which it did, and briefly looked like nothing was painting
        at all.
        """
        table = player._table
        table.scrollToTop()
        shot = table.viewport().grab().toImage()
        icon = table.iconSize().width()
        x = table.columnViewportPosition(ART_COLUMN) + icon // 2 + 2
        y = table.rowViewportPosition(row) + table.rowHeight(row) // 2
        return shot.pixelColor(x, y)

    def test_a_cover_actually_reaches_the_screen(
        self, player, qtbot, sf, tmp_path, cover_bytes
    ):
        """Sampled from a render: the app stylesheet targets QTableView::item,
        and a data-level assertion cannot tell a painted thumbnail from a
        stored one that never gets drawn."""
        add(player, qtbot, make_track(sf, tmp_path, "a.flac", cover_bytes))
        # Give the column room on screen.
        for col in (2, 3, 6, 7):
            player._set_column_visible(col, False)
        show_art(player, qtbot)

        assert self._art_pixel(player, 0).name() == COVER

    def test_a_track_with_no_cover_paints_nothing(
        self, player, qtbot, sf, tmp_path, cover_bytes
    ):
        add(
            player, qtbot,
            make_track(sf, tmp_path, "with.flac", cover_bytes),
            make_track(sf, tmp_path, "without.flac"),
        )
        for col in (2, 3, 6, 7):
            player._set_column_visible(col, False)
        show_art(player, qtbot)

        assert self._art_pixel(player, 1).name() != COVER


class TestTheCache:
    def test_a_coverless_file_is_only_read_once(
        self, player, qtbot, sf, tmp_path
    ):
        """Most libraries are mostly coverless. Without remembering the
        answer, every scroll past such a row re-parses its tags forever."""
        add(player, qtbot, make_track(sf, tmp_path, "none.flac"))
        show_art(player, qtbot)
        assert len(player._art_missing) == 1

        player._load_visible_artwork()

        assert player._art_cache == {}

    def test_the_key_carries_the_mtime(self, player, sf, tmp_path, cover_bytes):
        """So a file re-tagged in another app shows its new cover instead of
        the one we happened to read first."""
        path = make_track(sf, tmp_path, "a.flac", cover_bytes)

        key = player._art_key(path)

        assert key[0] == path
        assert key[1] == Path(path).stat().st_mtime

    def test_a_missing_file_still_gets_a_key(self, player, tmp_path):
        """stat() raises on a moved file, and a playlist full of those is a
        normal state for this app."""
        assert player._art_key(str(tmp_path / "gone.flac")) == (
            str(tmp_path / "gone.flac"), 0.0,
        )

    def test_it_does_not_grow_without_bound(self, player):
        from PySide6.QtGui import QPixmap

        for i in range(player._ART_CACHE_MAX + 20):
            player._art_cache[(f"/music/{i}.flac", 0.0)] = QPixmap()
        player._on_artwork_loaded(
            "/music/new.flac", QImage(4, 4, QImage.Format.Format_RGB32)
        )

        assert len(player._art_cache) <= player._ART_CACHE_MAX


class TestItFollowsTheRowHeight:
    def test_the_thumbnail_is_sized_to_the_row(self, player):
        row = player._table.verticalHeader().defaultSectionSize()

        assert player._art_size() == row - player._ART_ROW_INSET

    def test_the_view_icon_size_follows_too(self, player, qtbot, sf, tmp_path, cover_bytes):
        """A thumbnail scaled to 30px still paints at Qt's 16px default
        unless the view's icon size says otherwise."""
        add(player, qtbot, make_track(sf, tmp_path, "a.flac", cover_bytes))
        show_art(player, qtbot)

        assert player._table.iconSize().width() == player._art_size()

    def test_changing_the_text_size_rescales_them(
        self, player, qtbot, sf, tmp_path, cover_bytes
    ):
        add(player, qtbot, make_track(sf, tmp_path, "a.flac", cover_bytes))
        show_art(player, qtbot)
        small = next(iter(player._art_cache.values())).width()

        player.set_text_size("large")
        pump_art(player, qtbot)

        assert next(iter(player._art_cache.values())).width() > small


class TestThreading:
    def test_the_reader_is_joined_on_shutdown(
        self, player, qtbot, sf, tmp_path, cover_bytes
    ):
        """House rule: a panel that starts reader threads joins them on close,
        or Qt destroys a running QThread. The worker is cancelled first —
        its run() is a plain loop, so quit() means nothing to it."""
        add(player, qtbot, make_track(sf, tmp_path, "a.flac", cover_bytes))
        player._set_column_visible(ART_COLUMN, True)
        qtbot.wait(10)

        player.shutdown_workers()

        assert player._art_thread is None

    def test_a_new_request_cancels_the_one_in_flight(self, player, qtbot):
        """The old request is for rows the user has already scrolled past."""
        player._start_artwork_worker(["/music/a.flac"], 24)
        first = player._art_worker

        player._start_artwork_worker(["/music/b.flac"], 24)

        assert first._cancelled is True
        qtbot.waitUntil(lambda: player._art_thread is None, timeout=5000)
