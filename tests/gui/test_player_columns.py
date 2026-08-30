"""Optional Player columns: what shows, what persists, what upgrades cleanly.

Nine columns join the shipped nine (eight of data, plus Art — see
test_player_artwork.py for what that one carries), hidden until asked for from the header's
right-click menu. Most of the risk is not in showing them — it is in what a
*saved* header state means once the table is wider than the state is.

The trap, measured rather than assumed: Qt accepts a nine-column state into
this wider table (it returns True and applies the nine), but what
becomes of the sections the state never knew about is unspecified — and
observably inconsistent. A bare QTableWidget has them un-hidden by the
restore; this panel's header keeps the flag it was given. Neither behaviour
is relied on: `player_column_count` records what the state covers and
`_restore_column_state` applies visibility for the rest afterwards.

So the tests below assert the *invariant* — an upgrading user gets no columns
they did not ask for, and a saved choice is honoured — rather than the
mechanism, because the mechanism is exactly the part Qt does not promise.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QTableWidget

from src.gui.widgets.player_panel import PlayerPanel
from src.library import Library
from src.utils.config import AppConfig, load_config, save_config

FIRST_OPTIONAL = 9
TOTAL_COLUMNS = 18


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "library.db")
    yield library
    library.close()


def make_player(qtbot, lib=None):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    if lib is not None:
        panel.set_library(lib)
    return panel


@pytest.fixture
def player(qtbot, lib):
    return make_player(qtbot, lib)


class TestTheColumnSet:
    def test_the_original_nine_keep_their_indexes(self, player):
        """A saved header state addresses sections by number, so inserting a
        column anywhere before index 9 would re-point every existing user's
        widths and order at the wrong columns."""
        labels = [
            player._table.horizontalHeaderItem(c).text() for c in range(9)
        ]
        assert labels == [
            "#", "Filename", "Artist", "Title", "BPM", "Key", "Comment",
            "Duration", "Year",
        ]

    def test_the_optional_ones_are_appended_after_them(self, player):
        assert player._table.columnCount() == TOTAL_COLUMNS
        assert [c for c, _ in player._OPTIONAL_COLUMNS] == list(
            range(FIRST_OPTIONAL, TOTAL_COLUMNS)
        )

    def test_they_start_hidden_except_art(self, player):
        """Art is the one optional column shipped visible — it says what a
        track is at a glance, which none of the others do."""
        for col, _ in player._OPTIONAL_COLUMNS:
            if col in player._DEFAULT_SHOWN_OPTIONAL:
                assert not player._table.isColumnHidden(col), col
            else:
                assert player._table.isColumnHidden(col), col

    def test_art_is_the_only_one_of_them(self, player):
        assert player._DEFAULT_SHOWN_OPTIONAL == frozenset({player._ARTWORK_COLUMN})

    def test_the_shipped_nine_start_visible(self, player):
        for col in range(9):
            assert not player._table.isColumnHidden(col), col

    def test_filename_and_the_number_column_cannot_be_hidden(self, player):
        """One is the row's identity; the other doubles as the membership
        count during an All-playlists search. A table with neither is
        unreadable."""
        assert player._LOCKED_COLUMNS == {0, 1}


class TestTheHeaderMenu:
    def _menu_actions(self, player, qtbot):
        """The menu is built and inspected, never exec'd: a modal nothing
        clicks blocks the whole suite forever (it did, once)."""
        menu = player._build_column_menu()
        qtbot.addWidget(menu)
        return list(menu.actions())

    def test_it_offers_every_unlocked_column(self, player, qtbot):
        actions = self._menu_actions(player, qtbot)

        toggles = [a for a in actions if a.isCheckable()]
        assert len(toggles) == TOTAL_COLUMNS - len(player._LOCKED_COLUMNS)
        labels = [a.text() for a in toggles]
        assert "Filename" not in labels and "#" not in labels
        assert {"Album", "Genre", "Track #", "Label", "Bitrate", "Energy",
                "Art", "Date Added", "Date Created"} <= set(labels)

    def test_the_checkmarks_report_the_current_state(self, player, qtbot):
        actions = self._menu_actions(player, qtbot)
        by_label = {a.text(): a for a in actions}

        assert by_label["Artist"].isChecked()
        assert not by_label["Album"].isChecked()

    def test_showing_a_column_reveals_it(self, player):
        player._set_column_visible(9, True)

        assert not player._table.isColumnHidden(9)

    def test_hiding_one_puts_it_away_again(self, player):
        player._set_column_visible(9, True)
        player._set_column_visible(9, False)

        assert player._table.isColumnHidden(9)

    def test_a_revealed_column_is_never_zero_wide(self, player):
        """A section hidden at zero width comes back invisible, which reads
        as the menu not working."""
        player._table.setColumnWidth(9, 0)

        player._set_column_visible(9, True)

        assert player._table.columnWidth(9) > 0


class TestPersistence:
    def test_a_shown_column_survives_a_relaunch(self, qtbot, lib):
        player = make_player(qtbot, lib)
        player._set_column_visible(9, True)
        player._save_column_state()

        again = make_player(qtbot, lib)

        assert not again._table.isColumnHidden(9)

    def test_a_hidden_one_stays_hidden(self, qtbot, lib):
        player = make_player(qtbot, lib)
        player._set_column_visible(9, True)
        player._set_column_visible(9, False)
        player._save_column_state()

        again = make_player(qtbot, lib)

        assert again._table.isColumnHidden(9)

    def test_the_column_count_is_saved_with_the_state(self, qtbot, lib):
        player = make_player(qtbot, lib)
        player._save_column_state()

        assert load_config().player_column_count == TOTAL_COLUMNS

    def test_a_toggle_during_a_search_is_not_lost(self, qtbot, lib):
        """Saving is suppressed mid-search because '#' wears a temporary
        width then — but the user's choice must outlive the search."""
        player = make_player(qtbot, lib)
        player._search_active = True
        player._set_count_column(True)

        player._set_column_visible(9, True)
        assert not player._col_save_timer.isActive(), "should be deferred"

        player._search_active = False
        player._set_count_column(False)

        assert player._col_save_timer.isActive(), "the deferred save never fired"


class TestUpgradingFromNineColumns:
    """Someone with a layout saved before these columns existed."""

    def _save_nine_column_state(self):
        """A state exactly as a build before this change would have left it."""
        table = QTableWidget(0, 9)
        table.setColumnWidth(1, 329)
        state = bytes(
            table.horizontalHeader().saveState().toBase64()
        ).decode("ascii")
        cfg = AppConfig()
        cfg.player_column_state = state
        cfg.player_column_count = 0  # older builds never wrote one
        # Already migrated to the current defaults. Without this the one-time
        # layout migration discards the state before _normalize_header ever
        # sees it, and these tests would pass while testing nothing — the
        # short-state handling stays live for the *next* column added.
        cfg.player_column_defaults_version = PlayerPanel._COLUMN_DEFAULTS_VERSION
        save_config(cfg)

    def test_the_new_columns_take_their_defaults(self, qtbot, lib):
        """A nine-column state has no opinion about the columns that came
        later, so each one takes its shipped default — which for everything
        except Art is hidden. What must never happen is Qt's un-hiding of
        sections the state predates deciding this instead."""
        self._save_nine_column_state()

        player = make_player(qtbot, lib)

        for col, _ in player._OPTIONAL_COLUMNS:
            assert player._table.isColumnHidden(col) is (
                col not in player._DEFAULT_SHOWN_OPTIONAL
            ), f"column {col} did not take its default visibility"

    def test_the_saved_widths_are_still_honoured(self, qtbot, lib):
        """The upgrade must not cost the user their existing layout."""
        self._save_nine_column_state()

        player = make_player(qtbot, lib)

        assert player._table.columnWidth(1) == 329

    def test_the_upgraded_layout_can_be_saved_and_read_back(self, qtbot, lib):
        """The bug a single launch cannot show, and the reason
        `_normalize_header` exists.

        A header that has swallowed a shorter state is left internally
        inconsistent: everything looks right, and then the state it *saves*
        is refused by restoreState. So the first run after upgrading wrote a
        poisoned layout and the second run threw it away — taking the user's
        widths and any column they had switched on with it.
        """
        self._save_nine_column_state()

        first = make_player(qtbot, lib)
        first._set_column_visible(9, True)
        first._save_column_state()

        second = make_player(qtbot, lib)

        assert second._table.columnWidth(1) == 329, "the upgraded layout was lost"
        assert not second._table.isColumnHidden(9), "the column choice was lost"

    def test_the_saved_order_survives_the_upgrade_too(self, qtbot, lib):
        """_normalize_header re-applies order as well as widths — a user who
        had dragged Year next to Artist keeps it there."""
        table = QTableWidget(0, 9)
        table.horizontalHeader().moveSection(8, 2)
        cfg = AppConfig()
        cfg.player_column_state = bytes(
            table.horizontalHeader().saveState().toBase64()
        ).decode("ascii")
        cfg.player_column_count = 0
        cfg.player_column_defaults_version = PlayerPanel._COLUMN_DEFAULTS_VERSION
        save_config(cfg)

        player = make_player(qtbot, lib)

        assert player._table.horizontalHeader().visualIndex(8) == 2

    def test_a_shorter_state_is_accepted_rather_than_refused(self, qtbot):
        """Which is why `player_column_count` has to exist at all: a refusal
        would have been self-announcing, and this is silent."""
        table = QTableWidget(0, 9)
        table.setColumnWidth(1, 329)
        old_state = table.horizontalHeader().saveState()

        wider = QTableWidget(0, TOTAL_COLUMNS)
        restored = wider.horizontalHeader().restoreState(old_state)

        assert restored is True
        assert wider.columnWidth(1) == 329, "the nine it knows were applied"

    def test_hiding_before_the_restore_is_not_dependable(self, qtbot):
        """The reason visibility is applied *after* restoring, and the reason
        no test here asserts the mechanism.

        In a plain QTableWidget the restore drops the hidden flag on every
        section the state predates. This panel's header happens not to. Both
        were measured; Qt promises neither.
        """
        # Held in a local: a temporary QTableWidget is collected the moment
        # the expression ends, taking its header with it.
        narrow = QTableWidget(0, 9)
        old_state = narrow.horizontalHeader().saveState()

        wider = QTableWidget(0, TOTAL_COLUMNS)
        for col in range(FIRST_OPTIONAL, TOTAL_COLUMNS):
            wider.setColumnHidden(col, True)
        wider.horizontalHeader().restoreState(old_state)

        assert not wider.isColumnHidden(FIRST_OPTIONAL), (
            "Qt now preserves the flag — hide-before-restore would work, but "
            "applying it afterwards is still correct and still cheaper to reason about"
        )


class TestClosingTheWindowFlushesThePendingSave:
    """Quitting inside the 600 ms debounce must not lose the change.

    `PlayerPanel.closeEvent` flushes for exactly that — and it was dead on the
    only path the app closes by. Qt delivers a QCloseEvent to the widget being
    closed and does NOT propagate it to children, so closing the main window
    never reached the panel's closeEvent: a column dragged and then quit on
    came back at its shipped default next launch (measured: 321px -> 180px).
    The flush had been written, and tested at the panel, where it does run.

    The suite half is the documented one: a pending save resolves its app-data
    directory when it *fires*, so one left armed by a MainWindow test lands in
    the next test's isolated config. That is how this was found — new tests
    that build a MainWindow poisoned an unrelated search test after them.
    """

    def test_closing_the_window_writes_a_pending_column_change(self, qtbot):
        from src.gui.main_window import MainWindow

        win = MainWindow()
        qtbot.addWidget(win)
        player = win._player_panel
        player._table.setColumnWidth(2, 321)
        assert player._col_save_timer.isActive(), (
            "nothing was pending, so this would pass against the bug"
        )

        win.close()

        # The invariant, not a race with the timer: nothing is still owed.
        assert not player._col_save_timer.isActive()
        player.shutdown_workers()

        next_launch = make_player(qtbot)
        assert next_launch._table.columnWidth(2) == 321
        next_launch.shutdown_workers()


class TestTheWindowDoesNotClobberIt:
    """`MainWindow._persist_config` re-reads the fields panels own before it
    writes its own startup snapshot back. The column state was on that list;
    the count that goes with it was not, so closing the window reverted the
    count while keeping the state — and the next launch read a fifteen-column
    state as covering nine columns. Silent, and one launch removed from the
    action that caused it.
    """

    def test_closing_the_window_keeps_both_halves(self, qtbot, lib, tmp_path):
        from src.gui.main_window import MainWindow

        class WindowStub:
            _persist_config = MainWindow._persist_config

            def __init__(self, config):
                self._config = config

        # The window's startup snapshot: taken before the panel saved anything.
        startup = load_config()
        player = make_player(qtbot, lib)
        player._set_column_visible(9, True)
        player._save_column_state()
        assert load_config().player_column_count == TOTAL_COLUMNS

        WindowStub(startup)._persist_config()

        saved = load_config()
        assert saved.player_column_count == TOTAL_COLUMNS, (
            "the count was reverted to the window's stale startup value"
        )
        assert saved.player_column_state == load_config().player_column_state

    def test_and_the_choice_really_comes_back(self, qtbot, lib):
        """The same thing end to end, which is how it was found: the failure
        only shows on the launch *after* the one that saved."""
        from src.gui.main_window import MainWindow

        class WindowStub:
            _persist_config = MainWindow._persist_config

            def __init__(self, config):
                self._config = config

        startup = load_config()
        first = make_player(qtbot, lib)
        first._set_column_visible(9, True)
        first._save_column_state()
        WindowStub(startup)._persist_config()  # window closes

        second = make_player(qtbot, lib)

        assert not second._table.isColumnHidden(9)


class TestARefusedState:
    def test_defaults_come_back_rather_than_a_half_restored_header(
        self, qtbot, lib
    ):
        cfg = AppConfig()
        cfg.player_column_state = bytes(
            QByteArray(b"not a header state").toBase64()
        ).decode("ascii")
        cfg.player_column_count = TOTAL_COLUMNS
        save_config(cfg)

        player = make_player(qtbot, lib)

        assert player._table.columnWidth(1) == 300  # the default Filename width
        for col, _ in player._OPTIONAL_COLUMNS:
            assert player._table.isColumnHidden(col) is (
                col not in player._DEFAULT_SHOWN_OPTIONAL
            ), col


class TestTheDataReachesThem:
    def test_every_optional_column_shows_its_field(self, player, qtbot, tmp_path):
        sf = pytest.importorskip("soundfile")
        import numpy as np

        from src.metadata.tags import TrackMetadata, write_energy, write_metadata

        path = tmp_path / "full.flac"
        sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
        write_metadata(
            str(path),
            TrackMetadata(
                artist="Photek", title="Ni Ten Ichi Ryu", album="Modus Operandi",
                genre="Drum & Bass", year=1997, track_number=3, label="Science",
            ),
        )
        write_energy(str(path), 6)

        player.add_tracks(
            [{"file_path": str(path), "display_name": path.name}],
            allow_duplicates=True,
        )
        qtbot.wait(10)

        # Art is excluded: it carries a thumbnail, not text, and is covered
        # in test_player_artwork.py.
        shown = {
            player._table.horizontalHeaderItem(col).text():
                player._table.item(0, col).text()
            for col, attribute in player._OPTIONAL_COLUMNS
            if attribute is not None
        }
        # The two dates are asserted by shape rather than by value — they say
        # when this ran — and in full in test_player_date_columns.py.
        dates = {
            shown.pop("Date Added"),
            shown.pop("Date Created"),
        }
        assert shown == {
            "Album": "Modus Operandi",
            "Genre": "Drum & Bass",
            "Track #": "3",
            "Label": "Science",
            "Bitrate": "706",
            "Energy": "6",
        }
        assert all(re.fullmatch(r"\d{4}-\d\d-\d\d", d) for d in dates), dates

    def test_the_cells_exist_even_while_hidden(self, player, qtbot, tmp_path):
        """Built regardless of visibility, so unhiding one shows its data
        straight away instead of after the next rebuild."""
        path = tmp_path / "x.flac"
        pytest.importorskip("soundfile")
        import numpy as np
        import soundfile as sf

        sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
        player.add_tracks(
            [{"file_path": str(path), "display_name": path.name}],
            allow_duplicates=True,
        )
        qtbot.wait(10)

        assert player._table.isColumnHidden(9)
        assert player._table.item(0, 9) is not None

    def test_they_are_not_editable(self, player, qtbot, tmp_path):
        """The editable set is a deliberate list; widening it is its own
        conversation."""
        from PySide6.QtCore import Qt

        path = tmp_path / "y.flac"
        pytest.importorskip("soundfile")
        import numpy as np
        import soundfile as sf

        sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
        player.add_tracks(
            [{"file_path": str(path), "display_name": path.name}],
            allow_duplicates=True,
        )
        qtbot.wait(10)

        for col, _ in player._OPTIONAL_COLUMNS:
            flags = player._table.item(0, col).flags()
            assert not (flags & Qt.ItemFlag.ItemIsEditable), col
        assert col not in player._EDITABLE_COLUMNS


class TestTranslatedHeadersFit:
    """A default width measured against an English label is not a width.

    The seven optional columns shipped with fixed defaults — Track # at 70px,
    Bitrate and Art at 80 — and the translations authored for them do not fit:
    ru "Номер трека" wants 97px, ja ビットレート 95, ja アートワーク 95. Six of the
    eleven languages opened one of these clipped, and it is the *default* that
    is wrong, so it happened on the first reveal rather than after some
    unusual sequence.

    Asserted against the panel's own measurement rather than a pixel count:
    the suite runs with no application stylesheet, so a number written here
    would describe a header the app never paints (see CLAUDE.md). What must
    hold in any font is that the default is at least the width the header
    word needs.
    """

    FIXED_OPTIONAL = (11, 13, 15)  # Track #, Bitrate, Art — the tight ones

    def test_the_floor_never_narrows_a_base_width(self, player):
        """It may only widen — a column's base is a floor, not a target.

        Deliberately not asserted as *equality* for the English labels, even
        though that is what the running app does (Track # measures 57px of
        its 70 under the real stylesheet). The suite has no application
        stylesheet, so the same label measures 71px in Fusion's default font
        and the floor engages here for a reason that does not exist in the
        app. Equality would be a true statement about the wrong header.
        """
        for col, base in player._BASE_COLUMN_WIDTHS.items():
            assert player._default_column_widths[col] >= base

    def test_every_column_defaults_wide_enough_for_its_own_header(self, player):
        for col in range(player._table.columnCount()):
            assert player._default_column_widths[col] >= player._header_fit_width(col), (
                player._table.horizontalHeaderItem(col).text()
            )

    def test_a_label_longer_than_its_base_widens_the_default(self, player):
        """What ru does to Track #, done to a column whose base is fixed."""
        player._table.horizontalHeaderItem(11).setText("Номер трека вообще")
        player._apply_header_fit_floor()

        assert player._default_column_widths[11] > player._BASE_COLUMN_WIDTHS[11]
        assert player._default_column_widths[11] >= player._header_fit_width(11)

    def test_the_floor_is_recomputed_and_not_ratcheted(self, player):
        """Measured from the base each time, so a header that gets *shorter*
        (a smaller text size, a re-translation) gives the width back rather
        than keeping the widest it ever was."""
        player._table.horizontalHeaderItem(13).setText("Eine sehr lange Bezeichnung")
        player._apply_header_fit_floor()
        widened = player._default_column_widths[13]
        assert widened > player._BASE_COLUMN_WIDTHS[13]

        player._table.horizontalHeaderItem(13).setText("Bitrate")
        player._apply_header_fit_floor()
        # Back to what a fresh measurement gives — NOT to the base, which is a
        # floor and not the answer. Whether the English word clears it is a fact
        # about the font the suite happens to run in, exactly as
        # test_the_floor_never_narrows_a_base_width says: "Bitrate" fits inside
        # the 80px base under the offscreen font on macOS and measures 104px
        # under the one on Windows, so equality-with-base is a true statement
        # about one platform's header only. A ratcheting implementation fails
        # both halves below, which is what this test is here for.
        assert player._default_column_widths[13] < widened
        assert player._default_column_widths[13] == max(
            player._BASE_COLUMN_WIDTHS[13], player._header_fit_width(13)
        )

    def test_the_artwork_column_keeps_room_for_its_own_header(self, player):
        """Art's width comes from the band, not from a constant — so the band
        is what would strand a long label (ja アートワーク) if the two did not
        both get a say."""
        player._table.horizontalHeaderItem(15).setText("アートワーク")
        player._apply_art_icon_size()

        assert player._default_column_widths[15] >= player._header_fit_width(15)

    def test_a_visible_column_narrower_than_its_word_is_pushed_back_out(self, player):
        player._table.setColumnHidden(11, False)
        player._table.setColumnWidth(11, 20)
        player._table.horizontalHeaderItem(11).setText("Номер трека")
        player._apply_header_fit_floor()

        assert player._table.columnWidth(11) >= player._header_fit_width(11)


class TestFitToLongest:
    """One column, sized to the longest value it *currently* holds.

    Deliberately one shot. A width that kept tracking the contents would move
    under the user every time a playlist grew, and the header is Interactive
    precisely so the width is theirs — so a longer track added afterwards
    clips until they ask again.
    """

    def add(self, player, name: str) -> None:
        player.add_tracks(
            [{"file_path": f"/tmp/{name}", "display_name": name}],
            allow_duplicates=True,
        )

    def fit_action(self, player, qtbot, col: int):
        menu = player._build_column_menu(col)
        qtbot.addWidget(menu)
        return next(
            (a for a in menu.actions() if a.text().startswith("Fit ")), None
        )

    def test_the_menu_offers_it_for_the_column_it_was_opened_on(self, player, qtbot):
        action = self.fit_action(player, qtbot, 1)

        assert action is not None
        # Named, because everything else in this menu is about all the columns
        # at once and this one is not.
        assert action.text() == "Fit Filename to Longest"

    def test_a_right_click_past_the_last_section_offers_nothing_to_fit(
        self, player, qtbot
    ):
        """`logicalIndexAt` answers -1 there, which must not become column 0
        or a crash."""
        assert self.fit_action(player, qtbot, -1) is None

    @pytest.mark.parametrize("col", sorted(PlayerPanel._UNFITTABLE_COLUMNS))
    def test_the_two_columns_it_cannot_measure_are_not_offered(
        self, player, qtbot, col
    ):
        """'#' is the one Fixed section (and the count column during an
        All-playlists search); Art's band follows the row height, so there is
        nothing in its cells to measure."""
        assert self.fit_action(player, qtbot, col) is None

    def test_it_widens_a_column_to_show_its_longest_value(self, player, qtbot):
        self.add(player, "short.mp3")
        self.add(player, "a considerably longer filename than the column.mp3")
        player._table.setColumnWidth(1, 60)

        self.fit_action(player, qtbot, 1).trigger()

        # Asked of the style, through the path that paints the cell — a
        # hand-written `font metrics + a pad` is right on at most one platform.
        assert player._table.columnWidth(1) >= player._table.sizeHintForColumn(1)

    def test_it_narrows_one_that_is_wider_than_it_needs(self, player, qtbot):
        self.add(player, "a.mp3")
        player._table.setColumnWidth(1, 900)

        player._fit_column_to_contents(1)

        assert player._table.columnWidth(1) < 900

    def test_it_never_narrows_past_the_header_word(self, player, qtbot):
        """Measured the way *this* header paints its label. Qt's own
        `resizeColumnToContents` floors with `sectionSizeHint`, which is the
        style's idea of it, and `SeparatorHeaderView` blanks that and draws its
        own at `_TEXT_PAD`."""
        self.add(player, "a.mp3")

        player._fit_column_to_contents(1)

        assert player._table.columnWidth(1) >= player._header_fit_width(1)

    def test_an_empty_playlist_fits_to_the_header_word(self, player):
        player._table.setColumnWidth(1, 900)

        player._fit_column_to_contents(1)

        assert player._table.columnWidth(1) == player._header_fit_width(1)

    def test_it_is_one_shot_and_does_not_follow_later_additions(self, player):
        self.add(player, "a.mp3")
        player._fit_column_to_contents(1)
        fitted = player._table.columnWidth(1)

        self.add(player, "a very much longer filename indeed.mp3")

        assert player._table.columnWidth(1) == fitted

    def test_a_hidden_column_is_left_alone(self, player):
        """Nothing can right-click one, but the handler is public enough to be
        called: a hidden section reports width 0 and would be "fitted" to the
        header word, i.e. silently un-zeroed behind `_set_column_visible`'s
        back."""
        assert player._table.isColumnHidden(9)

        player._fit_column_to_contents(9)

        assert player._table.columnWidth(9) == 0

    def test_the_new_width_is_persisted(self, player):
        """`setColumnWidth` emits `sectionResized`, which is already wired to
        the debounced save — so this needs no save of its own, and this is the
        assertion that says so."""
        self.add(player, "a considerably longer filename than the column.mp3")
        player._col_save_timer.stop()

        player._fit_column_to_contents(1)

        assert player._col_save_timer.isActive()
