"""The Convert panel says "Ready" only for work the engine will actually do.

Quality only goes down: a same-format row needs a strict downgrade, and any
row is refused if it would raise the rate or depth. The table has to agree
with the engine on all of it — otherwise a row reads "Ready", the user presses
Convert, and gets nothing (or an error) back. Both come from _verdict, and
these tests drive the combos the way a user would: pick FLAC, pick 16-bit,
watch the row change.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from src.gui.models.track_model import TrackStore
from src.gui.widgets.conversion_panel import ConversionPanel
from src.utils.config import AppConfig, save_config

STATUS_COLUMN = 3
FROM_COLUMN = 1


def _write(path, samplerate: int, subtype: str) -> str:
    sf = pytest.importorskip("soundfile")
    import numpy as np

    t = np.linspace(0, 0.1, int(samplerate * 0.1), endpoint=False)
    sf.write(str(path), (0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32"),
             samplerate, subtype=subtype)
    return str(path)


@pytest.fixture
def flac_96k_24(tmp_path):
    """A real 96 kHz / 24-bit FLAC — the file this feature exists for."""
    return _write(tmp_path / "tone.flac", 96000, "PCM_24")


@pytest.fixture
def wav_44k_16(tmp_path):
    """A CD-quality WAV — nothing above it can be asked for."""
    return _write(tmp_path / "cd.wav", 44100, "PCM_16")


@pytest.fixture
def panel(qtbot):
    # Settings must be on disk before the widget reads them in __init__.
    save_config(AppConfig(
        convert_target_format="FLAC",
        convert_sample_rate=44100,
        convert_bit_depth=16,
    ))
    widget = ConversionPanel(TrackStore())
    qtbot.addWidget(widget)
    return widget


def _status(panel, row: int = 0) -> str:
    item = panel._file_table.item(row, STATUS_COLUMN)
    return item.text() if item is not None else ""


def _set_bit_depth(panel, bits: int) -> None:
    panel._bitdepth_combo.setCurrentIndex(panel._bitdepth_combo.findData(bits))


def _set_sample_rate(panel, hz: int) -> None:
    panel._samplerate_combo.setCurrentIndex(panel._samplerate_combo.findData(hz))


def test_downgrade_is_ready_and_convertible(panel, flac_96k_24):
    """96 kHz/24-bit FLAC -> 44.1 kHz/16-bit FLAC: the CDJ case."""
    panel.add_files([flac_96k_24])

    assert _status(panel) == "Ready"
    assert panel._convert_btn.isEnabled()


def test_same_settings_stay_same_format(panel, flac_96k_24):
    _set_sample_rate(panel, 96000)
    _set_bit_depth(panel, 24)
    panel.add_files([flac_96k_24])

    assert _status(panel) == "Same format"
    assert not panel._convert_btn.isEnabled()


def test_upsample_stays_same_format(panel, flac_96k_24):
    _set_sample_rate(panel, 96000)
    _set_bit_depth(panel, 32)  # FLAC clamps 32 -> 24, so this is a no-op
    panel.add_files([flac_96k_24])

    assert _status(panel) == "Same format"
    assert not panel._convert_btn.isEnabled()


def test_changing_bit_depth_reruns_the_test(panel, flac_96k_24):
    """The rate/depth combos change the verdict, so they refresh the table."""
    _set_sample_rate(panel, 96000)
    _set_bit_depth(panel, 24)
    panel.add_files([flac_96k_24])
    assert _status(panel) == "Same format"

    _set_bit_depth(panel, 16)

    assert _status(panel) == "Ready"
    assert panel._convert_btn.isEnabled()


def test_convert_emits_the_same_files_the_table_promised(panel, flac_96k_24, qtbot):
    panel.add_files([flac_96k_24])

    with qtbot.waitSignal(panel.start_conversion, timeout=1000) as sig:
        panel._convert_btn.click()

    file_paths, target_format, _bitrate, sample_rate, bit_depth = sig.args
    assert file_paths == [flac_96k_24]
    assert (target_format, sample_rate, bit_depth) == ("FLAC", 44100, 16)


def test_no_convert_when_nothing_is_a_downgrade(panel, flac_96k_24):
    """A dead Convert button can't be pressed, but the guard is in the click
    path too — the button is the only thing that ever called it."""
    _set_sample_rate(panel, 96000)
    _set_bit_depth(panel, 24)
    panel.add_files([flac_96k_24])

    emitted = []
    panel.start_conversion.connect(lambda *a: emitted.append(a))
    panel._on_convert_clicked()

    assert emitted == []


def test_cross_format_at_equal_settings_is_ready(panel, flac_96k_24):
    """Same rate and depth as the source, different container: still Ready.

    The downgrade requirement is for the source's own format only — applying
    it here would break the everyday container change."""
    _set_sample_rate(panel, 96000)
    _set_bit_depth(panel, 24)
    panel._format_combo.setCurrentText("AIFF")
    panel.add_files([flac_96k_24])

    assert _status(panel) == "Ready"
    assert panel._convert_btn.isEnabled()


def test_from_column_shows_what_the_rule_compared(panel, flac_96k_24):
    """The user needs to see the source's rate/depth to make sense of it."""
    panel.add_files([flac_96k_24])
    assert panel._file_table.item(0, FROM_COLUMN).text() == "FLAC 96k/24"


def test_blocked_row_says_why(panel, flac_96k_24):
    _set_sample_rate(panel, 96000)
    _set_bit_depth(panel, 24)
    panel.add_files([flac_96k_24])

    tooltip = panel._file_table.item(0, STATUS_COLUMN).toolTip()
    assert "lower" in tooltip


def test_cross_format_upsample_is_refused(panel, wav_44k_16):
    """44.1k/16 WAV -> FLAC at 96k/24 would invent quality, so the row won't run."""
    _set_sample_rate(panel, 96000)
    _set_bit_depth(panel, 24)
    panel.add_files([wav_44k_16])

    assert _status(panel) == "Would upsample"
    assert not panel._convert_btn.isEnabled()
    assert "no higher" in panel._file_table.item(0, STATUS_COLUMN).toolTip()


def test_one_axis_up_is_enough_to_refuse(panel, flac_96k_24):
    """Rate down, depth up: the depth is still invented."""
    _set_sample_rate(panel, 44100)
    _set_bit_depth(panel, 32)
    panel._format_combo.setCurrentText("WAV")
    panel.add_files([flac_96k_24])

    assert _status(panel) == "Would upsample"


def test_lowering_the_setting_clears_the_refusal(panel, wav_44k_16):
    _set_sample_rate(panel, 96000)
    _set_bit_depth(panel, 24)
    panel._format_combo.setCurrentText("FLAC")
    panel.add_files([wav_44k_16])
    assert _status(panel) == "Would upsample"

    _set_sample_rate(panel, 44100)
    _set_bit_depth(panel, 16)

    assert _status(panel) == "Ready"
    assert panel._convert_btn.isEnabled()


def test_mp3_target_is_exempt_from_the_rule(panel, wav_44k_16):
    """The rate/depth selectors don't apply to MP3 — they're hidden for it."""
    _set_sample_rate(panel, 96000)
    _set_bit_depth(panel, 32)
    panel._format_combo.setCurrentText("MP3")
    panel.add_files([wav_44k_16])

    assert _status(panel) == "Ready"
    assert panel._convert_btn.isEnabled()


def test_a_refused_row_is_not_sent_to_the_worker(panel, wav_44k_16, flac_96k_24):
    """Mixed batch: the downgradeable file converts, the upsample doesn't."""
    _set_sample_rate(panel, 96000)
    _set_bit_depth(panel, 24)
    panel._format_combo.setCurrentText("AIFF")
    panel.add_files([wav_44k_16, flac_96k_24])

    emitted = []
    panel.start_conversion.connect(lambda paths, *_: emitted.append(paths))
    panel._convert_btn.click()

    assert emitted == [[flac_96k_24]]


def test_unreadable_same_format_file_is_not_offered(panel, tmp_path):
    """An unmeasurable file keeps the old behaviour rather than guessing."""
    broken = tmp_path / "broken.flac"
    broken.write_text("")
    panel.add_files([str(broken)])

    assert _status(panel) == "Same format"
    assert not panel._convert_btn.isEnabled()
