"""Date Added and Date Created: where each one's value comes from, and why the
spelling is what it is.

The two columns look alike and share nothing underneath. **Date Created** is a
property of the file on disk, read with a stat, so it survives the library
knowing nothing about the track and it changes when the row is pointed at a
different file. **Date Added** is a property of the *library row* — when this
app first saw the file — which nothing on disk records and no tag holds, so it
can only come from ``tracks.added_at``, and re-adding a file must never move it.

The third thing under test is the spelling. ``_STAMP_FORMAT`` is ISO-ordered so
that the *displayed text* sorts chronologically, which is what lets both
columns use ``_sort_text`` with no parser of their own. A localized date would
sort as "01/09" before "25/08" — so the ordering test below is a test of the
format choice, not of the sort machinery.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest

from src.gui.widgets.player_panel import (
    _STAMP_FORMAT,
    _STAMP_SHAPE,
    PlayerPanel,
    _file_created_at,
    _format_iso_stamp,
)
from src.library import SCRATCH_NODE_ID, Library

STAMP = re.compile(r"\d{4}-\d\d-\d\d")
DATE_ADDED_COLUMN = PlayerPanel._DATE_ADDED_COLUMN
DATE_CREATED_COLUMN = PlayerPanel._DATE_CREATED_COLUMN


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


def make_file(tmp_path, name="track.mp3") -> Path:
    path = tmp_path / name
    path.write_bytes(b"\0" * 64)
    return path


def backdate(lib, path, iso: str) -> None:
    """Move a library row's `added_at`, which nothing in the app can do.

    Reaching past the API on purpose: `add_track` stamps ``now`` and never
    moves it again — which is the property under test — so there is no
    supported way to produce a row that was added years ago.
    """
    lib._con.execute(
        "UPDATE tracks SET added_at=? WHERE path=?", (iso, str(path))
    )
    lib._con.commit()


def add(player, path) -> None:
    player.add_tracks(
        [{"file_path": str(path), "display_name": Path(path).name}],
        allow_duplicates=True,
    )


class TestTheSpelling:
    def test_it_is_iso_ordered_so_the_text_sorts_as_the_date_does(self):
        earlier = _format_iso_stamp("2026-08-25T23:59:00")
        later = _format_iso_stamp("2026-09-01T00:01:00")

        assert (earlier, later) == ("2026-08-25", "2026-09-01")
        # The whole reason for the format: plain string order is date order,
        # which a localized "25/08/2026" would get backwards.
        assert earlier < later

    def test_the_time_of_day_is_dropped(self):
        """The columns show the date and nothing else. `added_at` still holds
        the second underneath, so this is a display decision, not a loss."""
        assert _format_iso_stamp("2026-08-25T17:30:45") == "2026-08-25"

    def test_which_makes_two_additions_on_one_day_compare_equal(self):
        """The consequence worth stating: a day's additions are one block, so
        sorting by Date Added leaves them in list order (the sort is stable)
        rather than in the order they arrived."""
        morning = _format_iso_stamp("2026-08-25T09:00:00")
        evening = _format_iso_stamp("2026-08-25T17:30:00")

        assert morning == evening

    def test_an_absent_or_unparsable_stamp_reads_as_blank(self):
        assert _format_iso_stamp("") == ""
        assert _format_iso_stamp(None) == ""
        assert _format_iso_stamp("whenever") == ""

    def test_the_shape_the_columns_are_measured_from_matches_the_real_thing(self):
        """`_STAMP_SHAPE` is what the column width is measured against, and it
        is kept beside the format rather than derived from it — the codes are
        not the width of what they expand to. So the two are pinned here: a
        format change that this misses would size the columns for a stamp the
        app does not print."""
        real = datetime(2026, 8, 25, 14, 3).strftime(_STAMP_FORMAT)

        assert len(real) == len(_STAMP_SHAPE)
        assert [
            (i, c) for i, c in enumerate(real) if not c.isdigit()
        ] == [(i, c) for i, c in enumerate(_STAMP_SHAPE) if not c.isdigit()]


class TestDateCreated:
    def test_it_comes_off_the_file(self, tmp_path):
        path = make_file(tmp_path)

        assert STAMP.fullmatch(_file_created_at(str(path)))

    def test_it_agrees_with_the_stat(self, tmp_path):
        path = make_file(tmp_path)
        st = path.stat()
        expected = datetime.fromtimestamp(
            getattr(st, "st_birthtime", None) or st.st_ctime
        ).strftime(_STAMP_FORMAT)

        assert _file_created_at(str(path)) == expected

    def test_a_file_that_is_not_there_is_blank_rather_than_an_error(self, tmp_path):
        assert _file_created_at(str(tmp_path / "gone.mp3")) == ""

    def test_a_track_the_library_never_heard_of_still_has_one(self, qtbot, tmp_path):
        """It is a fact about the disk, so it does not wait for an import."""
        panel = PlayerPanel()
        qtbot.addWidget(panel)  # no library at all
        path = make_file(tmp_path)

        add(panel, path)
        qtbot.wait(10)

        assert STAMP.fullmatch(panel._playlist[0].date_created)
        assert panel._playlist[0].date_added == "", "nothing to have added it to"


class TestDateAdded:
    def test_a_freshly_dropped_file_is_dated_by_the_add_itself(
        self, player, qtbot, tmp_path, lib
    ):
        """The row does not exist until the auto-save creates it, so the value
        can only be filled in afterwards — the case `_fill_dates_added` is for.
        A blank here is what the column looked like before it."""
        path = make_file(tmp_path)

        add(player, path)
        qtbot.wait(10)

        assert STAMP.fullmatch(player._playlist[0].date_added)
        assert player._table.item(0, DATE_ADDED_COLUMN).text() == (
            player._playlist[0].date_added
        ), "the cell was left blank while the entry was filled"

    def test_it_is_the_library_row_s_own_stamp(self, player, qtbot, tmp_path, lib):
        path = make_file(tmp_path)
        track_id = lib.add_track(str(path))

        add(player, path)
        qtbot.wait(10)

        assert player._playlist[0].date_added == _format_iso_stamp(
            lib.get_track(track_id).added_at
        )

    def test_re_adding_a_file_does_not_move_it(self, player, qtbot, tmp_path, lib):
        """'First time it was added' is the whole meaning of the column. The
        library already guarantees this — `add_track` leaves `added_at` alone
        for a path it knows — and this is the column relying on it."""
        path = make_file(tmp_path)
        lib.add_track(str(path))
        backdate(lib, path, "2019-03-04T10:20:30")

        add(player, path)
        qtbot.wait(10)
        add(player, path)
        qtbot.wait(10)

        assert [e.date_added for e in player._playlist] == [
            "2019-03-04",
            "2019-03-04",
        ]

    def test_opening_a_playlist_dates_every_row(self, player, qtbot, tmp_path, lib):
        """The load hands the stamps straight over with the rest of the row —
        no second query per track for a list it has already fetched."""
        paths = [make_file(tmp_path, f"t{i}.mp3") for i in range(3)]
        ids = [lib.add_track(str(p)) for p in paths]
        lib.set_items(SCRATCH_NODE_ID, ids)

        player.load_node(SCRATCH_NODE_ID)
        qtbot.wait(10)

        assert len(player._playlist) == 3
        assert all(STAMP.fullmatch(e.date_added) for e in player._playlist)

    def test_a_search_result_carries_both(self, player, qtbot, tmp_path, lib):
        """`_entry_from_track` promises no file is *opened* for a search hit.
        A stat is not an open, so Date Created is filled there too."""
        path = make_file(tmp_path, "photek.mp3")
        track = lib.get_track(lib.add_track(str(path), artist="Photek"))

        entry = player._entry_from_track(track)

        assert entry.date_added == _format_iso_stamp(track.added_at)
        assert STAMP.fullmatch(entry.date_created)


class TestSorting:
    def test_both_columns_sort_chronologically(self, player, qtbot, tmp_path, lib):
        """Asserted through the panel's own sort rather than on the key
        function, because what is sorted is the *displayed* string."""
        for name, added in (
            ("mid.mp3", "2022-06-06T06:06:06"),
            ("old.mp3", "2001-01-01T01:01:01"),
            ("new.mp3", "2030-12-31T23:59:59"),
        ):
            path = make_file(tmp_path, name)
            lib.add_track(str(path))
            backdate(lib, path, added)
        for name in ("mid.mp3", "old.mp3", "new.mp3"):
            add(player, tmp_path / name)
        qtbot.wait(10)

        player._on_header_clicked(DATE_ADDED_COLUMN)

        assert [e.display_name for e in player._playlist] == [
            "old.mp3", "mid.mp3", "new.mp3",
        ]

        player._on_header_clicked(DATE_ADDED_COLUMN)  # descending

        assert [e.display_name for e in player._playlist] == [
            "new.mp3", "mid.mp3", "old.mp3",
        ]

    def test_a_row_added_while_sorted_by_date_added_lands_in_its_place(
        self, player, qtbot, tmp_path, lib
    ):
        """The one case patching the cell in place is not enough for: the new
        row has no date until the auto-save makes one, so it is sorted as a
        blank — to the end — and would sit there wearing today's date."""
        old = make_file(tmp_path, "old.mp3")
        lib.add_track(str(old))
        backdate(lib, old, "2001-01-01T01:01:01")
        add(player, old)
        qtbot.wait(10)
        player._on_header_clicked(DATE_ADDED_COLUMN)
        player._on_header_clicked(DATE_ADDED_COLUMN)  # newest first

        add(player, make_file(tmp_path, "new.mp3"))
        qtbot.wait(10)

        assert [e.display_name for e in player._playlist] == ["new.mp3", "old.mp3"]

    def test_an_undated_row_sorts_last_in_both_directions(
        self, player, qtbot, tmp_path
    ):
        """The panel's rule for every column: a blank that sorted last
        ascending would sort *first* descending, putting the rows with no
        answer above the ones that have one."""
        for name in ("a.mp3", "b.mp3"):
            add(player, make_file(tmp_path, name))
        qtbot.wait(10)
        player._playlist[0].date_created = ""

        player._on_header_clicked(DATE_CREATED_COLUMN)
        assert player._playlist[-1].date_created == ""

        player._on_header_clicked(DATE_CREATED_COLUMN)
        assert player._playlist[-1].date_created == ""


class TestTheyAreNotTags:
    def test_neither_is_editable(self, player, qtbot, tmp_path):
        """Both are read from elsewhere — the disk and the library — so typing
        over one would be a value with nowhere to go."""
        assert DATE_ADDED_COLUMN not in player._EDITABLE_COLUMNS
        assert DATE_CREATED_COLUMN not in player._EDITABLE_COLUMNS

    def test_the_auto_save_does_not_try_to_write_them(
        self, player, qtbot, tmp_path, lib
    ):
        """`_persist_playlist` passes every entry field it owns through
        `add_track`; these two are not among the tags it takes, and a stamp
        round-tripping through it would overwrite the library's own."""
        path = make_file(tmp_path)
        add(player, path)
        qtbot.wait(10)
        stamped = lib.get_track_by_path(str(path)).added_at

        player._persist_playlist()

        assert lib.get_track_by_path(str(path)).added_at == stamped


class TestTheyStartOff:
    def test_hidden_until_asked_for(self, player):
        assert player._table.isColumnHidden(DATE_ADDED_COLUMN)
        assert player._table.isColumnHidden(DATE_CREATED_COLUMN)

    def test_the_header_menu_offers_both(self, player, qtbot):
        menu = player._build_column_menu()
        qtbot.addWidget(menu)

        labels = [a.text() for a in menu.actions() if a.isCheckable()]

        assert {"Date Added", "Date Created"} <= set(labels)

    @pytest.mark.parametrize("col", [DATE_ADDED_COLUMN, DATE_CREATED_COLUMN])
    def test_one_opens_wide_enough_for_the_stamp_it_holds(
        self, player, qtbot, tmp_path, col
    ):
        """Asked of the style, through the path that paints the cell, so the
        assertion travels to whichever style runs it — a hand-written
        `font metrics + a constant` is right on at most one platform (measured:
        the cell wants 120px under Fusion and 124 on macOS, from
        `PM_FocusFrameHMargin` alone).

        Measured against the widest value the column can hold, which for a
        fixed-width stamp is any of them. The header word is the other half,
        and `_apply_header_fit_floor` covers that — checked by hand against all
        twelve languages — where the header word decides it in every Latin
        and Cyrillic one, and the stamp decides it in ja/zh/ko.
        """
        add(player, make_file(tmp_path))
        qtbot.wait(10)
        player._set_column_visible(col, True)

        assert player._table.sizeHintForColumn(col) <= player._table.columnWidth(col)
        header = player._table.horizontalHeader()
        assert header.sectionSizeHint(col) <= player._table.columnWidth(col)

    @pytest.mark.parametrize("size", ["small", "medium", "large"])
    @pytest.mark.parametrize("reveal_first", [True, False])
    def test_it_still_fits_at_every_text_size(
        self, player, qtbot, tmp_path, size, reveal_first
    ):
        """The reason the width is measured rather than written down: a stamp
        wants 74 / 85 / 100px across the three presets (with the app's own
        stylesheet, which the suite does not load — so trust the *relation*
        here, not the numbers). A single constant is right at one preset and
        clips at another, silently, with `NoElideDelegate` leaving no ellipsis.

        Both orders, because they fail differently. Resizing while the column
        is *showing* goes through `_apply_header_fit_floor`; resizing while it
        is hidden cannot (a hidden section reports width 0), so the floor has
        to be applied again on reveal — which is what the second case caught.
        """
        both = (DATE_ADDED_COLUMN, DATE_CREATED_COLUMN)
        add(player, make_file(tmp_path))
        qtbot.wait(10)
        if reveal_first:
            for col in both:
                player._set_column_visible(col, True)
        player.set_text_size(size)
        if not reveal_first:
            for col in both:
                player._set_column_visible(col, True)
        qtbot.wait(10)

        for col in both:
            assert (
                player._table.sizeHintForColumn(col)
                <= player._table.columnWidth(col)
            ), f"{size}: column {col} clips its own stamp"

    def test_revealing_one_shows_what_was_already_there(
        self, player, qtbot, tmp_path
    ):
        """The cells are built whether or not the column is showing, so a
        reveal displays the data at once rather than at the next rebuild."""
        add(player, make_file(tmp_path))
        qtbot.wait(10)

        player._set_column_visible(DATE_CREATED_COLUMN, True)

        assert not player._table.isColumnHidden(DATE_CREATED_COLUMN)
        assert STAMP.fullmatch(player._table.item(0, DATE_CREATED_COLUMN).text())
