"""The Player header stays inside the visible width when the window narrows.

The panel scrolls: the transport row below holds the content widget at ~690px,
so anything laid out at the content width keeps that width no matter how narrow
the window gets. The header must not — it is chrome, and a header pinned to the
content width strands its right-hand group (visuals button, Edit Lock) far from
the scope button with dead space between, then scrolls it out of view.

Capping the header at the viewport makes its trailing stretch collapse as space
runs short, so the visuals button settles exactly one layout spacing from the
scope button — the same margin the search field has to it.
"""

import pytest

from src.gui.styles.theme import Theme
from src.gui.widgets.player_panel import PlayerPanel
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
    panel.set_library(lib)  # reveals the search field + scope button
    panel.show()
    qtbot.waitExposed(panel)
    return panel


def _gaps(panel):
    """(search -> scope, scope -> visuals) horizontal gaps, in pixels."""
    search = panel._search_field.geometry()
    scope = panel._scope_btn.geometry()
    vis = panel._vis_button.geometry()
    return scope.left() - search.right() - 1, vis.left() - scope.right() - 1


class TestHeaderCompression:
    def test_right_group_is_right_aligned_when_there_is_room(self, player, qtbot):
        player.resize(1200, 700)
        qtbot.wait(10)
        _, scope_to_vis = _gaps(player)
        # Far from the scope button: the stretch is doing its job.
        assert scope_to_vis > 200

    def test_visuals_button_closes_to_one_spacing_when_narrow(self, player, qtbot):
        player.resize(560, 700)
        qtbot.wait(10)
        search_to_scope, scope_to_vis = _gaps(player)
        assert scope_to_vis == search_to_scope == Theme.SPACING

    def test_header_never_squeezes_past_its_minimum(self, player, qtbot):
        """Below the header's own minimum it overflows rather than overlapping.

        The search field and scope button are both fixed-width, so a cap set
        under the row minimum makes them collide instead of clip.
        """
        player.resize(320, 700)
        qtbot.wait(10)
        search = player._search_field.geometry()
        scope = player._scope_btn.geometry()
        assert scope.left() > search.right()

    def test_gap_shrinks_monotonically_as_the_window_narrows(self, player, qtbot):
        widths, seen = (1100, 900, 700, 560), []
        for width in widths:
            player.resize(width, 700)
            qtbot.wait(10)
            seen.append(_gaps(player)[1])
        assert seen == sorted(seen, reverse=True)
        assert seen[-1] == Theme.SPACING  # closed all the way, not frozen partway
