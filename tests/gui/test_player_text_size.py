"""Playlist text size: three presets, applied live.

Live rather than at restart because nothing here caches anything — the theme
needs a restart only because widgets hold on to palette colours.

The mechanism is forced by the app stylesheet: a global
``QWidget { font-size: 14px }`` beats ``setFont()`` on the table, so the size
has to be QSS, and since a second ``setStyleSheet`` replaces rather than adds
to the first, the table's one inline sheet is built in one place. Most of the
tests below are about the things that do NOT follow the font on their own.
"""

from __future__ import annotations

import pytest

from src.gui.widgets.player_panel import (
    DEFAULT_TEXT_SIZE,
    TEXT_SIZES,
    PlayerPanel,
)
from src.utils.config import AppConfig, load_config, save_config


@pytest.fixture
def player(qtbot):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    panel.resize(1000, 500)
    panel.show()
    qtbot.waitExposed(panel)
    return panel


class TestThePresets:
    def test_there_are_three_of_them(self):
        assert TEXT_SIZES == {"small": 12, "medium": 14, "large": 17}
        assert DEFAULT_TEXT_SIZE == "medium"

    def test_a_panel_starts_at_the_default(self, player):
        assert f"font-size: {TEXT_SIZES[DEFAULT_TEXT_SIZE]}px" in player._table.styleSheet()

    def test_each_one_reaches_the_table(self, player):
        for size, px in TEXT_SIZES.items():
            player.set_text_size(size)
            assert player._table.font().pixelSize() == px, size

    def test_an_unknown_name_is_ignored(self, player):
        player.set_text_size("enormous")

        assert player._table.font().pixelSize() == TEXT_SIZES[DEFAULT_TEXT_SIZE]


class TestTheHeaderKeepsUp:
    def test_the_header_font_follows_too(self, player):
        """On QHeaderView, not QHeaderView::section. A sub-control rule is
        honoured when the section is painted but never reaches header.font() —
        which is what the column widths are measured from, so styling only the
        sub-control drew a bigger word and left the old column to hold it."""
        player.set_text_size("large")

        assert player._table.horizontalHeader().font().pixelSize() == 17

    def test_the_word_fit_columns_widen_with_it(self, player):
        before = player._table.columnWidth(4)  # BPM

        player.set_text_size("large")

        assert player._table.columnWidth(4) > before

    def test_shrinking_never_takes_width_away(self, player):
        """The measured width is a floor, not a target: a column the user
        widened stays where they put it."""
        player._table.setColumnWidth(4, 300)

        player.set_text_size("small")

        assert player._table.columnWidth(4) == 300


class TestRowHeight:
    def test_medium_is_exactly_what_shipped(self, player, qtbot, tmp_path):
        """Rows sit at the vertical header's default section size and nothing
        re-measures them. The first attempt used resizeRowsToContents, which
        sizes to the delegate hint plus the QSS padding and made every row
        half again as tall *at the current size* — a redesign nobody asked
        for, arriving with an unrelated feature.

        Asserted on a real row rather than on the default section size,
        because that is what changed and the default would not have.
        """
        pytest.importorskip("soundfile")
        import numpy as np
        import soundfile as sf

        path = tmp_path / "m.flac"
        sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
        player.add_tracks(
            [{"file_path": str(path), "display_name": path.name}],
            allow_duplicates=True,
        )
        qtbot.wait(10)
        base = player._base_row_height

        player.set_text_size("large")
        player.set_text_size("medium")
        qtbot.wait(10)

        assert player._table.rowHeight(0) == base

    def test_large_is_taller_and_small_is_shorter(self, player):
        heights = {}
        for size in ("small", "medium", "large"):
            player.set_text_size(size)
            heights[size] = player._table.verticalHeader().defaultSectionSize()

        assert heights["small"] < heights["medium"] < heights["large"]

    def test_the_rows_themselves_move(self, player, qtbot, tmp_path):
        pytest.importorskip("soundfile")
        import numpy as np
        import soundfile as sf

        path = tmp_path / "a.flac"
        sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format="FLAC")
        player.add_tracks(
            [{"file_path": str(path), "display_name": path.name}],
            allow_duplicates=True,
        )
        qtbot.wait(10)
        before = player._table.rowHeight(0)

        player.set_text_size("large")
        qtbot.wait(10)

        assert player._table.rowHeight(0) > before


class TestTheInlineSheetHasOneOwner:
    """A second setStyleSheet would replace this one, so everything the table
    needs from QSS is rebuilt together — including the rules that have nothing
    to do with text size."""

    @pytest.mark.parametrize("size", ["small", "medium", "large"])
    def test_the_row_padding_survives_every_size(self, player, size):
        player.set_text_size(size)

        assert "padding: 8px 0px" in player._table.styleSheet()

    @pytest.mark.parametrize("size", ["small", "medium", "large"])
    def test_the_inline_editor_rule_survives_too(self, player, size):
        """Without it the editor inherits the global pill-shaped QLineEdit and
        clips its own text in a short row."""
        player.set_text_size(size)
        sheet = player._table.styleSheet()

        assert "QTableWidget QLineEdit" in sheet
        assert "border-radius: 0px" in sheet

    def test_the_transparent_background_survives(self, player):
        """The backdrop waveform is painted behind the table; an opaque fill
        would cover it."""
        player.set_text_size("large")

        assert "background-color: transparent" in player._table.styleSheet()


class TestTheSetting:
    def test_it_round_trips(self):
        for size in TEXT_SIZES:
            save_config(AppConfig(player_text_size=size))
            assert load_config().player_text_size == size

    def test_a_bad_value_falls_back(self):
        """A hand-edited config must not leave the player with no size at all."""
        save_config(AppConfig(player_text_size="gigantic"))

        assert load_config().player_text_size == DEFAULT_TEXT_SIZE

    def test_the_default_is_medium(self):
        assert AppConfig().player_text_size == DEFAULT_TEXT_SIZE


class TestTheSettingsRow:
    def test_it_reports_the_choice(self, qtbot):
        from src.gui.widgets.settings_panel import SettingsPanel

        panel = SettingsPanel()
        qtbot.addWidget(panel)
        panel._text_size_radios["large"].setChecked(True)

        assert panel.get_config(AppConfig()).player_text_size == "large"

    def test_it_shows_the_stored_choice(self, qtbot):
        from src.gui.widgets.settings_panel import SettingsPanel

        panel = SettingsPanel()
        qtbot.addWidget(panel)
        panel.load_config(AppConfig(player_text_size="small"))

        assert panel._text_size_radios["small"].isChecked()

    def test_changing_it_announces_a_settings_change(self, qtbot):
        """The live-apply path: the panel only announces, MainWindow pushes."""
        from src.gui.widgets.settings_panel import SettingsPanel

        panel = SettingsPanel()
        qtbot.addWidget(panel)

        with qtbot.waitSignal(panel.settings_changed):
            panel._text_size_group.buttonClicked.emit(
                panel._text_size_radios["large"]
            )
