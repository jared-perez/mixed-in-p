"""Compatible Tracks panel: the seed wiring, the empty states, the toggle.

The query itself is covered in `tests/test_compatible_tracks.py`; what is
tested here is everything the panel adds around it — that the seed follows
the *loaded* track (and survives Stop, which does not unload), that each of
the three reasons for an empty list says which one it is, and that the toggle
splits the playlist area rather than replacing it.

Nothing here asserts a pixel width. The GUI suite runs with no application
stylesheet, so a measurement taken here is a measurement of a different app
(see tests/gui/README.md); the width work is checked structurally — the panel
asks for *some* room, and the window minimum grows by it only while open.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTableWidgetItem

from src.analysis.keycode import KEY_TO_KEYCODE, KEYCODE_TO_KEY, render_key
from src.gui.widgets.compatible_panel import (
    _BPM_SAMPLE,
    _ENERGY_SAMPLE,
    _KEY_SAMPLES,
    COL_AUDITION,
    COL_BPM,
    COL_ENERGY,
    COL_KEY,
    COL_TRACK,
)
from src.gui.styles.theme import Theme
from src.gui.widgets.player_panel import PlayerPanel
from src.library import SCRATCH_NODE_ID, Library


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


def add_track(player, lib, tmp_path, name, **tags):
    """A file in the visible playlist, which is how it reaches the library.

    The tags ride in on the entry rather than being written to the library
    afterwards, because that is the direction the app works in: entry fields
    mirror the file's own tags and `_persist_playlist` writes them through on
    every list change — so a library row tagged behind the Player's back is
    blanked by the next add.
    """
    path = make_file(tmp_path, name)
    entry = {"file_path": path, "display_name": name}
    entry.update({k: ("" if v is None else str(v)) for k, v in tags.items()})
    player.add_tracks([entry])
    return path


def rows(panel) -> list[str]:
    return [m.track.filename for m in panel.matches]


class TestSeedWiring:
    def test_playing_a_track_seeds_the_panel(self, player, lib, tmp_path):
        seed = add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(player, lib, tmp_path, "match.wav", key="8A", bpm=128.0)
        player._play_track(0)
        assert player._compat_panel.seed_path == seed
        assert rows(player._compat_panel) == ["match.wav"]

    def test_stop_keeps_the_seed(self, player, lib, tmp_path):
        """Stop does not unload the track, and the matches for the track
        sitting in the player are still the ones the user wants."""
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(player, lib, tmp_path, "match.wav", key="8A", bpm=128.0)
        player._play_track(0)
        player._on_stop()
        assert rows(player._compat_panel) == ["match.wav"]

    def test_clearing_the_playlist_clears_the_seed(self, player, lib, tmp_path):
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(player, lib, tmp_path, "match.wav", key="8A", bpm=128.0)
        player._play_track(0)
        player._on_clear_playlist()
        assert player._compat_panel.seed_path is None
        assert rows(player._compat_panel) == []

    def test_the_ranking_order_is_what_the_panel_lists(self, player, lib, tmp_path):
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0, energy=5)
        add_track(player, lib, tmp_path, "adjacent.wav", key="9A", bpm=128.0)
        add_track(player, lib, tmp_path, "same.wav", key="8A", bpm=130.0)
        add_track(player, lib, tmp_path, "relative.wav", key="8B", bpm=128.0)
        player._play_track(0)
        assert rows(player._compat_panel) == ["same.wav", "relative.wav", "adjacent.wav"]


class TestEmptyStates:
    def test_no_seed_asks_for_one(self, player):
        # isHidden, not isVisible: the whole player page is unshown in an
        # offscreen test, so isVisible() is False for everything in it.
        panel = player._compat_panel
        assert panel._table.isHidden()
        assert "Play a track" in panel._message_label.text()

    def test_a_track_outside_the_library_says_so(self, qtbot, player, tmp_path):
        """The seed must be a library track (decided 2026-08-12), so the
        panel names that rather than showing an empty list."""
        path = make_file(tmp_path, "loose.wav")
        player._compat_panel.set_seed_path(path)
        assert "library" in player._compat_panel._message_label.text()

    def test_an_unanalysed_seed_points_at_the_analyzer(self, player, lib, tmp_path):
        add_track(player, lib, tmp_path, "seed.wav", bpm=128.0)
        player._play_track(0)
        assert "analyse" in player._compat_panel._message_label.text().lower()

    def test_no_matches_is_its_own_message(self, player, lib, tmp_path):
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(player, lib, tmp_path, "other.wav", key="3B", bpm=90.0)
        player._play_track(0)
        text = player._compat_panel._message_label.text()
        assert "mixes with" in text
        assert player._compat_panel._table.isHidden()

    def test_a_result_replaces_the_message_with_the_table(self, player, lib, tmp_path):
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(player, lib, tmp_path, "match.wav", key="8A", bpm=128.0)
        player._play_track(0)
        panel = player._compat_panel
        assert panel._table.isHidden() is False
        assert panel._message_label.isHidden() is True
        assert panel._table.rowCount() == 1


class TestTableContents:
    def test_a_row_carries_key_bpm_energy_and_name(self, player, lib, tmp_path):
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(
            player,
            lib,
            tmp_path,
            "match.wav",
            key="8A",
            bpm=128.0,
            energy=7,
            artist="Aphex",
            title="Xtal",
        )
        player._play_track(0)
        table = player._compat_panel._table
        assert table.item(0, COL_KEY).text() == "8A"
        assert table.item(0, COL_BPM).text() == "128"
        assert table.item(0, COL_ENERGY).text() == "7"
        assert table.item(0, COL_TRACK).text() == "Aphex – Xtal"

    def test_a_half_time_match_is_marked_not_silently_listed(self, player, lib, tmp_path):
        """64 under a 128 seed must not read as a query bug.

        The mark is a tint and a tooltip rather than a "×2" beside the number:
        that suffix was a third of the column's width, and the column is sized
        for three digits so the track name gets the room. What the test can
        assert here is the foreground the model carries — unlike a *background*
        brush, which the stylesheet's `::item` rule would silently discard.
        """
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(player, lib, tmp_path, "halved.wav", key="8A", bpm=64.0)
        player._play_track(0)
        cell = player._compat_panel._table.item(0, COL_BPM)
        assert cell.text() == "64"
        assert "Half-time" in cell.toolTip()
        assert cell.foreground().color() == QColor(Theme.INFO)

    def test_an_ordinary_tempo_is_left_untinted(self, player, lib, tmp_path):
        """The tint has to mean something, so a 1:1 match must not carry it."""
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(player, lib, tmp_path, "match.wav", key="8A", bpm=128.0)
        player._play_track(0)
        cell = player._compat_panel._table.item(0, COL_BPM)
        assert cell.toolTip() == ""
        assert cell.foreground().color() != QColor(Theme.INFO)

    def test_the_track_column_is_sized_to_the_longest_name(
        self, player, lib, tmp_path
    ):
        """The track column ends at the longest name, and the table scrolls.

        Deliberately *not* the last-section stretch every other table here
        uses: a stretched column ends at the panel edge, so a long name is
        elided and the only way to read it is to drag the splitter and take
        the room off the playlist. Ending at the content instead means the
        panel scrolls sideways to reach it.

        Asserted as a comparison, never as a pixel count — the GUI suite runs
        with no application stylesheet, so an absolute width measured here is
        a width the running app never has (see the module docstring).
        """
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(
            player, lib, tmp_path, "short.wav", key="8A", bpm=128.0,
            artist="A", title="B",
        )
        player._play_track(0)
        panel = player._compat_panel
        assert panel._table.horizontalHeader().stretchLastSection() is False
        short = panel._table.columnWidth(COL_TRACK)

        # Emphatically longer than the table's own width, so this asserts the
        # name rule and not the fill-the-viewport one. Narrowing the table
        # here instead does not work and looks like it does: `refresh` toggles
        # the table's visibility, which re-activates the panel's layout and
        # puts the width straight back.
        add_track(
            player, lib, tmp_path, "long.wav", key="8A", bpm=128.0,
            artist="Jensen Interceptor & Assembler Code",
            title="Body Music " + "(Extended Club Mix) " * 8,
        )
        panel.refresh()
        grown = panel._table.columnWidth(COL_TRACK)
        assert grown > short

        # And it gives the width back: re-measured on every fill rather than
        # nudged upwards, or one long name widens the column for good. Retagged
        # straight on the library row rather than through the Player, because
        # this asserts what the *panel* does with a shorter result — and the
        # panel reads the library, not the playlist.
        # Retagged to exactly the other row's name, so the expected width is
        # the earlier measurement itself rather than a tolerance — glyphs are
        # not the same width, and "A – C" came back 1px off "A – B".
        lib.add_track(str(tmp_path / "long.wav"), artist="A", title="B")
        panel.refresh()
        assert panel._table.columnWidth(COL_TRACK) == short

    def test_a_short_list_still_reaches_the_panel_edge(self, player, lib, tmp_path):
        """Sizing to the content must not leave a ragged edge.

        The other half of dropping `stretchLastSection`: with only rule 1, a
        list of short names ends partway across and the rows and the header
        band simply stop, with bare background beside them. So the column is
        also never narrower than what is left of the viewport.
        """
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(
            player, lib, tmp_path, "short.wav", key="8A", bpm=128.0,
            artist="A", title="B",
        )
        player._play_track(0)
        table = player._compat_panel._table
        table.resize(600, 200)
        used = sum(table.columnWidth(c) for c in range(table.columnCount()))
        assert used >= table.viewport().width()

    def test_no_fixed_column_can_elide_any_value_it_can_hold(self, player):
        """The fixed columns must fit their whole domain, on any platform.

        They cannot be resized, so an ellipsis there hides a value with no way
        for the user to get it back — the column has to be wide enough for the
        widest member of a closed set, full stop.

        Asserted against `sizeHintForColumn`, which is the same quantity
        `resizeColumnToContents` uses and therefore includes whatever the
        active QStyle reserves around the text. That matters more than it
        looks: this suite runs offscreen, which is **Fusion**, while the app
        on this machine runs the **macOS** style, whose `PM_FocusFrameHMargin`
        is twice Fusion's. A width that was measured against a hand-written
        padding constant passed here and clipped every key code to "1…" in the
        running app; the same constant would be wrong again on Windows. This
        assertion compares two numbers the style supplies, so it travels.
        """
        panel = player._compat_panel
        table = panel._table
        domain = {
            COL_KEY: _KEY_SAMPLES,
            COL_BPM: (_BPM_SAMPLE,),
            COL_ENERGY: (_ENERGY_SAMPLE,),
        }
        for col, values in domain.items():
            table.setRowCount(len(values))
            for row, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(value))
            assert table.sizeHintForColumn(col) <= table.columnWidth(col), (
                f"column {col} is narrower than its widest value"
            )
            table.setRowCount(0)

    def test_the_key_samples_really_are_every_key_the_panel_renders(self):
        """The domain above is only a guarantee if it is the whole domain.

        `render_key` answers in one of three notations and the setting can
        change while the panel is alive, so all three have to be in the
        measurement — a sample list covering only key codes would be provably
        wide enough for a case the user can switch away from.
        """
        rendered = {
            render_key(key, keycode, notation)
            for keycode, key in KEYCODE_TO_KEY.items()
            for notation in ("keycode", "traditional", "open_key")
        } | {
            render_key(key, keycode, "traditional")
            for key, keycode in KEY_TO_KEYCODE.items()
        }
        assert rendered <= set(_KEY_SAMPLES)

    def test_a_fractional_tempo_is_rounded_rather_than_clipped(
        self, player, lib, tmp_path
    ):
        """Three digits is a property of the column, not a hope about the data.

        The library stores BPM as a REAL, so a hand-edited or imported "128.4"
        is reachable — and it is the one value a column sized for three digits
        could not show. Rounded for display, as every other panel does.
        """
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(player, lib, tmp_path, "frac.wav", key="8A", bpm=128.4)
        player._play_track(0)
        assert player._compat_panel._table.item(0, COL_BPM).text() == "128"

    def test_the_key_column_follows_the_notation_setting(self, player, lib, tmp_path):
        """A track tagged "Am" reads as 8A under the default notation and as
        itself under traditional — the derived keycode is what matched it,
        the stored key is what a traditional reader wants to see."""
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(player, lib, tmp_path, "match.wav", key="Am", bpm=128.0)
        player._play_track(0)
        assert player._compat_panel._table.item(0, COL_KEY).text() == "8A"
        player.set_key_notation("traditional")
        assert player._compat_panel._table.item(0, COL_KEY).text() == "Am"

    def test_double_click_adds_the_track_to_the_visible_playlist(
        self, player, lib, tmp_path
    ):
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        match = make_file(tmp_path, "match.wav")
        lib.add_track(match, key="8A", bpm=128.0)
        player._play_track(0)
        panel = player._compat_panel
        assert [e.file_path for e in player._playlist] == [panel.seed_path]

        panel._on_double_clicked(panel._table.model().index(0, COL_TRACK))
        assert match in [e.file_path for e in player._playlist]
        assert match in [t.path for t in lib.get_items(SCRATCH_NODE_ID)]


class TestToggle:
    def test_the_panel_is_closed_until_asked_for(self, player):
        assert player.compat_panel_open is False
        assert player._compat_panel.isHidden() is True
        assert player.compat_panel_min_width() == 0

    def test_toggling_opens_it_and_asks_for_room(self, qtbot, player):
        with qtbot.waitSignal(player.compat_panel_toggled) as blocker:
            player._compat_button.setChecked(True)
        assert blocker.args == [True]
        assert player._compat_panel.isHidden() is False
        # Structural, not a pixel count: it wants *some* width, and that is
        # what the window minimum grows by.
        assert player.compat_panel_min_width() > 0

    def test_closing_it_gives_the_width_back(self, player):
        player._compat_button.setChecked(True)
        player._compat_button.setChecked(False)
        assert player._compat_panel.isHidden() is True
        assert player.compat_panel_min_width() == 0

    def test_opening_mid_track_seeds_immediately(self, player, lib, tmp_path):
        """Opening the panel must not wait for the next track to be played."""
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(player, lib, tmp_path, "match.wav", key="8A", bpm=128.0)
        player._play_track(0)
        player._compat_button.setChecked(True)
        assert rows(player._compat_panel) == ["match.wav"]

    def test_the_tooltip_says_what_the_next_click_does(self, player):
        closed = player._compat_button.toolTip()
        player._compat_button.setChecked(True)
        opened = player._compat_button.toolTip()
        assert closed != opened
        assert "Show" in closed and "Hide" in opened

    def test_the_slicer_can_still_pin_the_playlist_height(self, qtbot, player, tmp_path):
        """The slicer pins the playlist to N rows by capping the *table's*
        height. Wrapping the table in a splitter would defeat that if the
        splitter did not inherit the cap — it does, and this says so.

        Shown and pumped first: the splitter picks its children's constraints
        up during a layout pass, so asking before one has run reads the
        unconstrained default and the test passes against a broken build.
        """
        add_track(player, None, tmp_path, "a.wav", key="8A", bpm=128.0)
        player._compat_button.setChecked(True)
        player.show()
        qtbot.wait(10)
        player._apply_table_height(True)
        qtbot.wait(10)
        assert player._table.maximumHeight() < 16_777_215
        assert player._playlist_splitter.maximumHeight() == player._table.maximumHeight()

    def test_the_playlist_keeps_its_place_in_the_splitter(self, player):
        """The table is a child of the splitter whether or not the panel is
        open — the closed state must not be a different widget tree."""
        splitter = player._playlist_splitter
        assert splitter.indexOf(player._table) == 0
        assert splitter.indexOf(player._compat_panel) == 1
        assert splitter.count() == 2


class TestPolish:
    """Key-tier colour and drag-out — the two things phase 4 added."""

    def test_the_key_colour_says_which_kind_of_match_it_is(
        self, player, lib, tmp_path
    ):
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(player, lib, tmp_path, "same.wav", key="8A", bpm=128.0)
        add_track(player, lib, tmp_path, "relative.wav", key="8B", bpm=128.0)
        add_track(player, lib, tmp_path, "adjacent.wav", key="9A", bpm=128.0)
        player._play_track(0)
        table = player._compat_panel._table
        colours = [table.item(row, COL_KEY).foreground().color().name() for row in range(3)]
        assert len(set(colours)) == 3, "the three tiers must be distinguishable"
        assert colours[0].lower() == Theme.NEON_YELLOW.lower()

    def test_the_key_cell_names_the_relationship_in_words(
        self, player, lib, tmp_path
    ):
        """Colour alone is not an explanation, and not everyone sees it."""
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        add_track(player, lib, tmp_path, "relative.wav", key="8B", bpm=128.0)
        player._play_track(0)
        tip = player._compat_panel._table.item(0, COL_KEY).toolTip()
        assert "elative" in tip

    def test_a_drag_out_carries_the_selected_paths(self, player, lib, tmp_path):
        add_track(player, lib, tmp_path, "seed.wav", key="8A", bpm=128.0)
        match = add_track(player, lib, tmp_path, "match.wav", key="8A", bpm=128.0)
        player._play_track(0)
        panel = player._compat_panel
        panel._table.selectRow(0)
        assert panel._selected_paths() == [match]

    def test_the_drag_payload_is_indistinguishable_from_a_finder_drop(self):
        """No source-panel marker, on purpose: with one, every drop target
        would route the drag by DRAG_ROUTES and an unknown source is refused
        everywhere. Without one it is an ordinary file add."""
        from src.gui.widgets.compatible_panel import drag_mime
        from src.gui.widgets.droppable_table import SOURCE_PAGE_MIME

        mime = drag_mime(["/music/a.wav", "/music/b.wav"])
        assert [u.toLocalFile() for u in mime.urls()] == ["/music/a.wav", "/music/b.wav"]
        assert not mime.hasFormat(SOURCE_PAGE_MIME)

    def test_a_drag_out_is_copy_only(self, player):
        """A Move would ask the source to give the row up, and this list has
        no rows of its own to give — it is a query result."""
        from PySide6.QtWidgets import QAbstractItemView

        assert player._compat_panel._table.dragDropMode() == (
            QAbstractItemView.DragDropMode.DragOnly
        )
        assert player._compat_panel._table.dragEnabled()
