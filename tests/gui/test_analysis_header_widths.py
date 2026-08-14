"""Every Analyze column is wide enough to show its own header word.

The widths were constants measured against the English labels, and the
columns are `Fixed` — so a header that does not fit cannot be dragged wider.
The header is also centred with `ElideNone`, which means an over-long word is
cut at *both* ends with no ellipsis to admit it: Russian "Энергия" rendered as
"нерги", "Тональность" as "жнальнос", "Код тональности" as "тональнс". Three
headers gone in Russian, two in Japanese and in French — and English lost the
tail of "Energy" and "Key Code", which is what made it visible at all.

Asserted against `sectionSizeHint`, the same measurement the fix is built on,
rather than against pixel counts: the suite runs with no application
stylesheet (see CLAUDE.md), so any number written here would describe a header
the app never paints. What has to hold under any font and padding is that a
column is at least as wide as the header says it needs to be.

Three things that hint accounts for and a QFontMetrics call does not — the
reason the fix does not do its own arithmetic:

* the stylesheet's `QHeaderView::section` padding, invisible to font metrics;
* the bold weight the same rule sets, which never reaches `header.font()`;
* the room Qt reserves for the sort indicator. Sorting is enabled on every
  column here, so it can land on any of them.
"""

from __future__ import annotations

import pytest

from src.gui.models.track_model import TrackStore
from src.gui.widgets.analysis_panel import AnalysisPanel

ENERGY_COLUMN = 7
KEY_CODE_COLUMN = 5


@pytest.fixture
def panel(qtbot):
    widget = AnalysisPanel(TrackStore())
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def header(panel):
    return panel._table.horizontalHeader()


class TestHeadersFitTheirColumns:
    def test_no_column_is_narrower_than_its_own_header(self, panel):
        for col in panel._BASE_COLUMN_WIDTHS:
            assert panel._table.columnWidth(col) >= header(panel).sectionSizeHint(col), (
                panel._model.COLUMNS[col]
            )

    def test_energy_fits_in_english(self, panel):
        """The column that gave the game away: 'Energy' lost its 'y' at 60px."""
        assert panel._table.columnWidth(ENERGY_COLUMN) >= header(panel).sectionSizeHint(
            ENERGY_COLUMN
        )

    def test_a_base_width_is_a_floor_and_not_a_target(self, panel):
        """Only ever widened — a column with room to spare keeps its width,
        so the layout does not shrink-wrap to the header word."""
        for col, base in panel._BASE_COLUMN_WIDTHS.items():
            assert panel._table.columnWidth(col) >= base

    def test_a_longer_label_widens_its_column(self, panel):
        """What Russian does to Key Code, done to a live panel. The instance
        attribute shadows the class list the model reads its headers from."""
        before = panel._table.columnWidth(KEY_CODE_COLUMN)
        columns = list(panel._model.COLUMNS)
        columns[KEY_CODE_COLUMN] = "Код тональности вообще"
        panel._model.COLUMNS = columns

        panel._fit_header_widths()

        assert panel._table.columnWidth(KEY_CODE_COLUMN) > before
        assert panel._table.columnWidth(KEY_CODE_COLUMN) >= header(panel).sectionSizeHint(
            KEY_CODE_COLUMN
        )

    def test_the_contents_sized_columns_are_left_alone(self, panel):
        """Alt Keys and Status size to their contents already — that is how
        Status was fixed when it clipped in five languages, and re-imposing a
        width on them would undo it."""
        assert 6 not in panel._BASE_COLUMN_WIDTHS
        assert 8 not in panel._BASE_COLUMN_WIDTHS
