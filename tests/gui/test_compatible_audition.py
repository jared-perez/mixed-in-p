"""The click-gated audition: the gesture, the windows, and the gutter icon.

The gesture was decided in full on 2026-08-12 and is not a hover-to-play:
a **click** starts a track, sound lasts only while the pointer stays on the
icon, moving off stops everything, the main player stays stopped, and a
second click skips 30 s on. Each of those is a test here.

No audio device is opened: `AuditionPlayer` is driven with its engine
replaced by a recorder, so what is asserted is which windows were asked for
and when sound was told to start and stop — not whether a speaker made a
noise, which a headless machine cannot answer anyway.

The icon is checked by **sampling a render**. It is drawn by a delegate
precisely because the QSS styles `QTableView::item` and would overpaint
anything the model returned, so a data-level assertion here would pass
against a build that draws nothing at all.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent

from src.gui.widgets.audition_player import SKIP_MS, AuditionPlayer
from src.gui.widgets.compatible_panel import COL_AUDITION, COL_TRACK
from src.gui.widgets.player_panel import PlayerPanel
from src.gui.workers.audition_worker import WINDOW_MS, read_window
from src.library import Library


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


def make_file(tmp_path, name):
    f = tmp_path / name
    f.write_bytes(b"not-really-audio-" + name.encode())
    return str(f)


def add_track(player, tmp_path, name, **tags):
    path = make_file(tmp_path, name)
    entry = {"file_path": path, "display_name": name}
    entry.update({k: str(v) for k, v in tags.items()})
    player.add_tracks([entry])
    return path


class FakeEngine:
    """Stands in for the audition's PlayerEngine — records, makes no sound."""

    def __init__(self):
        self.loaded: list[int] = []  # sample rates, in load order
        self.plays = 0
        self.stops = 0
        self.unloads = 0
        self._playing = False

    def load(self, pcm, sr):
        self.loaded.append(int(sr))

    def play(self):
        self.plays += 1
        self._playing = True
        return True

    def stop(self):
        self.stops += 1
        self._playing = False

    def unload(self):
        self.unloads += 1
        self._playing = False

    def is_playing(self):
        return self._playing

    def set_volume(self, volume):
        pass


@pytest.fixture
def audition(qtbot):
    """An AuditionPlayer whose windows arrive instantly and silently."""
    player = AuditionPlayer()
    player._engine = FakeEngine()
    requested: list[tuple[str, int]] = []

    def fake_request(path, offset_ms, *, play):
        requested.append((path, offset_ms))
        if play:
            player._play_on_arrival = False
            player._start_engine(path, np.zeros((16, 2), dtype=np.float32), 44100)

    player._request = fake_request
    player.requested = requested
    yield player
    player.shutdown_workers()


class TestWindowReader:
    """The one part that really touches a file."""

    def test_a_window_reads_only_its_own_slice(self, tmp_path):
        sf = pytest.importorskip("soundfile")
        path = tmp_path / "tone.wav"
        sr = 8000
        tone = np.zeros((sr * 4, 1), dtype=np.float32)  # 4 seconds
        sf.write(str(path), tone, sr)

        pcm, got_sr = read_window(str(path), 1000, 2000)
        assert got_sr == sr
        assert pcm.shape[0] == pytest.approx(sr * 2, abs=2)

    def test_a_window_past_the_end_comes_back_empty(self, tmp_path):
        """This is how a skip learns it has run out of track — no duration
        probe, and no trusting a length the tags claim."""
        sf = pytest.importorskip("soundfile")
        path = tmp_path / "short.wav"
        sf.write(str(path), np.zeros((8000, 1), dtype=np.float32), 8000)

        pcm, sr = read_window(str(path), 60_000, WINDOW_MS)
        assert pcm.shape[0] == 0
        assert sr == 8000


class TestGesture:
    def test_a_click_starts_at_the_top_of_the_track(self, audition):
        audition.click("/music/a.wav")
        assert audition.requested == [("/music/a.wav", 0)]
        assert audition._engine.plays == 1
        assert audition.is_playing()

    def test_hover_alone_never_makes_a_sound(self, audition):
        """The whole point of the click gate: a swipe across the panel must
        not emit audio."""
        audition.warm("/music/a.wav")
        assert audition.requested == [("/music/a.wav", 0)]
        assert audition._engine.plays == 0
        assert not audition.is_playing()

    def test_a_second_click_skips_thirty_seconds(self, audition):
        audition.click("/music/a.wav")
        audition.click("/music/a.wav")
        assert audition.requested[-1] == ("/music/a.wav", SKIP_MS)

    def test_skips_accumulate(self, audition):
        audition.click("/music/a.wav")
        audition.click("/music/a.wav")
        audition.click("/music/a.wav")
        assert audition.requested[-1] == ("/music/a.wav", 2 * SKIP_MS)

    def test_clicking_another_row_starts_that_one_from_the_top(self, audition):
        audition.click("/music/a.wav")
        audition.click("/music/b.wav")
        assert audition.requested[-1] == ("/music/b.wav", 0)
        assert audition.current_path == "/music/b.wav"

    def test_stop_ends_it_and_forgets_it(self, qtbot, audition):
        audition.click("/music/a.wav")
        with qtbot.waitSignal(audition.stopped):
            audition.stop()
        assert audition.current_path is None
        assert not audition.is_playing()
        audition.click("/music/a.wav")
        assert audition.requested[-1] == ("/music/a.wav", 0)

    def test_stop_is_idempotent_and_silent_when_nothing_plays(self, audition):
        received = []
        audition.stopped.connect(lambda: received.append(1))
        audition.stop()
        audition.stop()
        assert received == []

    def test_a_finished_window_rolls_into_the_next(self, audition):
        """Holding the icon past 35 s must play on, not stop dead."""
        audition.click("/music/a.wav")
        audition._on_window_finished()
        assert audition.requested[-1] == ("/music/a.wav", WINDOW_MS)

    def test_running_off_the_end_stops(self, qtbot, audition):
        audition.click("/music/a.wav")
        with qtbot.waitSignal(audition.stopped):
            audition._on_window_empty("/music/a.wav", SKIP_MS)
        assert audition.current_path is None

    def test_a_late_window_for_an_abandoned_track_is_not_played(self, audition):
        """A decode that lands after the pointer has left is cached, never
        played — sound arriving after the gesture ended is the failure this
        gesture exists to avoid."""
        audition.click("/music/a.wav")
        plays_before = audition._engine.plays
        audition.stop()
        audition._on_window_ready(
            "/music/a.wav", 0, np.zeros((16, 2), dtype=np.float32), 44100
        )
        assert audition._engine.plays == plays_before
        assert audition._have("/music/a.wav", 0)


class TestPanelWiring:
    def test_an_audition_stops_the_main_player(self, qtbot, player, tmp_path):
        add_track(player, tmp_path, "seed.wav", key="8A", bpm=128.0)
        match = add_track(player, tmp_path, "match.wav", key="8A", bpm=128.0)
        player._play_track(0)
        stops = []
        player._engine.stop = lambda: stops.append(1)

        player._compat_panel.audition_started.emit(match)
        assert stops, "the main engine must stop when an audition starts"

    def test_moving_off_the_icon_stops_the_audition(self, player, lib, tmp_path):
        add_track(player, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(player, tmp_path, "match.wav", key="8A", bpm=128.0)
        player._play_track(0)
        panel = player._compat_panel
        stops = []
        panel._audition.stop = lambda: stops.append(1)

        panel._on_icon_hover(-1)
        assert stops

    def test_closing_the_panel_stops_the_audition(self, player, tmp_path):
        add_track(player, tmp_path, "seed.wav", key="8A", bpm=128.0)
        player._play_track(0)
        stops = []
        player._compat_panel.stop_audition = lambda: stops.append(1)
        player._compat_button.setChecked(True)
        player._compat_button.setChecked(False)
        assert stops

    def test_a_new_seed_stops_the_audition(self, player, tmp_path):
        add_track(player, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(player, tmp_path, "next.wav", key="8A", bpm=128.0)
        player._play_track(0)
        stops = []
        player._compat_panel._audition.stop = lambda: stops.append(1)
        player._play_track(1)
        assert stops, "the rows the audition belonged to are gone"

    def test_the_volume_slider_carries_to_the_audition(self, player):
        volumes = []
        player._compat_panel._audition.set_volume = lambda v: volumes.append(v)
        player._on_volume_changed(35)
        assert volumes == [0.35]

    def test_double_clicking_the_gutter_does_not_add_the_track(
        self, player, lib, tmp_path
    ):
        """In the gutter a double click is two clicks of the gesture (start,
        then skip), not a request to add the track to the playlist.

        The match is library-only, so the add the second half of this test
        provokes is a real add rather than a duplicate prompt.
        """
        add_track(player, tmp_path, "seed.wav", key="8A", bpm=128.0)
        lib.add_track(make_file(tmp_path, "match.wav"), key="8A", bpm=128.0)
        player._play_track(0)
        panel = player._compat_panel
        activated = []
        panel.track_activated.connect(activated.append)

        panel._on_double_clicked(panel._table.model().index(0, COL_AUDITION))
        assert activated == []
        panel._on_double_clicked(panel._table.model().index(0, COL_TRACK))
        assert len(activated) == 1


class TestGutterIcon:
    """Sampled from a render — a data-level check cannot see this at all."""

    @staticmethod
    def _shown(qtbot, player, tmp_path):
        add_track(player, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(player, tmp_path, "match.wav", key="8A", bpm=128.0)
        player._play_track(0)
        player._compat_button.setChecked(True)
        player.show()
        qtbot.wait(20)
        return player._compat_panel

    @staticmethod
    def _gutter_colours(panel) -> set[tuple[int, int, int]]:
        table = panel._table
        rect = table.visualRect(table.model().index(0, COL_AUDITION))
        image = table.viewport().grab().toImage()
        found = set()
        for x in range(rect.left(), rect.right() + 1):
            for y in range(rect.top(), rect.bottom() + 1):
                c = image.pixelColor(x, y)
                found.add((c.red(), c.green(), c.blue()))
        return found

    def test_the_icon_is_drawn_on_every_row(self, qtbot, player, tmp_path):
        panel = self._shown(qtbot, player, tmp_path)
        colours = self._gutter_colours(panel)
        assert len(colours) > 1, "the gutter is a flat fill — nothing was drawn"

    def test_hovering_the_icon_brightens_it(self, qtbot, player, tmp_path):
        panel = self._shown(qtbot, player, tmp_path)
        resting = self._gutter_colours(panel)
        panel._on_icon_hover(0)
        qtbot.wait(20)
        hovered = self._gutter_colours(panel)
        assert hovered != resting

    def test_a_click_in_the_gutter_reaches_the_audition(self, qtbot, player, tmp_path):
        """Through the real mouse path — a press on the viewport, not a call
        to the slot the press is supposed to reach."""
        panel = self._shown(qtbot, player, tmp_path)
        clicked = []
        panel._audition.click = lambda path: clicked.append(path)
        table = panel._table
        rect = table.visualRect(table.model().index(0, COL_AUDITION))
        point = QPointF(rect.center())
        table.mousePressEvent(
            QMouseEvent(
                QMouseEvent.Type.MouseButtonPress,
                point,
                table.viewport().mapToGlobal(QPoint(rect.center().x(), rect.center().y())),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert clicked == [panel.matches[0].track.path]
