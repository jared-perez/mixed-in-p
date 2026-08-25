"""The Player's eye menu is the only control over visuals.

There was a master switch in Settings until 2026-08-23; "Visuals off" is now
one of the modes, the eye button is always there, and picking a visual is what
starts it. What that leaves behind is a config carrying a mode *and* the
retired switch, which is what most of this file is about.
"""

import json

import pytest

from src.gui.widgets.player_panel import PlayerPanel
from src.utils.config import (
    LEGACY_VIS_SWITCH,
    RETIRED_VIS_MODES,
    AppConfig,
    _config_path,
    _renamed_vis_mode,
    _VALID_VIS_MODES,
    load_config,
    save_config,
)


@pytest.fixture
def player(qtbot):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    return panel


def write_raw(**data):
    """A config.json as an older build would have left it."""
    _config_path().write_text(json.dumps(data), encoding="utf-8")


class TestTheRetiredSwitch:
    def test_a_switched_off_config_starts_off(self):
        """The switch was off by default and was what suppressed the mode, so
        reading the mode alone would start a visual nobody asked for."""
        write_raw(**{LEGACY_VIS_SWITCH: False, "visualization_mode": "backdrop"})
        assert load_config().visualization_mode == "off"

    def test_a_switched_on_config_keeps_its_visual(self):
        write_raw(**{LEGACY_VIS_SWITCH: True, "visualization_mode": "backdrop_fire"})
        assert load_config().visualization_mode == "backdrop_fire"

    def test_a_config_without_the_switch_is_taken_at_its_word(self):
        write_raw(visualization_mode="backdrop_loop_tunnel")
        assert load_config().visualization_mode == "backdrop_loop_tunnel"

    def test_saving_drops_the_legacy_key_for_good(self, qtbot, player):
        """What makes the fold one-time without a version field: the key stops
        existing the first time the config is written back."""
        write_raw(**{LEGACY_VIS_SWITCH: False, "visualization_mode": "backdrop"})
        player._select_vis_mode("backdrop_fractal")
        raw = json.loads(_config_path().read_text())
        assert LEGACY_VIS_SWITCH not in raw
        assert raw["visualization_mode"] == "backdrop_fractal"

    def test_the_field_is_gone_from_the_config(self):
        assert not hasattr(AppConfig(), LEGACY_VIS_SWITCH)



class TestTheRetiredModeNames:
    """Mode ids the menu no longer offers, and what a config holding one gets.

    Most of them are the two tunnels, renamed on 2026-08-24. Both were named
    for their *look*, and the look swapped: once the beat-locked tunnel's wall
    became nebula cloud it was plainly the wormhole-looking one, so the labels
    traded places. The ids were not swapped to match — they were retired and
    replaced with mechanism names, which is what makes this migration safe to
    re-run. The popout fire (dropped 2026-08-24) is the other kind: a mode
    withdrawn outright rather than renamed. Both follow the one rule — hand
    back whatever still draws the picture that was chosen. See
    `config._renamed_vis_mode`.
    """

    def test_an_old_config_keeps_the_picture_it_chose(self):
        """The row the user picked changed its name; the visual behind it did not.

        A config saying `tunnel_chase` chose the beat-locked tunnel. That
        visual is `beat_tunnel` now and wears the label "Wormhole" — so this
        must land on the same picture, and emphatically *not* on whichever id
        inherited the label `tunnel_chase` used to have.
        """
        write_raw(visualization_mode="tunnel_chase")
        assert load_config().visualization_mode == "beat_tunnel"

        write_raw(visualization_mode="wormhole")
        assert load_config().visualization_mode == "loop_tunnel"

    def test_the_backdrop_halves_move_with_them(self):
        write_raw(visualization_mode="backdrop_tunnel_chase")
        assert load_config().visualization_mode == "backdrop_beat_tunnel"

        write_raw(visualization_mode="backdrop_wormhole")
        assert load_config().visualization_mode == "backdrop_loop_tunnel"

    def test_running_it_again_changes_nothing(self):
        """The property a straight swap could not have had.

        Swapping the two ids would have needed a version counter to stay
        one-shot, and re-running one would silently flip the user's setting
        back. Retiring the names instead makes the trigger the stored value
        itself, so a second pass — or a crash before the first save — is inert.
        """
        for retired, current in RETIRED_VIS_MODES.items():
            once = _renamed_vis_mode(retired)
            assert once == current
            assert _renamed_vis_mode(once) == once

    def test_the_retired_names_cannot_be_chosen_again(self):
        """They are gone from the valid set, so nothing can write one back."""
        for retired in RETIRED_VIS_MODES:
            assert retired not in _VALID_VIS_MODES
        for current in RETIRED_VIS_MODES.values():
            assert current in _VALID_VIS_MODES

    def test_a_switched_off_config_is_still_off(self):
        """The older migration runs first and wins; this one never sees it."""
        write_raw(**{LEGACY_VIS_SWITCH: False, "visualization_mode": "wormhole"})
        assert load_config().visualization_mode == "off"


class TestThePopoutFireIsGone:
    """Withdrawn from the menu on 2026-08-24 — it did not look good full-window.

    The flames themselves stayed, as a backdrop, which is what a config that
    had chosen them gets back.
    """

    def test_the_menu_does_not_offer_it(self, player):
        labels = [a.text() for a in player._vis_menu.actions() if not a.isSeparator()]
        assert "Popout fire" not in labels
        assert "fire" not in player._vis_actions

    def test_the_backdrop_still_offers_it(self, player):
        labels = [a.text() for a in player._vis_menu.actions() if not a.isSeparator()]
        assert "Backdrop fire" in labels
        assert "backdrop_fire" in player._vis_actions

    def test_the_renderer_still_draws_fire(self):
        """The backdrop asks for exactly this mode, so it cannot be deleted.

        A mode may render and not be offered as a popout; the reverse would be
        a menu row that raises.
        """
        from src.gui.widgets.vis_canvas import POPOUT_MODES, RENDER_MODES

        assert "fire" in RENDER_MODES
        assert "fire" not in POPOUT_MODES
        assert set(POPOUT_MODES) <= set(RENDER_MODES)

    def test_a_config_that_chose_it_keeps_the_flames(self):
        """Not "off" — the picture it picked still exists, so hand it back."""
        write_raw(visualization_mode="fire")
        assert load_config().visualization_mode == "backdrop_fire"


class TestTheDefault:
    def test_a_fresh_install_starts_off(self, qtbot):
        """Nothing animates until someone picks a visual."""
        save_config(AppConfig())
        assert AppConfig.visualization_mode == "off"
        panel = PlayerPanel()
        qtbot.addWidget(panel)
        assert panel._vis_mode == "off"


class TestTheEyeMenu:
    def test_the_button_is_always_there(self, player):
        """It used to be hidden unless Settings said otherwise; the menu's own
        'off' row is the switch now. `isHidden`, not `isVisible` — nothing is
        ever shown in this suite."""
        assert not player._vis_button.isHidden()

    def test_no_master_switch_is_left_to_call(self, player):
        assert not hasattr(player, "set_visualizations_enabled")
        assert not hasattr(player, "_visualizations_enabled")

    def test_the_two_richest_visuals_lead_each_group(self, player):
        modes = [
            a.data() or a.text()
            for a in player._vis_menu.actions()
            if not a.isSeparator()
        ]
        labels = [a.text() for a in player._vis_menu.actions() if not a.isSeparator()]
        assert labels[0] == "Backdrop fractal"
        assert labels[1] == "Backdrop wormhole"
        assert labels[-1] == "Visuals off"
        # The popout half leads with the same two, so the groups read as pairs
        # at the head (the tails diverge — the backdrops order theirs to taste).
        popouts = labels[labels.index("Popout fractal") :]
        assert popouts[:2] == ["Popout fractal", "Popout wormhole"]
        assert len(modes) == len(player._vis_actions)

    def test_every_mode_is_offered_exactly_once(self, player):
        from src.gui.widgets.vis_canvas import POPOUT_MODES
        from src.gui.widgets.player_panel import _BACKDROP_VIS_MAP

        offered = set(player._vis_actions)
        assert offered == {"off", "backdrop"} | set(_BACKDROP_VIS_MAP) | set(POPOUT_MODES)
        assert len(player._vis_menu.actions()) == len(offered) + 2  # two separators


class TestPickingAVisualStartsIt:
    def test_choosing_a_backdrop_builds_its_renderer(self, player):
        player._select_vis_mode("backdrop_loop_tunnel")
        assert player._backdrop_renderer is not None
        assert player._backdrop_renderer._mode == "loop_tunnel"
        assert load_config().visualization_mode == "backdrop_loop_tunnel"

    def test_choosing_off_stops_it(self, player):
        player._select_vis_mode("backdrop_fractal")
        player._select_vis_mode("off")
        assert not player._vis_tick_timer.isActive()
        assert load_config().visualization_mode == "off"

    def test_a_popout_does_not_survive_a_restart(self, qtbot, player):
        """Unchanged by any of this: a visualizer window appearing at launch,
        before the main window, would be jarring."""
        player._select_vis_mode("fractal")
        assert load_config().visualization_mode == "fractal"
        second = PlayerPanel()
        qtbot.addWidget(second)
        assert second._vis_mode == "off"
        player._select_vis_mode("off")
