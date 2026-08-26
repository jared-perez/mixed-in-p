"""The Convert panel's Convert-step toggle and what it does to the button.

Structure, never pixels — the suite runs with no application stylesheet, so a
width measured here is a width of a different app (CLAUDE.md).

The target playlist used to live here and now lives in the header; its tests
moved with it, to test_pipeline_cluster.py.
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


def test_toggling_on_renames_the_button(panel):
    panel._pipeline_toggle.setChecked(True)
    assert panel.pipeline_enabled()
    assert panel._convert_btn.text() == "Start Pipeline"
    assert panel._convert_btn.toolTip()


def test_the_toggle_tooltip_says_what_the_next_click_does(panel):
    off = panel._pipeline_toggle.toolTip()
    panel._pipeline_toggle.setChecked(True)
    on = panel._pipeline_toggle.toolTip()
    assert off != on
    assert "Include" in off and "Leave" in on


def test_toggling_emits_for_the_mirror(panel, qtbot):
    with qtbot.waitSignal(panel.pipeline_toggled) as caught:
        panel._pipeline_toggle.setChecked(True)
    assert caught.args == [True]


def test_set_pipeline_enabled_is_a_reflect_not_an_act(panel):
    """MainWindow calls this when the header's mini is clicked; it must not
    come back round as a toggle the user made here."""
    seen = []
    panel.pipeline_toggled.connect(seen.append)
    panel._pipeline_toggle.setChecked(True)
    assert seen == [True]
    panel.set_pipeline_enabled(False)
    assert seen == [True]  # no echo
    assert not panel.pipeline_enabled()
    assert panel._convert_btn.text() == "Convert"


# ---------------------------------------------------------------- enablement


def test_start_pipeline_needs_forwardable_rows(qtbot, tmp_path):
    panel = _panel(qtbot)
    panel._pipeline_toggle.setChecked(True)
    assert not panel._convert_btn.isEnabled()
    panel.add_files([_write(tmp_path / "a.wav")])
    assert panel._convert_btn.isEnabled()


def test_start_pipeline_does_not_wait_for_a_target(qtbot, tmp_path):
    """The target is in the header now. A button greyed for the want of it is
    greyed for a reason nowhere near it, so the press explains itself instead."""
    panel = _panel(qtbot)
    panel.add_files([_write(tmp_path / "a.wav")])
    panel._pipeline_toggle.setChecked(True)
    assert panel._convert_btn.isEnabled()


def test_start_is_enabled_for_a_batch_with_nothing_to_convert(qtbot, tmp_path):
    """Every row already in the target format: Convert is dead, Start is not."""
    panel = _panel(qtbot, convert_target_format="WAV")
    panel.add_files([_write(tmp_path / "a.wav")])
    assert not panel._convert_btn.isEnabled()  # Same format
    panel._pipeline_toggle.setChecked(True)
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


# -------------------------------------------------------------- persistence


def test_the_stored_step_is_shown_on_the_way_in(qtbot):
    panel = _panel(qtbot, pipeline_convert_enabled=True)
    assert panel.pipeline_enabled()
    assert panel._convert_btn.text() == "Start Pipeline"


def test_the_panel_never_writes_the_step_itself(qtbot):
    """A step appears here and again in the header, so MainWindow owns all
    four pipeline fields — two writers would only drift."""
    panel = _panel(qtbot)
    panel._pipeline_toggle.setChecked(True)
    panel._format_combo.setCurrentText("WAV")  # forces a settings write
    assert load_config().pipeline_convert_enabled is False


def test_the_toggle_survives_auto_analyze_being_off(qtbot):
    """The two settings were coupled while the pipeline was a Convert feature
    that could only end in an analysis. It drives its own now."""
    save_config(AppConfig(auto_analyze=False, pipeline_convert_enabled=True,
                          pipeline_playlist="Set"))
    assert load_config().pipeline_convert_enabled is True
    panel = ConversionPanel(TrackStore())
    qtbot.addWidget(panel)
    assert panel.pipeline_enabled()


def test_loading_the_panel_does_not_write_back(qtbot):
    """The restore runs inside the _loading_settings guard."""
    save_config(AppConfig(pipeline_convert_enabled=True,
                          pipeline_playlist="Set",
                          convert_target_format="WAV"))
    panel = ConversionPanel(TrackStore())
    qtbot.addWidget(panel)
    disk = load_config()
    assert disk.pipeline_playlist == "Set"
    assert disk.convert_target_format == "WAV"


# ------------------------------------------------------------------ the row


def test_the_bottom_row_reports_a_real_minimum(panel):
    """Not a pixel assertion: only that the row's spacing was set, so the sum
    adds where it means to add (an unset QLayout answers -1)."""
    assert panel._bottom_row.spacing() > 0
    assert panel.bottom_row_min_width() > panel._convert_btn.sizeHint().width()


def test_the_pipeline_toggle_sits_beside_the_convert_button(panel):
    """Ordered [stats][stretch][triangle][Convert]: the step toggle is next to
    the button it re-labels, not adrift in the middle of the row."""
    row = panel._bottom_row
    order = [row.itemAt(i).widget() for i in range(row.count())]
    widgets = [w for w in order if w is not None]
    assert widgets == [
        panel._stats_label,
        panel._pipeline_toggle,
        panel._convert_btn,
    ]
    # ...and the only stretch is the one before the toggle.
    stretches = [i for i in range(row.count()) if row.itemAt(i).widget() is None]
    assert len(stretches) == 1
    assert stretches[0] == order.index(panel._pipeline_toggle) - 1


def test_the_toggle_is_a_step_triangle(panel):
    from src.gui.widgets.pipeline_toggle import PipelineToggle

    assert isinstance(panel._pipeline_toggle, PipelineToggle)
    assert panel._pipeline_toggle.isCheckable()


def test_send_to_is_gone(panel):
    """Sidebar drag covers every route it offered; the signals stay for a CLI."""
    assert not hasattr(panel, "_send_to_btn")
    assert hasattr(panel, "send_to_analyze")
    assert hasattr(panel, "send_to_rename")
    assert hasattr(panel, "send_to_player")
