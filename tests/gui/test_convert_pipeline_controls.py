"""The Convert panel's pipeline controls: the `|` toggle and the target field.

Structure, never pixels — the suite runs with no application stylesheet, so a
width measured here is a width of a different app (CLAUDE.md).

The two things worth guarding are the ones a reasonable implementation gets
wrong. A typed name that happens to equal a listed playlist must still read as
"create", or the completer's inline match would silently retarget the run at
somebody else's playlist. And a remembered name must be *selected* rather than
typed back in, or every launch makes one more numbered playlist.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from src.gui.models.track_model import TrackStore
from src.gui.widgets.conversion_panel import ConversionPanel
from src.utils.config import AppConfig, load_config, save_config


def _write(path, samplerate: int = 44100, subtype: str = "PCM_16") -> str:
    sf = pytest.importorskip("soundfile")
    import numpy as np

    t = np.linspace(0, 0.1, int(samplerate * 0.1), endpoint=False)
    sf.write(str(path), (0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32"),
             samplerate, subtype=subtype)
    return str(path)


def _panel(qtbot, **cfg) -> ConversionPanel:
    cfg.setdefault("convert_target_format", "FLAC")
    cfg.setdefault("convert_sample_rate", 44100)
    cfg.setdefault("convert_bit_depth", 16)
    save_config(AppConfig(**cfg))
    widget = ConversionPanel(TrackStore())
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def panel(qtbot):
    return _panel(qtbot)


# ------------------------------------------------------------------- toggling


def test_off_by_default(panel):
    assert not panel.pipeline_enabled()
    assert panel._convert_btn.text() == "Convert"
    assert not panel._pipeline_target.isEnabled()


def test_toggling_on_renames_the_button_and_opens_the_field(panel):
    panel._pipeline_toggle.setChecked(True)
    assert panel.pipeline_enabled()
    assert panel._convert_btn.text() == "Start"
    assert panel._convert_btn.toolTip() == "Send the tracks through the pipeline"
    assert panel._pipeline_target.isEnabled()


def test_the_toggle_tooltip_says_what_the_next_click_does(panel):
    off = panel._pipeline_toggle.toolTip()
    panel._pipeline_toggle.setChecked(True)
    on = panel._pipeline_toggle.toolTip()
    assert off != on
    assert "Turn on" in off and "Turn off" in on


def test_toggling_emits_for_the_coupling(panel, qtbot):
    with qtbot.waitSignal(panel.pipeline_toggled) as caught:
        panel._pipeline_toggle.setChecked(True)
    assert caught.args == [True]


def test_set_pipeline_enabled_is_a_reflect_not_an_act(panel):
    """MainWindow calls this when auto-analyze goes off; it must not come back
    round as a toggle the user made."""
    seen = []
    panel.pipeline_toggled.connect(seen.append)
    panel._pipeline_toggle.setChecked(True)
    assert seen == [True]
    panel.set_pipeline_enabled(False)
    assert seen == [True]  # no echo
    assert not panel.pipeline_enabled()
    assert panel._convert_btn.text() == "Convert"
    assert load_config().convert_pipeline_enabled is False


# ---------------------------------------------------------------- enablement


def test_start_needs_both_rows_and_a_name(qtbot, tmp_path):
    panel = _panel(qtbot)
    panel.add_files([_write(tmp_path / "a.wav")])
    panel._pipeline_toggle.setChecked(True)
    assert panel._pipeline_target.currentText() == ""
    assert not panel._convert_btn.isEnabled()
    panel._pipeline_target.setEditText("Pipeline test")
    assert panel._convert_btn.isEnabled()
    panel._pipeline_target.setEditText("   ")
    assert not panel._convert_btn.isEnabled()


def test_a_name_alone_is_not_enough(qtbot):
    panel = _panel(qtbot)
    panel._pipeline_toggle.setChecked(True)
    panel._pipeline_target.setEditText("Pipeline test")
    assert not panel._convert_btn.isEnabled()


def test_start_is_enabled_for_a_batch_with_nothing_to_convert(qtbot, tmp_path):
    """Every row already in the target format: Convert is dead, Start is not."""
    panel = _panel(qtbot, convert_target_format="WAV")
    panel.add_files([_write(tmp_path / "a.wav")])
    assert not panel._convert_btn.isEnabled()  # Same format
    panel._pipeline_toggle.setChecked(True)
    panel._pipeline_target.setEditText("Pipeline test")
    assert panel._convert_btn.isEnabled()


# -------------------------------------------------------------- pipeline_rows


def test_pipeline_rows_classifies_each_verdict(qtbot, tmp_path):
    panel = _panel(qtbot, convert_target_format="WAV", convert_sample_rate=44100,
                   convert_bit_depth=16)
    ready = _write(tmp_path / "hires.flac", samplerate=96000, subtype="PCM_24")
    same = _write(tmp_path / "same.wav", samplerate=44100, subtype="PCM_16")
    upsample = _write(tmp_path / "low.flac", samplerate=32000, subtype="PCM_16")
    panel.add_files([ready, same, upsample])

    to_convert, passthrough = panel.pipeline_rows()
    assert to_convert == [ready]
    assert passthrough == [same]
    assert upsample not in to_convert and upsample not in passthrough


def test_an_already_converted_row_is_forwarded_by_its_output(qtbot, tmp_path):
    from src.conversion.result import ConversionResult

    panel = _panel(qtbot)
    src = _write(tmp_path / "a.wav")
    panel.add_files([src])
    panel.mark_converted([
        ConversionResult(source_path=src, output_path=str(tmp_path / "a.flac"),
                         target_format="FLAC")
    ])
    to_convert, passthrough = panel.pipeline_rows()
    assert to_convert == []
    assert passthrough == [src]
    assert panel._effective_path(src) == str(tmp_path / "a.flac")


# --------------------------------------------------------------- the target


def test_pipeline_target_reports_a_pick(panel):
    panel.set_playlists([(4, "Set"), (9, "Warmup")])
    panel.select_node(9)
    assert panel.pipeline_target() == (9, "Warmup")


def test_typed_text_equal_to_a_listed_name_still_reads_as_create(panel):
    """The completer is off precisely so these two stay distinguishable."""
    panel.set_playlists([(4, "Set")])
    panel._pipeline_target.setCurrentIndex(-1)
    panel._pipeline_target.setEditText("Set")
    assert panel.pipeline_target() == (None, "Set")


def test_the_completer_is_off(panel):
    assert panel._pipeline_target.completer() is None


def test_the_target_is_a_fitted_combo(panel):
    from src.gui.widgets.fitted_combo import FittedComboBox

    assert isinstance(panel._pipeline_target, FittedComboBox)


def test_select_node_reports_a_miss(panel):
    panel.set_playlists([(4, "Set")])
    assert panel.select_node(4)
    assert not panel.select_node(99)


def test_refilling_keeps_a_pick(panel):
    panel.set_playlists([(4, "Set"), (9, "Warmup")])
    panel.select_node(9)
    panel.set_playlists([(4, "Set"), (9, "Warmup"), (11, "New")])
    assert panel.pipeline_target() == (9, "Warmup")


def test_refilling_keeps_typed_text(panel):
    panel._pipeline_target.setEditText("Not yet made")
    panel.set_playlists([(4, "Set")])
    assert panel.pipeline_target() == (None, "Not yet made")


def test_refilling_after_the_picked_playlist_is_deleted_keeps_the_name(panel):
    panel.set_playlists([(4, "Set"), (9, "Warmup")])
    panel.select_node(9)
    panel.set_playlists([(4, "Set")])
    assert panel.pipeline_target() == (None, "Warmup")


# -------------------------------------------------------------- persistence


def test_the_toggle_and_the_name_are_saved(qtbot, tmp_path):
    panel = _panel(qtbot)
    panel._pipeline_toggle.setChecked(True)
    panel._pipeline_target.setEditText("Pipeline test")
    disk = load_config()
    assert disk.convert_pipeline_enabled is True
    assert disk.convert_pipeline_playlist == "Pipeline test"


def test_a_remembered_name_that_matches_nothing_is_typed_back(qtbot):
    panel = _panel(qtbot, convert_pipeline_enabled=True,
                   convert_pipeline_playlist="Gone")
    assert panel.pipeline_enabled()
    assert panel.pipeline_target() == (None, "Gone")


def test_a_remembered_name_resolves_to_the_same_playlist(qtbot):
    """The whole point of storing a name: it must be *picked* on the way back,
    or every launch creates one more numbered playlist."""
    panel = _panel(qtbot, convert_pipeline_enabled=True,
                   convert_pipeline_playlist="Set")
    panel.set_playlists([(4, "Set"), (9, "Warmup")])
    # set_playlists cannot re-pick what was never picked, so restore again the
    # way MainWindow does once the list has arrived.
    panel.restore_pipeline_target("Set")
    assert panel.pipeline_target() == (4, "Set")


def test_the_toggle_cannot_come_back_on_with_auto_analyze_off(qtbot):
    save_config(AppConfig(auto_analyze=False, convert_pipeline_enabled=True,
                          convert_pipeline_playlist="Set"))
    assert load_config().convert_pipeline_enabled is False
    panel = ConversionPanel(TrackStore())
    qtbot.addWidget(panel)
    assert not panel.pipeline_enabled()


def test_loading_the_panel_does_not_write_back(qtbot):
    """The restore runs inside the _loading_settings guard."""
    save_config(AppConfig(convert_pipeline_enabled=True,
                          convert_pipeline_playlist="Set",
                          convert_target_format="WAV"))
    panel = ConversionPanel(TrackStore())
    qtbot.addWidget(panel)
    disk = load_config()
    assert disk.convert_pipeline_playlist == "Set"
    assert disk.convert_target_format == "WAV"


# ------------------------------------------------------------------ the row


def test_the_bottom_row_reports_a_real_minimum(panel):
    """Not a pixel assertion: only that the row's spacing was set, so the sum
    adds where it means to add (an unset QLayout answers -1)."""
    assert panel._bottom_row.spacing() > 0
    assert panel.bottom_row_min_width() > panel._convert_btn.sizeHint().width()


def test_the_target_box_does_not_grow_with_its_playlists(panel):
    """An editable combo sizes itself to its widest item by default, so the
    box grew with whoever had the longest playlist name and changed size when
    one was renamed. A field you type into has to stay put."""
    before = panel._pipeline_target.width()
    panel.set_playlists([(1, "Set")])
    assert panel._pipeline_target.width() == before
    panel.set_playlists([(1, "Gigs / Saturday closing set 2026 extended mix")])
    assert panel._pipeline_target.width() == before
    assert panel._pipeline_target.minimumWidth() == panel._pipeline_target.maximumWidth()


def test_the_list_is_not_capped_with_the_box(panel, qtbot):
    """The popup is floored at the box's width, which was right while the box
    sized itself to its items — capped, it opened the list elided."""
    panel.set_playlists([(1, "Set"), (2, "Gigs / Saturday closing set 2026")])
    panel.show()
    qtbot.waitExposed(panel)
    combo = panel._pipeline_target
    combo.showPopup()
    try:
        assert combo.view().width() > combo.width()
        assert combo.view().width() >= combo.view().sizeHintForColumn(0)
    finally:
        combo.hidePopup()


def test_the_target_sizes_from_contents_not_first_show(panel):
    """MainWindow feeds the playlists in after the panel exists, so the
    default AdjustToContentsOnFirstShow would lock the hint at an empty list
    and the popup floor would read that stale number for ever."""
    from PySide6.QtWidgets import QComboBox

    assert (panel._pipeline_target.sizeAdjustPolicy()
            == QComboBox.SizeAdjustPolicy.AdjustToContents)


def test_the_pipeline_controls_sit_beside_the_convert_button(panel):
    """Ordered [stats][stretch][toggle][playlist][Convert][Send To]: the two
    pipeline controls are adjacent to the button they arm, not adrift in the
    middle of the row."""
    row = panel._bottom_row
    order = [row.itemAt(i).widget() for i in range(row.count())]
    widgets = [w for w in order if w is not None]
    assert widgets == [
        panel._stats_label,
        panel._pipeline_toggle,
        panel._pipeline_target,
        panel._convert_btn,
        panel._send_to_btn,
    ]
    # ...and the only stretch is the one before the toggle.
    stretches = [i for i in range(row.count()) if row.itemAt(i).widget() is None]
    assert len(stretches) == 1
    assert stretches[0] == order.index(panel._pipeline_toggle) - 1


def test_the_toggle_glyph_is_not_translated(panel):
    assert panel._pipeline_toggle.text() == "|"
    assert panel._pipeline_toggle.objectName() == "pipelineToggle"
