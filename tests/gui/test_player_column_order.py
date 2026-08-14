"""The shipped column order, and the one-time migration that delivers it.

The order is a *visual* arrangement over fixed logical indexes — the logical
order can never change, because every saved header state addresses sections by
number. So "the default order" is its own constant, and changing it raises a
second problem: a saved state beats the defaults, so a new default would only
ever be seen by someone who had never opened the app. Hence a defaults version,
and a migration that runs exactly once.

"Exactly once" is the part worth testing hard. Run it twice and it eats the
layout the user built in between — which is the same failure as a config field
that a panel writes and the window reverts on close, and that one has bitten
this app before (see TestTheWindowDoesNotClobberIt in test_player_columns).
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QTableWidget

from src.gui.widgets.player_panel import PlayerPanel
from src.library import Library
from src.utils.config import AppConfig, load_config, save_config

EXPECTED_ORDER = [
    "#", "Art", "Artist", "Title", "BPM", "Key", "Comment", "Duration",
    "Year", "Filename",
]


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "library.db")
    yield library
    library.close()


def make_player(qtbot, lib):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    panel.set_library(lib)
    return panel


def visual_order(player, visible_only=True):
    """The header's columns left to right, by label."""
    header = player._table.horizontalHeader()
    labels = []
    for visual in range(player._table.columnCount()):
        col = header.logicalIndex(visual)
        if visible_only and player._table.isColumnHidden(col):
            continue
        item = player._table.horizontalHeaderItem(col)
        labels.append(item.text() if item else str(col))
    return labels


def saved_state_from(player):
    """What this panel would persist, as a config the next one will read."""
    player._save_column_state()
    return load_config()


class TestTheShippedOrder:
    def test_it_is_what_was_asked_for(self, qtbot, lib):
        player = make_player(qtbot, lib)

        assert visual_order(player) == EXPECTED_ORDER

    def test_the_hidden_ones_follow_behind(self, qtbot, lib):
        """Order still matters for a column that is off: turning one on should
        drop it where it belongs, not wherever it was declared."""
        player = make_player(qtbot, lib)

        assert visual_order(player, visible_only=False) == EXPECTED_ORDER + [
            "Album", "Genre", "Track #", "Label", "Bitrate", "Energy",
        ]

    def test_the_logical_indexes_are_untouched(self, qtbot, lib):
        """The order is visual *only*. Renumbering the columns instead would
        re-point every saved state in the wild at the wrong sections."""
        player = make_player(qtbot, lib)

        labels = [
            player._table.horizontalHeaderItem(c).text()
            for c in range(player._table.columnCount())
        ]
        assert labels[:9] == [
            "#", "Filename", "Artist", "Title", "BPM", "Key", "Comment",
            "Duration", "Year",
        ]
        assert labels[15] == "Art"

    def test_filename_is_last_but_still_cannot_be_hidden(self, qtbot, lib):
        """It moved to the end of the row, not out of the row: it is still the
        track's identity, and still doubles as a fallback for an empty Title."""
        player = make_player(qtbot, lib)

        assert visual_order(player)[-1] == "Filename"
        assert 1 in player._LOCKED_COLUMNS

    def test_art_opens_at_the_band_width(self, qtbot, lib):
        """Shipped visible, so it never passes through the reveal path that
        sizes it — and Qt's default section size is wider than the band."""
        player = make_player(qtbot, lib)

        assert player._table.columnWidth(player._ARTWORK_COLUMN) == (
            player._default_column_widths[player._ARTWORK_COLUMN]
        )


class TestAllTenAreOpen:
    """The order was only half the ask: those ten columns are the default
    *open* set, and a stale saved layout must not leave any of them off.
    """

    def test_a_fresh_install_shows_all_ten(self, qtbot, lib):
        player = make_player(qtbot, lib)

        assert len(visual_order(player)) == len(EXPECTED_ORDER)

    def test_a_stale_layout_with_columns_switched_off_gets_them_back(
        self, qtbot, lib
    ):
        """What this actually repairs: a layout stamped with an older defaults
        version but with Artist, Title, Comment and Duration hidden — the shape
        an unreleased build left behind. Hiding is only the user's to keep once
        their layout is current."""
        table = QTableWidget(0, 16)
        for col in (2, 3, 6, 7):
            table.setColumnHidden(col, True)
        cfg = AppConfig()
        cfg.player_column_state = bytes(
            table.horizontalHeader().saveState().toBase64()
        ).decode("ascii")
        cfg.player_column_count = 16
        cfg.player_column_defaults_version = (
            PlayerPanel._COLUMN_DEFAULTS_VERSION - 1
        )
        save_config(cfg)

        player = make_player(qtbot, lib)

        assert visual_order(player) == EXPECTED_ORDER

    def test_a_current_layout_keeps_what_the_user_switched_off(self, qtbot, lib):
        """The other side of it: once migrated, a column the user hid stays
        hidden. A reset that fired on every launch would be a bug, not a fix."""
        first = make_player(qtbot, lib)
        first._set_column_visible(6, False)  # Comment
        first._save_column_state()

        second = make_player(qtbot, lib)

        assert second._table.isColumnHidden(6)


class TestTheOneTimeMigration:
    def _old_layout(self, columns=16, version=0):
        """A config as some earlier build left it: a state that predates the
        new default order, and a version that has never heard of it."""
        table = QTableWidget(0, columns)
        table.setColumnWidth(1, 329)
        cfg = AppConfig()
        cfg.player_column_state = bytes(
            table.horizontalHeader().saveState().toBase64()
        ).decode("ascii")
        cfg.player_column_count = columns
        cfg.player_column_defaults_version = version
        save_config(cfg)
        return cfg

    def test_an_old_layout_is_replaced_by_the_new_default(self, qtbot, lib):
        """Without this the change reaches nobody who has ever run the app."""
        self._old_layout()

        player = make_player(qtbot, lib)

        assert visual_order(player) == EXPECTED_ORDER

    def test_it_writes_the_version_back_immediately(self, qtbot, lib):
        """Not at the next column change: someone who never touches the header
        would be migrated on every launch, each one discarding the layout of
        the session before."""
        self._old_layout()

        make_player(qtbot, lib)

        assert load_config().player_column_defaults_version == (
            PlayerPanel._COLUMN_DEFAULTS_VERSION
        )

    def test_it_does_not_run_a_second_time(self, qtbot, lib):
        """The whole risk of the design, in one test: arrange the columns after
        migrating and they must still be that way on the next launch."""
        self._old_layout()
        first = make_player(qtbot, lib)
        first._set_column_visible(9, True)   # Album
        first._table.setColumnWidth(2, 411)  # Artist
        first._save_column_state()

        second = make_player(qtbot, lib)

        assert not second._table.isColumnHidden(9), "the column choice was lost"
        assert second._table.columnWidth(2) == 411, "the width was lost"

    def test_a_fresh_install_is_not_a_migration(self, qtbot, lib):
        """No saved state means nothing to migrate — and nothing to write back
        either, since the defaults are not a layout the user chose."""
        make_player(qtbot, lib)

        assert load_config().player_column_state == ""

    def test_a_current_layout_is_left_alone(self, qtbot, lib):
        """Someone who has already migrated keeps what they arranged, however
        far it is from the shipped order."""
        self._old_layout(version=PlayerPanel._COLUMN_DEFAULTS_VERSION)

        player = make_player(qtbot, lib)

        assert player._table.columnWidth(1) == 329
        assert visual_order(player)[:2] == ["#", "Filename"]


class TestTheWindowDoesNotRevertTheVersion:
    """`MainWindow._persist_config` re-reads the fields the panels own before
    writing its startup snapshot back. A new field that belongs with one
    already on that list has to be added to it, or closing the window reverts
    half a value — here, the version without the state, which would run the
    migration again on the next launch and eat the session's layout.
    """

    def test_closing_the_window_keeps_the_version(self, qtbot, tmp_path):
        from src.gui.main_window import MainWindow

        class WindowStub:
            _persist_config = MainWindow._persist_config

            def __init__(self, config):
                self._config = config

        # The window's snapshot is from launch: no layout, version 0.
        startup = AppConfig()
        # ...and the panel has since written both, mid-session.
        save_config(
            AppConfig(
                player_column_state="abc",
                player_column_count=16,
                player_column_defaults_version=PlayerPanel._COLUMN_DEFAULTS_VERSION,
            )
        )

        WindowStub(startup)._persist_config()

        saved = load_config()
        assert saved.player_column_state == "abc"
        assert saved.player_column_count == 16
        assert saved.player_column_defaults_version == (
            PlayerPanel._COLUMN_DEFAULTS_VERSION
        )
