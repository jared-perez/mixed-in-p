"""Settings > Playlist Artwork: which part of the cover the Art column shows.

Three views over the *same* scaled cover. Top and Middle cut a band one row
tall out of it and differ only in where from; Full keeps the square whole and
grows the row to fit. So the invariant worth defending is that the cover is
scaled identically in all three — the column never reflows when the setting
changes, only the row height does, and only for Full.

Most of this is checked by sampling a render rather than by reading the cache.
A cached image proves what was decoded, not what was drawn, and the whole point
of the setting is what ends up on screen (CLAUDE.md: the Analyze row tint
passed ten data-level tests while painting nothing).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage

from src.gui.widgets.player_panel import (
    ARTWORK_VIEWS,
    DEFAULT_ARTWORK_VIEW,
    PlayerPanel,
)
from src.utils.config import AppConfig, load_config, save_config

from .test_player_artwork import ART_COLUMN, add, make_room, make_track, pump_art

TOP = "#ff0000"
MIDDLE = "#ff00ff"
BOTTOM = "#00ff00"


@pytest.fixture
def sf():
    return pytest.importorskip("soundfile")


@pytest.fixture
def banded_cover(tmp_path):
    """A cover in three horizontal bands, so a crop is legible in a render.

    Thirds, because the band is one third of the scaled cover — the top view
    must show only TOP, the middle view only MIDDLE, and Full all three.
    """
    size = 300
    image = QImage(size, size, QImage.Format.Format_RGB32)
    for y in range(size):
        band = (TOP, MIDDLE, BOTTOM)[min(2, y * 3 // size)]
        for x in range(size):
            image.setPixelColor(x, y, QColor(band))
    path = tmp_path / "banded.png"
    image.save(str(path))
    return path.read_bytes()


@pytest.fixture
def player(qtbot):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    panel.resize(900, 400)
    panel.show()
    qtbot.waitExposed(panel)
    return panel


def show_art(player, qtbot):
    """Reveal the column with the wide text columns out of the way.

    make_room first: the band is three rows wide and a column drawn past the
    viewport's right edge is cut off there, which samples as a missing crop.
    """
    make_room(player)
    player._set_column_visible(ART_COLUMN, True)
    pump_art(player, qtbot)


def painted(player, row=0):
    """Every colour drawn in the row's Art cell, as a set of names."""
    table = player._table
    table.scrollToTop()
    shot = table.viewport().grab().toImage()
    x0 = table.columnViewportPosition(ART_COLUMN)
    y0 = table.rowViewportPosition(row)
    return {
        shot.pixelColor(x, y).name()
        for y in range(y0, y0 + table.rowHeight(row))
        for x in range(x0, min(x0 + table.columnWidth(ART_COLUMN), shot.width()))
    }


class TestTheSetting:
    def test_there_are_three_views(self):
        assert ARTWORK_VIEWS == ("top", "middle", "full")

    def test_a_panel_starts_at_the_default(self, player):
        assert player._art_view == DEFAULT_ARTWORK_VIEW == "top"

    def test_an_unknown_name_is_ignored(self, player):
        """A config written by a future build must not blank the column."""
        player.set_artwork_view("bottom")

        assert player._art_view == "top"

    def test_it_survives_a_round_trip_through_config(self):
        save_config(AppConfig(player_artwork_view="middle"))

        assert load_config().player_artwork_view == "middle"

    def test_a_bad_stored_value_falls_back(self, tmp_path):
        save_config(AppConfig(player_artwork_view="sideways"))

        assert load_config().player_artwork_view == "top"

    def test_an_older_config_has_no_opinion(self):
        """The field is new: a config written before it must read as Top, not
        as an empty string that then matches no radio and no view."""
        cfg = load_config()

        assert cfg.player_artwork_view == "top"


class TestWhichPartIsDrawn:
    """The three views, sampled off the screen."""

    def test_top_shows_only_the_top_band(
        self, player, qtbot, sf, tmp_path, banded_cover
    ):
        add(player, qtbot, make_track(sf, tmp_path, "a.flac", banded_cover))
        show_art(player, qtbot)

        colours = painted(player)

        assert TOP in colours
        assert MIDDLE not in colours and BOTTOM not in colours

    def test_middle_shows_only_the_middle_band(
        self, player, qtbot, sf, tmp_path, banded_cover
    ):
        add(player, qtbot, make_track(sf, tmp_path, "a.flac", banded_cover))
        show_art(player, qtbot)
        player.set_artwork_view("middle")
        pump_art(player, qtbot)

        colours = painted(player)

        assert MIDDLE in colours, "the middle of the sleeve never arrived"
        assert TOP not in colours and BOTTOM not in colours

    def test_full_shows_the_whole_sleeve(
        self, player, qtbot, sf, tmp_path, banded_cover
    ):
        add(player, qtbot, make_track(sf, tmp_path, "a.flac", banded_cover))
        show_art(player, qtbot)
        player.set_artwork_view("full")
        pump_art(player, qtbot)

        colours = painted(player)

        assert {TOP, MIDDLE, BOTTOM} <= colours

    def test_switching_back_from_full_crops_again(
        self, player, qtbot, sf, tmp_path, banded_cover
    ):
        """The uncropped square is in the cache by then; a stale entry would
        leave the whole sleeve squashed into a one-row band."""
        add(player, qtbot, make_track(sf, tmp_path, "a.flac", banded_cover))
        show_art(player, qtbot)
        player.set_artwork_view("full")
        pump_art(player, qtbot)

        player.set_artwork_view("top")
        pump_art(player, qtbot)

        colours = painted(player)
        assert TOP in colours
        assert BOTTOM not in colours


class TestTheCacheKnowsWhichCrop:
    def test_top_and_middle_are_not_confused(
        self, player, qtbot, sf, tmp_path, banded_cover
    ):
        """The two crops are byte-for-byte the same *size*, so a cache guard
        that compares only the scaled edge serves the old band back and the
        setting appears to do nothing at all."""
        add(player, qtbot, make_track(sf, tmp_path, "a.flac", banded_cover))
        show_art(player, qtbot)
        top_strip = next(iter(player._art_cache.values())).toImage()

        player.set_artwork_view("middle")
        pump_art(player, qtbot)
        middle_strip = next(iter(player._art_cache.values())).toImage()

        assert top_strip.size() == middle_strip.size()
        assert top_strip != middle_strip

    def test_the_view_is_part_of_the_loaded_key(self, player):
        assert player._art_size_loaded == (0, "")


class TestOnlyFullChangesTheLayout:
    def test_the_cover_is_scaled_the_same_in_every_view(self, player):
        """What keeps the column from reflowing: Top, Middle and Full all scale
        the sleeve to the same edge and differ only in how much is kept."""
        sizes = set()
        for view in ARTWORK_VIEWS:
            player.set_artwork_view(view)
            sizes.add(player._art_size())

        assert len(sizes) == 1

    def test_the_column_width_does_not_move(self, player):
        player._set_column_visible(ART_COLUMN, True)
        width = player._table.columnWidth(ART_COLUMN)

        player.set_artwork_view("full")

        assert player._table.columnWidth(ART_COLUMN) == width

    def test_the_band_views_leave_the_row_height_alone(self, player):
        height = player._table.verticalHeader().defaultSectionSize()

        player.set_artwork_view("middle")

        assert player._table.verticalHeader().defaultSectionSize() == height

    def test_full_grows_the_row_to_fit_the_sleeve(self, player):
        player._set_column_visible(ART_COLUMN, True)
        text_row = player._text_row_height()

        player.set_artwork_view("full")

        assert player._table.verticalHeader().defaultSectionSize() == (
            player._art_size() + player._ART_ROW_INSET
        )
        assert player._table.verticalHeader().defaultSectionSize() > text_row

    def test_the_icon_is_square_in_full(self, player):
        player._set_column_visible(ART_COLUMN, True)

        player.set_artwork_view("full")

        icon = player._table.iconSize()
        assert icon.width() == icon.height() == player._art_size()

    def test_a_hidden_column_does_not_pay_for_the_art(self, player):
        """Full while the column is hidden would leave a plain text playlist
        wearing three-row rows for artwork nobody can see."""
        player._set_column_visible(ART_COLUMN, True)
        player.set_artwork_view("full")
        tall = player._table.verticalHeader().defaultSectionSize()

        player._set_column_visible(ART_COLUMN, False)

        assert tall > player._text_row_height()
        assert player._table.verticalHeader().defaultSectionSize() == (
            player._text_row_height()
        )

    def test_revealing_it_again_brings_the_height_back(self, player):
        player.set_artwork_view("full")
        assert player._table.verticalHeader().defaultSectionSize() == (
            player._text_row_height()
        )

        player._set_column_visible(ART_COLUMN, True)

        assert player._table.verticalHeader().defaultSectionSize() > (
            player._text_row_height()
        )


class TestItStillFollowsTheTextSize:
    def test_full_rows_scale_with_it(self, player):
        player._set_column_visible(ART_COLUMN, True)
        player.set_artwork_view("full")
        medium = player._table.verticalHeader().defaultSectionSize()

        player.set_text_size("large")

        assert player._table.verticalHeader().defaultSectionSize() > medium

    def test_the_row_height_is_not_fed_its_own_output(self, player):
        """The art is scaled from the row height and, in Full, the row height
        from the art. Read one back from the other and every pass over the
        setting makes the rows taller — so this asks twice."""
        player._set_column_visible(ART_COLUMN, True)
        player.set_artwork_view("full")
        once = player._table.verticalHeader().defaultSectionSize()

        player.set_text_size("large")
        player.set_text_size("medium")

        assert player._table.verticalHeader().defaultSectionSize() == once

    def test_the_band_height_is_measured_off_the_text_row(self, player):
        """Not off the vertical header, which in Full holds the art's height."""
        player._set_column_visible(ART_COLUMN, True)
        player.set_artwork_view("full")

        assert player._art_strip_height() == (
            player._text_row_height() - player._ART_ROW_INSET
        )


class TestItReachesThePanelAtStartup:
    def test_a_saved_view_is_applied_to_the_player(self, qtbot, monkeypatch):
        """Through MainWindow, since that is the only thing that reads the
        config field — a panel built by hand always starts at the default."""
        save_config(AppConfig(player_artwork_view="middle"))
        from src.gui.main_window import MainWindow

        window = MainWindow()
        qtbot.addWidget(window)

        assert window._player_panel._art_view == "middle"

        window._player_panel.shutdown_workers()


class TestTheSettingsPanel:
    def test_the_radios_load_from_the_config(self, qtbot):
        from src.gui.widgets.settings_panel import SettingsPanel

        panel = SettingsPanel()
        qtbot.addWidget(panel)

        panel.load_config(AppConfig(player_artwork_view="full"))

        assert panel._artwork_view_radios["full"].isChecked()

    def test_the_selection_reaches_the_saved_config(self, qtbot):
        """It is a replace() over the live config, so a field left out of that
        call is silently reset to its default every time Settings saves."""
        from src.gui.widgets.settings_panel import SettingsPanel

        panel = SettingsPanel()
        qtbot.addWidget(panel)
        panel._artwork_view_radios["middle"].setChecked(True)

        cfg = panel.get_config(AppConfig())

        assert cfg.player_artwork_view == "middle"

    def test_it_is_its_own_section(self, qtbot):
        """Not another row under Playlist Text Size: a control placed inside a
        section label reads as belonging to it."""
        from PySide6.QtWidgets import QLabel

        from src.gui.widgets.settings_panel import SettingsPanel

        panel = SettingsPanel()
        qtbot.addWidget(panel)

        titles = [
            w.text()
            for w in panel.findChildren(QLabel)
            if w.objectName() == "settingsSectionTitle"
        ]

        assert "Playlist Artwork" in titles
