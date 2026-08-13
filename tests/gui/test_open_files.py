"""The receiving end of "Open with Mixed in P".

Three pieces, tested at the level each one actually decides something:

* ``MainWindow.open_files`` — the funnel every OS entry point shares. Driven
  as an unbound method against a stub (the same trick the drag tests use),
  because what is being tested is the *order* of its steps, not a window.
* ``PlayerPanel.play_path_if_idle`` — the idle question, and which row wins.
* ``FileOpenRelay`` — the macOS half, whose whole job is timing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QUrl

from src.gui.file_open_relay import FileOpenRelay
from src.gui.main_window import MainWindow
from src.gui.widgets.player_panel import PlayerPanel
from src.library import SCRATCH_NODE_ID, Library
from src.utils.paths import normalize_track_path as norm


def make_files(tmp_path, *names):
    paths = []
    for name in names:
        f = tmp_path / name
        f.write_bytes(b"not-really-audio-" + name.encode())
        paths.append(str(f))
    return paths


# ── MainWindow.open_files ───────────────────────────────────────


class PanelStub:
    def __init__(self, loaded=SCRATCH_NODE_ID):
        self.loaded_node_id = loaded
        self.loaded = []
        self.added = []
        self.allow_duplicates = None
        self.scroll_to_end = None
        self.played = []
        self.play_result = True

    def load_node(self, node_id):
        self.loaded.append(node_id)
        self.loaded_node_id = node_id

    def add_tracks(self, tracks, allow_duplicates=None, *, scroll_to_end=True):
        self.added.extend(tracks)
        self.allow_duplicates = allow_duplicates
        self.scroll_to_end = scroll_to_end

    def play_path_if_idle(self, path):
        self.played.append(path)
        return self.play_result


class SidebarStub:
    def __init__(self):
        self.pages = []

    def set_current_page(self, page_id):
        self.pages.append(page_id)


class WindowStub(QObject):
    """Just enough MainWindow to run the real open_files against.

    A QObject because the batch timer wants a parent, and it is set up by
    MainWindow's own method rather than a copy of it — the wiring between
    ``open_files`` and ``_flush_open_batch`` is part of what is being tested.
    """

    open_files = MainWindow.open_files
    _flush_open_batch = MainWindow._flush_open_batch
    _setup_open_batch = MainWindow._setup_open_batch
    _add_files_to_player = MainWindow._add_files_to_player

    def __init__(self, loaded=SCRATCH_NODE_ID):
        super().__init__()
        self._player_panel = PanelStub(loaded)
        self._sidebar = SidebarStub()
        self.pages = []
        self.raised = 0
        self._setup_open_batch()

    def _raise_to_front(self):
        self.raised += 1

    def _on_page_changed(self, page_id):
        self.pages.append(page_id)


def open_now(window, paths):
    """Open *paths* and close the batch window by hand.

    For the tests that are about what ``open_files`` decides rather than when
    it decides it — the timing itself is covered by TestOpenBatching.
    """
    window.open_files(paths)
    window._open_batch_timer.stop()
    window._flush_open_batch()


class TestOpenFiles:
    @pytest.fixture(autouse=True)
    def _app(self, qapp):
        """WindowStub owns a QTimer, which wants an application to live in."""

    def test_it_targets_scratch_even_with_a_playlist_loaded(self, tmp_path):
        """Otherwise a file from Finder appends to the user's set list.

        And the list auto-saves, so the damage is silent and persistent —
        which is why this is step one and not an afterthought.
        """
        (a,) = make_files(tmp_path, "a.mp3")
        window = WindowStub(loaded=42)

        open_now(window, [a])

        assert window._player_panel.loaded == [SCRATCH_NODE_ID]

    def test_duplicates_are_forced_never_asked(self, tmp_path):
        """The prompt is deferred off a timer; during launch it could land
        before the window is even mapped."""
        (a,) = make_files(tmp_path, "a.mp3")
        window = WindowStub()

        open_now(window, [a])

        assert window._player_panel.allow_duplicates is True

    def test_the_view_stays_at_the_track_that_starts_playing(self, tmp_path):
        """An add normally scrolls to the end. Not this one: the first of
        these files is about to play, and its row is at the top."""
        a, b = make_files(tmp_path, "a.mp3", "b.mp3")
        window = WindowStub()

        open_now(window, [a, b])

        assert window._player_panel.scroll_to_end is False

    def test_the_file_lands_normalized(self, tmp_path):
        (a,) = make_files(tmp_path, "a.mp3")
        window = WindowStub()

        open_now(window, [a])

        assert [t["file_path"] for t in window._player_panel.added] == [
            norm(a)
        ]

    def test_it_plays_the_first_file_and_asks_for_the_stored_spelling(self, tmp_path):
        """Matching on the raw string would silently never find the row —
        the panel stores the normalized one."""
        a, b = make_files(tmp_path, "a.mp3", "b.mp3")
        window = WindowStub()

        open_now(window, [a, b])

        assert window._player_panel.played == [norm(a)]

    def test_unsupported_files_are_dropped_not_refused(self, tmp_path):
        """A folder's worth of files should add the audio and ignore the art."""
        a, art, notes = make_files(tmp_path, "a.mp3", "cover.jpg", "notes.txt")
        window = WindowStub()

        open_now(window, [art, a, notes])

        assert [t["file_path"] for t in window._player_panel.added] == [
            norm(a)
        ]

    def test_it_switches_to_the_player(self, tmp_path):
        """Both halves: the nav rail's highlight and the actual page."""
        (a,) = make_files(tmp_path, "a.mp3")
        window = WindowStub()

        open_now(window, [a])

        assert window._sidebar.pages == ["player"]
        assert window.pages == ["player"]

    def test_it_comes_to_the_front(self, tmp_path):
        (a,) = make_files(tmp_path, "a.mp3")
        window = WindowStub()

        open_now(window, [a])

        assert window.raised == 1

    def test_a_bare_relaunch_raises_and_touches_nothing_else(self):
        """Double-clicking the app while it runs means "show me", not "load".

        The early return sits *after* the raise on purpose — this is the test
        that would fail if someone moved it above.
        """
        window = WindowStub(loaded=42)

        open_now(window, [])

        assert window.raised == 1
        assert window._player_panel.loaded == []
        assert window._player_panel.added == []
        assert window._player_panel.played == []

    def test_a_selection_of_only_unsupported_files_changes_nothing(self, tmp_path):
        art, notes = make_files(tmp_path, "cover.jpg", "notes.txt")
        window = WindowStub(loaded=42)

        open_now(window, [art, notes])

        assert window.raised == 1
        assert window._player_panel.loaded == []
        assert window._player_panel.added == []

    def test_the_batch_is_sorted_not_left_in_arrival_order(self, tmp_path):
        """Windows hands these over in whatever order five processes race in —
        measured as a different order on all three runs of the same files."""
        one, two, three = make_files(tmp_path, "1 one.mp3", "2 two.mp3", "3 three.mp3")
        window = WindowStub()

        open_now(window, [three, one, two])

        assert [t["file_path"] for t in window._player_panel.added] == [
            norm(one),
            norm(two),
            norm(three),
        ]

    def test_the_track_that_plays_is_the_first_by_name(self, tmp_path):
        """The whole point of waiting for the batch: without it the app plays
        whichever process won the race, which is row 3 as often as row 1."""
        one, two, three = make_files(tmp_path, "1 one.mp3", "2 two.mp3", "3 three.mp3")
        window = WindowStub()

        open_now(window, [three, one, two])

        assert window._player_panel.played == [norm(one)]


# ── The batch window ────────────────────────────────────────────


class TestOpenBatching:
    """Several one-file arrivals, milliseconds apart, are one open.

    This is the machinery that lets the sort above mean anything: on Windows
    the five files of a multi-select arrive as five separate calls, so a
    version of this that acted on each call would sort lists of one.
    """

    @pytest.fixture(autouse=True)
    def quick_batch(self, qapp, monkeypatch):
        """Shrink the window so the timing tests cost milliseconds.

        The real 300 ms is a property of how the shells launch us, not of
        anything these tests assert — they are about *whether* arrivals
        coalesce and the timer fires, not about the number.
        """
        monkeypatch.setattr("src.gui.main_window.OPEN_BATCH_MS", 10)

    def test_arrivals_in_the_window_become_one_add(self, qtbot, tmp_path):
        """One reload of Scratch, one add, one play decision — not five."""
        a, b, c = make_files(tmp_path, "a.mp3", "b.mp3", "c.mp3")
        window = WindowStub()

        for path in (c, a, b):
            window.open_files([path])
        qtbot.waitUntil(lambda: bool(window._player_panel.added), timeout=1000)

        assert window._player_panel.loaded == [SCRATCH_NODE_ID]
        assert [t["file_path"] for t in window._player_panel.added] == [
            norm(a),
            norm(b),
            norm(c),
        ]
        assert window._player_panel.played == [norm(a)]

    def test_the_timer_fires_without_being_flushed_by_hand(self, qtbot, tmp_path):
        """The wiring itself: nothing else in the app calls the flush."""
        (a,) = make_files(tmp_path, "a.mp3")
        window = WindowStub()

        window.open_files([a])
        assert window._player_panel.added == []  # still waiting

        qtbot.waitUntil(lambda: bool(window._player_panel.added), timeout=1000)

    def test_the_window_does_not_slide_with_each_arrival(self, qtbot, tmp_path):
        """Started, not restarted. A trickle of arrivals must not be able to
        postpone playback indefinitely."""
        a, b = make_files(tmp_path, "a.mp3", "b.mp3")
        window = WindowStub()
        starts: list[int] = []
        real_start = window._open_batch_timer.start

        def spy(ms):
            starts.append(ms)
            real_start(ms)

        window._open_batch_timer.start = spy

        window.open_files([a])
        window.open_files([b])

        assert starts == [10]

    def test_a_later_open_starts_a_fresh_batch(self, qtbot, tmp_path):
        """Two separate gestures are two opens — the second must not be
        swallowed by a buffer that was never emptied."""
        a, b = make_files(tmp_path, "a.mp3", "b.mp3")
        window = WindowStub()

        window.open_files([a])
        qtbot.waitUntil(lambda: bool(window._player_panel.added), timeout=1000)
        window.open_files([b])
        qtbot.waitUntil(
            lambda: len(window._player_panel.added) == 2, timeout=1000
        )

        assert window._player_panel.loaded == [SCRATCH_NODE_ID, SCRATCH_NODE_ID]
        assert window._player_panel.played == [norm(a), norm(b)]

    def test_coming_to_the_front_does_not_wait_for_the_batch(self, qtbot, tmp_path):
        """A relaunch means "show me" now, not in 300 ms — and a bare one
        carries no files to wait for at all."""
        (a,) = make_files(tmp_path, "a.mp3")
        window = WindowStub()

        window.open_files([a])

        assert window.raised == 1
        assert window._player_panel.added == []


# ── PlayerPanel.play_path_if_idle ───────────────────────────────


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "library.db")
    yield library
    library.close()


@pytest.fixture
def player(qtbot, lib):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    panel.set_library(lib)
    return panel


@pytest.fixture
def played(player, monkeypatch):
    """Record which row playback was asked for, without decoding anything.

    ``_play_track`` spawns a decode thread and touches the audio device; what
    this method adds on top of it is the *decision*, so the decision is what
    is tested here. Real playback is covered by the manual checklist.
    """
    calls: list[int] = []
    monkeypatch.setattr(player, "_play_track", calls.append)
    return calls


def add(player, paths):
    player.add_tracks(
        [{"file_path": p, "display_name": Path(p).name} for p in paths],
        allow_duplicates=True,
    )


def set_engine(player, monkeypatch, *, playing=False, paused=False):
    monkeypatch.setattr(player._engine, "is_playing", lambda: playing)
    monkeypatch.setattr(player._engine, "is_paused", lambda: paused)


class TestPlayPathIfIdle:
    def test_an_idle_player_plays_the_file(self, player, played, monkeypatch, tmp_path):
        """The cold-start case, which is the entire point of the feature."""
        a, b = make_files(tmp_path, "a.mp3", "b.mp3")
        add(player, [a, b])
        set_engine(player, monkeypatch)

        assert player.play_path_if_idle(b) is True
        assert played == [1]

    def test_it_will_not_interrupt_playback(self, player, played, monkeypatch, tmp_path):
        """Cutting off a track mid-set is a real-world harm in a DJ app."""
        (a,) = make_files(tmp_path, "a.mp3")
        add(player, [a])
        set_engine(player, monkeypatch, playing=True)

        assert player.play_path_if_idle(a) is False
        assert played == []

    def test_paused_counts_as_busy(self, player, played, monkeypatch, tmp_path):
        """A paused track holds a position the user chose and expects back."""
        (a,) = make_files(tmp_path, "a.mp3")
        add(player, [a])
        set_engine(player, monkeypatch, paused=True)

        assert player.play_path_if_idle(a) is False
        assert played == []

    def test_a_pending_decode_counts_as_busy(
        self, player, played, monkeypatch, tmp_path
    ):
        """Between _play_track and the PCM landing the engine reads as stopped,
        but a track is milliseconds from starting."""
        (a,) = make_files(tmp_path, "a.mp3")
        add(player, [a])
        set_engine(player, monkeypatch)
        player._pending_play_path = a

        assert player.play_path_if_idle(a) is False
        assert played == []

    def test_the_newest_copy_wins(self, player, played, monkeypatch, tmp_path):
        """Additions force duplicates, so the row the user just asked for is
        the last one, not the one that was already there."""
        (a,) = make_files(tmp_path, "a.mp3")
        add(player, [a])
        add(player, [a])
        set_engine(player, monkeypatch)

        assert player.play_path_if_idle(a) is True
        assert played == [1]

    def test_a_path_that_is_not_here_plays_nothing(
        self, player, played, monkeypatch, tmp_path
    ):
        a, b = make_files(tmp_path, "a.mp3", "b.mp3")
        add(player, [a])
        set_engine(player, monkeypatch)

        assert player.play_path_if_idle(b) is False
        assert played == []


# ── FileOpenRelay (macOS) ───────────────────────────────────────


class TestFileOpenRelay:
    """The macOS delivery path, whose only real hazard is arriving too early."""

    @pytest.fixture
    def relay(self, qtbot):
        host = QObject()
        return FileOpenRelay(host), host

    def test_events_before_go_live_are_buffered_and_replayed_as_one(self, relay):
        """Skip this and the *first* Open With silently does nothing while
        every later one works — which reads as flakiness, not a bug.

        Coalescing matters too: macOS sends one event per file, and five
        separate emissions would load Scratch and raise the window five times.
        """
        rly, _ = relay
        got: list[list[str]] = []
        rly.files_opened.connect(got.append)

        rly._deliver("/music/a.mp3")
        rly._deliver("/music/b.mp3")
        assert got == []

        rly.go_live()
        assert got == [[norm("/music/a.mp3"), norm("/music/b.mp3")]]

    def test_after_go_live_events_pass_straight_through(self, relay):
        rly, _ = relay
        got: list[list[str]] = []
        rly.files_opened.connect(got.append)
        rly.go_live()

        rly._deliver("/music/a.mp3")
        rly._deliver("/music/b.mp3")

        assert got == [[norm("/music/a.mp3")], [norm("/music/b.mp3")]]

    def test_go_live_on_an_ordinary_launch_emits_nothing(self, relay):
        """Nothing was buffered — the common case must stay silent."""
        rly, _ = relay
        got: list[list[str]] = []
        rly.files_opened.connect(got.append)

        rly.go_live()

        assert got == []

    def test_a_real_event_reaches_the_signal(self, qtbot, tmp_path):
        """Drive it through eventFilter rather than _deliver, so the wiring
        (the filter is installed, and QFileOpenEvent is the type it matches)
        is covered and not just the buffering.
        """
        from PySide6.QtGui import QFileOpenEvent

        host = QObject()
        rly = FileOpenRelay(host)
        got: list[list[str]] = []
        rly.files_opened.connect(got.append)
        rly.go_live()

        (a,) = make_files(tmp_path, "a.mp3")
        handled = rly.eventFilter(host, QFileOpenEvent(QUrl.fromLocalFile(a)))

        assert handled is True
        assert got == [[norm(a)]]

    def test_a_non_local_url_is_ignored(self, qtbot):
        """An http:// URL is not a file this app has any business opening."""
        from PySide6.QtGui import QFileOpenEvent

        host = QObject()
        rly = FileOpenRelay(host)
        got: list[list[str]] = []
        rly.files_opened.connect(got.append)
        rly.go_live()

        rly.eventFilter(host, QFileOpenEvent(QUrl("https://example.com/a.mp3")))

        assert got == []
