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
    AppConfig,
    _config_path,
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
        write_raw(visualization_mode="backdrop_wormhole")
        assert load_config().visualization_mode == "backdrop_wormhole"

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
        # The popout half runs in the same order, so the groups read as pairs.
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
        player._select_vis_mode("backdrop_wormhole")
        assert player._backdrop_renderer is not None
        assert player._backdrop_renderer._mode == "wormhole"
        assert load_config().visualization_mode == "backdrop_wormhole"

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
