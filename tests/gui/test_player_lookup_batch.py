"""Batch lookup from the playlist: the queue, the paging, and what it writes.

No test here touches the network — the provider is replaced wholesale. What is
under test is the batch's own behaviour: which rows become jobs, what Skip and
Stop mean, which rows get refreshed afterwards, and what the run says at the
end.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QMessageBox

import src.gui.widgets.player_panel as player_module
from src.gui.widgets.dialogs.lookup_review import STOP_RESULT, LookupReviewDialog
from src.gui.widgets.player_panel import PlayerPanel
from src.library import Library
from src.metadata.tags import read_metadata
from src.online.result import Candidate, ProposedTags


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "library.db")
    yield library
    library.close()


@pytest.fixture
def tracks(tmp_path):
    """Three real FLACs whose names parse to artist/title, and no tags at all."""
    sf = pytest.importorskip("soundfile")
    paths = []
    for i, name in enumerate(
        ["Underworld - Born Slippy", "Orbital - Halcyon", "Phuture - Acid Tracks"]
    ):
        path = tmp_path / f"{name}.flac"
        sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
        paths.append(str(path))
    return paths


@pytest.fixture
def player(qtbot, lib, tracks):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    panel.set_library(lib)
    panel.add_tracks(
        [{"file_path": p, "display_name": Path(p).name} for p in tracks]
    )
    panel.set_online_lookup(True, token="tok")
    return panel


class StubProvider:
    """Answers every fetch with a title built from the query, and counts calls."""

    instances: list["StubProvider"] = []

    def __init__(self, token=""):
        self.token = token
        self.on_wait = None
        self.searched = []
        StubProvider.instances.append(self)

    def search(self, query, limit=25):
        self.searched.append(query)
        if query.title == "Halcyon":
            return []  # this one has no match, to exercise the failure path
        return [Candidate(release_id=1, artist=query.artist, album="An Album")]

    def fetch(self, candidate, query):
        candidate.score = 0.95
        return ProposedTags(
            title=f"{query.title} (Nuxx)", artist=query.artist, provider="discogs"
        )

    def fetch_artwork(self, url):
        return b""


@pytest.fixture
def stub_provider(monkeypatch):
    StubProvider.instances = []
    monkeypatch.setattr(player_module, "DiscogsProvider", StubProvider)
    return StubProvider


def _run(qtbot, player, row=0):
    """Kick off a batch and wait for the queue to drain."""
    player._lookup_selected_online(row)
    qtbot.waitUntil(lambda: player._lookup_thread is None, timeout=5000)
    qtbot.wait(10)


def _approve_all(monkeypatch):
    def approve(self):
        self._select_all()
        return 1

    monkeypatch.setattr(LookupReviewDialog, "exec", approve)


def _silence_summary(monkeypatch) -> list[str]:
    said: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args, **kw: said.append(args[2])
    )
    return said


# --- the entry point --------------------------------------------------------


def test_the_menu_entry_appears_only_when_the_setting_is_on(qtbot, player):
    entry = player._playlist[0]

    player.set_online_lookup(False)
    _, off = player._build_row_menu(entry)
    player.set_online_lookup(True, token="tok")
    _, on = player._build_row_menu(entry)

    assert "lookup" not in off
    assert "Look Up Online" in on["lookup"].text()


def test_the_selection_is_the_queue(qtbot, player, stub_provider, monkeypatch):
    _approve_all(monkeypatch)
    _silence_summary(monkeypatch)
    player._table.selectRow(0)
    player._table.selectRow(2)  # replaces the selection — one row
    _run(qtbot, player, row=2)
    assert len(stub_provider.instances[0].searched) == 1


def test_a_right_click_outside_the_selection_acts_on_that_row_alone(
    qtbot, player, stub_provider, monkeypatch
):
    _approve_all(monkeypatch)
    _silence_summary(monkeypatch)
    player._table.selectRow(0)
    _run(qtbot, player, row=2)  # right-clicked row 2, which is not selected
    searched = stub_provider.instances[0].searched
    assert [q.title for q in searched] == ["Acid Tracks"]


def test_rows_with_nothing_to_search_on_never_reach_the_network(
    qtbot, player, stub_provider, monkeypatch, tmp_path
):
    sf = pytest.importorskip("soundfile")
    blank = tmp_path / "track01.flac"
    sf.write(str(blank), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
    player.add_tracks([{"file_path": str(blank), "display_name": blank.name}])
    said = _silence_summary(monkeypatch)
    row = player._row_for_path(str(blank))
    player._lookup_selected_online(row)
    # No thread at all: there was nothing to queue.
    assert player._lookup_thread is None
    assert said and "artist or title" in said[0]


# --- paging through the results --------------------------------------------


def test_approving_writes_the_tags_and_refreshes_the_row(
    qtbot, player, stub_provider, monkeypatch, tracks
):
    _approve_all(monkeypatch)
    _silence_summary(monkeypatch)
    _run(qtbot, player, row=0)
    assert read_metadata(tracks[0]).title == "Born Slippy (Nuxx)"
    # The visible row reflects the write without anyone pressing Reload.
    assert player._playlist[0].title == "Born Slippy (Nuxx)"


def test_skip_leaves_that_file_alone_and_continues(
    qtbot, player, stub_provider, monkeypatch, tracks
):
    seen: list[str] = []

    def skip_first(self):
        seen.append(self._file_path)
        if len(seen) == 1:
            return 0  # Rejected — skip this one
        self._select_all()
        return 1

    monkeypatch.setattr(LookupReviewDialog, "exec", skip_first)
    _silence_summary(monkeypatch)
    player._table.selectAll()
    _run(qtbot, player, row=0)

    assert read_metadata(tracks[0]).title is None       # skipped
    assert read_metadata(tracks[2]).title == "Acid Tracks (Nuxx)"  # reviewed after


def test_stop_abandons_the_rest_of_the_queue(
    qtbot, player, stub_provider, monkeypatch, tracks
):
    seen: list[str] = []

    def stop_after_first(self):
        seen.append(self._file_path)
        return STOP_RESULT

    monkeypatch.setattr(LookupReviewDialog, "exec", stop_after_first)
    _silence_summary(monkeypatch)
    player._table.selectAll()
    _run(qtbot, player, row=0)

    assert len(seen) == 1  # the second file's dialog never opened
    assert read_metadata(tracks[2]).title is None


def test_the_dialog_says_where_it_is_in_the_batch(
    qtbot, player, stub_provider, monkeypatch
):
    positions: list = []

    def record(self):
        positions.append(self._position)
        return 0

    monkeypatch.setattr(LookupReviewDialog, "exec", record)
    _silence_summary(monkeypatch)
    player._table.selectAll()
    _run(qtbot, player, row=0)
    # Two of the three files matched (Halcyon deliberately does not), and the
    # counter counts the reviewable ones, not the queue.
    assert positions == [(1, 2), (2, 2)]


def test_a_row_removed_while_the_queue_ran_is_not_reviewed(
    qtbot, player, stub_provider, monkeypatch, tracks
):
    opened: list[str] = []

    def record(self):
        opened.append(self._file_path)
        return 0

    monkeypatch.setattr(LookupReviewDialog, "exec", record)
    _silence_summary(monkeypatch)

    real_review = PlayerPanel._review_lookup_results

    def drop_then_review(self, results, skipped):
        # The user removed the first track while the lookups were running.
        del self._playlist[0]
        return real_review(self, results, skipped)

    monkeypatch.setattr(PlayerPanel, "_review_lookup_results", drop_then_review)
    player._table.selectAll()
    _run(qtbot, player, row=0)
    assert tracks[0] not in opened


# --- what the run says at the end ------------------------------------------


def test_a_run_with_nothing_to_report_stays_quiet(
    qtbot, player, stub_provider, monkeypatch
):
    _approve_all(monkeypatch)
    said = _silence_summary(monkeypatch)
    player._table.selectRow(0)  # the one file that matches
    _run(qtbot, player, row=0)
    assert said == []


def test_unmatched_files_are_named_at_the_end(
    qtbot, player, stub_provider, monkeypatch
):
    _approve_all(monkeypatch)
    said = _silence_summary(monkeypatch)
    player._table.selectAll()
    _run(qtbot, player, row=0)
    assert said and "Halcyon" in said[0]


def test_the_rate_limit_pause_reaches_the_progress_dialog(qtbot, player):
    from PySide6.QtWidgets import QProgressDialog

    progress = QProgressDialog("x", "y", 0, 3, player)
    qtbot.addWidget(progress)
    player._lookup_progress = progress
    player._on_lookup_waiting(5.0)
    assert "rate limit" in progress.labelText().lower()
    player._lookup_progress = None


# --- the release memory (schema v6) ----------------------------------------
#
# Until this batch the Metadata panel was the *only* writer of
# `tracks.discogs_release_id`, so a track tagged from the playlist came back to
# the Discogs tab as "No release known for this file yet" over tags it had just
# taken from a release. Same family as the two bugs the D queue already
# documents: one path fills something in, another reuses the result and
# inherits only what the first path happened to store.


def test_approving_records_the_release_it_came_from(
    qtbot, player, stub_provider, monkeypatch, tracks, lib
):
    _approve_all(monkeypatch)
    _silence_summary(monkeypatch)
    _run(qtbot, player, row=0)
    assert lib.get_track_by_path(tracks[0]).discogs_release_id == 1


def test_skipping_records_nothing(
    qtbot, player, stub_provider, monkeypatch, tracks, lib
):
    monkeypatch.setattr(LookupReviewDialog, "exec", lambda self: 0)
    _silence_summary(monkeypatch)
    _run(qtbot, player, row=0)
    assert lib.get_track_by_path(tracks[0]).discogs_release_id is None


def test_a_remembered_release_seeds_the_next_lookup(
    qtbot, player, monkeypatch, tracks, lib
):
    """The switcher opens on the user's own answer, not on the ranking again."""
    captured: list = []
    monkeypatch.setattr(
        PlayerPanel,
        "_start_lookup_queue",
        lambda self, jobs, skipped: captured.extend(jobs),
    )
    lib.set_release_id(lib.get_track_by_path(tracks[0]).id, 249504)
    player._lookup_selected_online(0)
    assert [job.prefer_release_id for job in captured] == [249504]


# --- the release switcher, which this batch wired up -----------------------


class TwoPressings(StubProvider):
    """Two candidates, and a fetch whose album names the one it was given."""

    def search(self, query, limit=25):
        self.searched.append(query)
        return [
            Candidate(release_id=1, artist=query.artist, album="First Pressing"),
            Candidate(release_id=2, artist=query.artist, album="Reissue"),
        ]

    def fetch(self, candidate, query):
        candidate.score = 0.95
        candidate.album = "First Pressing" if candidate.release_id == 1 else "Reissue"
        return ProposedTags(
            title=f"{query.title} (Nuxx)",
            artist=query.artist,
            album=candidate.album,
            provider="discogs",
        )


@pytest.fixture
def two_pressings(monkeypatch):
    TwoPressings.instances = []
    monkeypatch.setattr(player_module, "DiscogsProvider", TwoPressings)
    return TwoPressings


def test_switching_release_re_reads_that_release_and_applies_it(
    qtbot, player, two_pressings, monkeypatch, tracks, lib
):
    """The combo was drawn and never wired: it moved, and Apply wrote the old one."""

    def switch_then_approve(self):
        self.candidate_requested.emit(self._candidate_combo.itemData(1))
        qtbot.waitUntil(lambda: player._lookup_thread is None, timeout=5000)
        qtbot.wait(10)
        self._select_all()
        return 1

    monkeypatch.setattr(LookupReviewDialog, "exec", switch_then_approve)
    _silence_summary(monkeypatch)
    _run(qtbot, player, row=0)
    # The second pressing's values, and the second pressing remembered — not
    # the one the automatic match opened on.
    assert read_metadata(tracks[0]).album == "Reissue"
    assert lib.get_track_by_path(tracks[0]).discogs_release_id == 2


def test_a_switch_that_fails_puts_the_combo_back(
    qtbot, player, two_pressings, monkeypatch, tracks
):
    """A combo naming a release the fields do not describe is the original bug."""
    warned: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kw: warned.append(args[2])
    )
    _silence_summary(monkeypatch)

    def boom(self, candidate, query):
        raise RuntimeError("no")

    def switch_then_skip(self):
        monkeypatch.setattr(TwoPressings, "fetch", boom)
        self.candidate_requested.emit(self._candidate_combo.itemData(1))
        qtbot.waitUntil(lambda: player._lookup_thread is None, timeout=5000)
        qtbot.wait(10)
        # Back on the release actually on screen, not the one we could not read.
        assert self._candidate_combo.currentIndex() == 0
        return 0

    monkeypatch.setattr(LookupReviewDialog, "exec", switch_then_skip)
    _run(qtbot, player, row=0)
    assert warned
