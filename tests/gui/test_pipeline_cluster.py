"""The header's pipeline cluster: three mini step toggles and the target.

Structure, never pixels — the suite runs with no application stylesheet, so a
width measured here is a width of a different app (CLAUDE.md).

Most of the target-field tests came here from the Convert panel with the field
itself. The two worth keeping either way are the ones a reasonable
implementation gets wrong: a typed name that happens to equal a listed playlist
must still read as "create", or the completer's inline match would silently
retarget the run at somebody else's playlist; and a remembered name must be
*selected* rather than typed back in, or every launch makes one more numbered
playlist.
"""

from __future__ import annotations

import pytest

from src.gui.convert_pipeline import STEP_ANALYZE, STEP_CONVERT, STEP_ORDER, STEP_RENAME
from src.gui.widgets.pipeline_cluster import PipelineCluster


@pytest.fixture
def cluster(qtbot) -> PipelineCluster:
    widget = PipelineCluster()
    qtbot.addWidget(widget)
    return widget


# ------------------------------------------------------------- the step minis


def test_it_holds_one_mini_per_step_in_order(cluster):
    row = cluster.layout()
    widgets = [row.itemAt(i).widget() for i in range(row.count())]
    assert [w for w in widgets if w in cluster._toggles.values()] == [
        cluster._toggles[step] for step in STEP_ORDER
    ]
    assert list(STEP_ORDER) == [STEP_RENAME, STEP_CONVERT, STEP_ANALYZE]


def test_every_step_starts_off(cluster):
    assert not cluster.any_step_enabled()
    for step in STEP_ORDER:
        assert not cluster.step_enabled(step)


def test_clicking_a_mini_asks_rather_than_decides(cluster, qtbot):
    """MainWindow owns the state; the cluster only reports the click."""
    with qtbot.waitSignal(cluster.step_toggled) as caught:
        cluster._toggles[STEP_CONVERT].click()
    assert caught.args == [STEP_CONVERT, True]


def test_reflecting_a_step_does_not_echo(cluster):
    """Without the block the two mirrors would write config at each other."""
    seen = []
    cluster.step_toggled.connect(lambda step, on: seen.append((step, on)))
    cluster.set_step_enabled(STEP_RENAME, True)
    assert seen == []
    assert cluster.step_enabled(STEP_RENAME)


def test_reflecting_the_same_value_twice_is_stable(cluster):
    cluster.set_step_enabled(STEP_ANALYZE, True)
    cluster.set_step_enabled(STEP_ANALYZE, True)
    assert cluster.step_enabled(STEP_ANALYZE)
    assert not cluster._target.isHidden()


# -------------------------------------------------------- the target's collapse


def test_the_target_is_hidden_until_a_step_is_on(cluster):
    # isHidden, not isVisible: nothing here has been shown.
    assert cluster._target.isHidden()
    cluster.set_step_enabled(STEP_RENAME, True)
    assert not cluster._target.isHidden()


def test_the_target_collapses_when_the_last_step_goes_off(cluster):
    cluster.set_step_enabled(STEP_RENAME, True)
    cluster.set_step_enabled(STEP_CONVERT, True)
    cluster.set_step_enabled(STEP_RENAME, False)
    assert not cluster._target.isHidden()  # convert is still on
    cluster.set_step_enabled(STEP_CONVERT, False)
    assert cluster._target.isHidden()


def test_the_shape_change_is_announced_once_per_move(cluster):
    """The header competes for this width and has no resize to notice it by."""
    beats = []
    cluster.shape_changed.connect(lambda: beats.append(1))
    cluster.set_step_enabled(STEP_RENAME, True)
    assert len(beats) == 1
    cluster.set_step_enabled(STEP_CONVERT, True)
    assert len(beats) == 1  # already showing
    cluster.set_step_enabled(STEP_RENAME, False)
    cluster.set_step_enabled(STEP_CONVERT, False)
    assert len(beats) == 2


def test_the_width_hint_follows_the_target(cluster):
    """Reserving the hidden field's width would cost the header's subtitle
    80-odd pixels for a feature that ships off."""
    narrow = cluster.width_hint()
    cluster.set_step_enabled(STEP_RENAME, True)
    assert cluster.width_hint() > narrow


# ------------------------------------------------------------------ the target


def test_pipeline_target_reports_a_pick(cluster):
    cluster.set_playlists([(4, "Set"), (9, "Warmup")])
    cluster.select_node(9)
    assert cluster.pipeline_target() == (9, "Warmup")


def test_typed_text_equal_to_a_listed_name_still_reads_as_create(cluster):
    """The completer is off precisely so these two stay distinguishable."""
    cluster.set_playlists([(4, "Set")])
    cluster._target.setCurrentIndex(-1)
    cluster._target.setEditText("Set")
    assert cluster.pipeline_target() == (None, "Set")


def test_the_completer_is_off(cluster):
    assert cluster._target.completer() is None


def test_the_target_is_a_fitted_combo(cluster):
    from src.gui.widgets.fitted_combo import FittedComboBox

    assert isinstance(cluster._target, FittedComboBox)


def test_select_node_reports_a_miss(cluster):
    cluster.set_playlists([(4, "Set")])
    assert cluster.select_node(4)
    assert not cluster.select_node(99)


def test_refilling_keeps_a_pick(cluster):
    cluster.set_playlists([(4, "Set"), (9, "Warmup")])
    cluster.select_node(9)
    cluster.set_playlists([(4, "Set"), (9, "Warmup"), (11, "New")])
    assert cluster.pipeline_target() == (9, "Warmup")


def test_refilling_keeps_typed_text(cluster):
    cluster._target.setEditText("Not yet made")
    cluster.set_playlists([(4, "Set")])
    assert cluster.pipeline_target() == (None, "Not yet made")


def test_refilling_after_the_picked_playlist_is_deleted_keeps_the_name(cluster):
    cluster.set_playlists([(4, "Set"), (9, "Warmup")])
    cluster.select_node(9)
    cluster.set_playlists([(4, "Set")])
    assert cluster.pipeline_target() == (None, "Warmup")


def test_a_target_change_is_announced(cluster, qtbot):
    with qtbot.waitSignal(cluster.target_changed):
        cluster._target.setEditText("Friday set")


# --------------------------------------------------------- restoring a target


def test_a_remembered_name_that_matches_nothing_is_typed_back(cluster):
    cluster.restore_pipeline_target("Gone")
    assert cluster.pipeline_target() == (None, "Gone")


def test_a_remembered_name_resolves_to_the_same_playlist(cluster):
    """The whole point of storing a name: it must be *picked* on the way back,
    or every launch creates one more numbered playlist."""
    cluster.restore_pipeline_target("Set")  # pass 1: the list is still empty
    cluster.set_playlists([(4, "Set"), (9, "Warmup")])
    # set_playlists cannot re-pick what was never picked, so restore again the
    # way MainWindow does once the list has arrived.
    cluster.restore_pipeline_target("Set")
    assert cluster.pipeline_target() == (4, "Set")


def test_restoring_nothing_leaves_the_field_alone(cluster):
    cluster._target.setEditText("Typed")
    cluster.restore_pipeline_target("")
    assert cluster.pipeline_target() == (None, "Typed")


# ------------------------------------------------------------------ the field


def test_the_target_box_does_not_grow_with_its_playlists(cluster):
    """An editable combo sizes itself to its widest item by default, so the
    box grew with whoever had the longest playlist name and changed size when
    one was renamed. A field you type into has to stay put."""
    before = cluster._target.width()
    cluster.set_playlists([(1, "Set")])
    assert cluster._target.width() == before
    cluster.set_playlists([(1, "Gigs / Saturday closing set 2026 extended mix")])
    assert cluster._target.width() == before
    assert cluster._target.minimumWidth() == cluster._target.maximumWidth()


def test_the_list_is_not_capped_with_the_box(cluster, qtbot):
    """The popup is floored at the box's width, which was right while the box
    sized itself to its items — capped, it opened the list elided."""
    cluster.set_step_enabled(STEP_CONVERT, True)
    cluster.set_playlists([(1, "Set"), (2, "Gigs / Saturday closing set 2026")])
    cluster.show()
    qtbot.waitExposed(cluster)
    combo = cluster._target
    combo.showPopup()
    try:
        assert combo.view().width() > combo.width()
        assert combo.view().width() >= combo.view().sizeHintForColumn(0)
    finally:
        combo.hidePopup()


def test_the_target_sizes_from_contents_not_first_show(cluster):
    """MainWindow feeds the playlists in after the cluster exists, so the
    default AdjustToContentsOnFirstShow would lock the hint at an empty list
    and the popup floor would read that stale number for ever."""
    from PySide6.QtWidgets import QComboBox

    assert (cluster._target.sizeAdjustPolicy()
            == QComboBox.SizeAdjustPolicy.AdjustToContents)


def test_locking_the_controls_greys_everything(cluster):
    cluster.set_controls_enabled(False)
    assert not cluster._target.isEnabled()
    assert all(not t.isEnabled() for t in cluster._toggles.values())
    cluster.set_controls_enabled(True)
    assert cluster._target.isEnabled()
