"""The Playlists section of Settings: duplicate policy round-trip."""

import pytest

from src.gui.widgets.settings_panel import SettingsPanel
from src.utils.config import AppConfig


@pytest.fixture
def panel(qtbot):
    widget = SettingsPanel()
    qtbot.addWidget(widget)
    return widget


class TestDuplicatePolicyControl:
    def test_the_three_policies_are_offered_in_order(self, panel):
        combo = panel._duplicate_policy_combo
        assert [combo.itemData(i) for i in range(combo.count())] == [
            "ask",
            "add",
            "skip",
        ]

    @pytest.mark.parametrize("value", ["ask", "add", "skip"])
    def test_each_value_survives_a_round_trip(self, panel, value):
        panel.load_config(AppConfig(duplicate_policy=value))
        assert panel.get_config().duplicate_policy == value

    def test_it_defaults_to_asking(self, panel):
        """A fresh panel must not read as "always add" before any load."""
        assert panel.get_config().duplicate_policy == "ask"

    def test_an_unknown_stored_value_leaves_the_selection_alone(self, panel):
        """load_config() is fed a sanitised AppConfig, but be defensive: an
        unmatched value must not blank the combo into returning None."""
        panel.load_config(AppConfig(duplicate_policy="nonsense"))
        assert panel.get_config().duplicate_policy in {"ask", "add", "skip"}
