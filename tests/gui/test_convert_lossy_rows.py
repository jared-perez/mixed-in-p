"""A lossy file moved into Convert lands as a row, and can only get smaller.

Convert used to refuse lossy files at the door, but a move from Rename (or
any panel) had already taken them out of their old home, so a refused MP3 was
in no panel at all. Now it gets a row whose status says what it can't do, and
the one conversion a lossy source is allowed — MP3 to a lower-bitrate MP3 —
runs the same way every other row does: the table, the button and the engine
all agree.
"""

from __future__ import annotations

import pytest

from src.conversion.converter import convert_file
from src.conversion.result import read_mp3_bitrate
from src.gui.models.track_model import TrackStore
from src.gui.widgets.conversion_panel import ConversionPanel
from src.utils.config import AppConfig, save_config

STATUS_COLUMN = 3
FROM_COLUMN = 1


def _mp3(path, kbps: int) -> str:
    """A real, short MP3 at the given bitrate."""
    lameenc = pytest.importorskip("lameenc")
    import numpy as np

    rate = 44100
    t = np.linspace(0, 0.5, int(rate * 0.5), endpoint=False)
    pcm = (0.2 * np.sin(2 * np.pi * 440 * t) * 32767).astype("int16")
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(kbps)
    encoder.set_in_sample_rate(rate)
    encoder.set_channels(1)
    encoder.set_quality(2)
    data = encoder.encode(pcm.tobytes()) + encoder.flush()
    path.write_bytes(data)
    return str(path)


@pytest.fixture
def mp3_320(tmp_path):
    return _mp3(tmp_path / "track.mp3", 320)


def _panel(qtbot, target: str, bitrate: int = 192) -> ConversionPanel:
    save_config(AppConfig(convert_target_format=target, convert_mp3_bitrate=bitrate))
    widget = ConversionPanel(TrackStore())
    qtbot.addWidget(widget)
    return widget


def _status(panel, row: int = 0) -> str:
    item = panel._file_table.item(row, STATUS_COLUMN)
    return item.text() if item is not None else ""


class TestTheRow:
    def test_an_mp3_moved_here_is_a_row(self, qtbot, mp3_320):
        panel = _panel(qtbot, "FLAC")
        panel.add_files([mp3_320])

        assert panel._file_table.rowCount() == 1
        assert _status(panel) == "Lossy source"
        assert not panel._convert_btn.isEnabled()

    def test_it_shows_its_bitrate(self, qtbot, mp3_320):
        panel = _panel(qtbot, "FLAC")
        panel.add_files([mp3_320])
        assert panel._file_table.item(0, FROM_COLUMN).text() == "MP3 320 kbps"

    def test_a_lower_mp3_bitrate_is_ready(self, qtbot, mp3_320):
        panel = _panel(qtbot, "MP3", bitrate=192)
        panel.add_files([mp3_320])

        assert _status(panel) == "Ready"
        assert panel._convert_btn.isEnabled()

    def test_the_same_bitrate_is_same_format(self, qtbot, mp3_320):
        panel = _panel(qtbot, "MP3", bitrate=320)
        panel.add_files([mp3_320])

        assert _status(panel) == "Same format"
        assert not panel._convert_btn.isEnabled()

    def test_changing_the_bitrate_reruns_the_test(self, qtbot, mp3_320):
        panel = _panel(qtbot, "MP3", bitrate=320)
        panel.add_files([mp3_320])
        panel._bitrate_combo.setCurrentText("128")
        assert _status(panel) == "Ready"

    def test_it_can_be_selected_and_removed(self, qtbot, mp3_320, tmp_path):
        """Rows map onto paths the same way for lossy and lossless files."""
        wav = str(tmp_path / "a.wav")
        panel = _panel(qtbot, "FLAC")
        panel.add_files([wav, mp3_320])
        panel._file_table.selectRow(1)

        assert panel._selected_source_paths() == [mp3_320]
        panel._on_remove_selected()
        assert panel._file_paths == [wav]

    def test_convert_sends_only_the_ready_mp3(self, qtbot, mp3_320, tmp_path):
        other = _mp3(tmp_path / "low.mp3", 128)
        panel = _panel(qtbot, "MP3", bitrate=192)
        panel.add_files([mp3_320, other])

        with qtbot.waitSignal(panel.start_conversion, timeout=1000) as sig:
            panel._convert_btn.click()
        assert sig.args[0] == [mp3_320]

    def test_lossy_rows_held(self, qtbot, mp3_320):
        panel = _panel(qtbot, "FLAC")
        panel.add_files([mp3_320])
        assert panel.lossy_rows_held([mp3_320])
        panel._format_combo.setCurrentText("MP3")
        assert not panel.lossy_rows_held([mp3_320])


class TestTheEngine:
    def test_an_mp3_becomes_a_smaller_mp3(self, mp3_320, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        result = convert_file(mp3_320, "MP3", output_dir=str(out), bitrate=128)

        assert result.error is None and not result.skipped
        assert read_mp3_bitrate(result.output_path) == 128

    def test_the_same_bitrate_is_skipped(self, mp3_320):
        result = convert_file(mp3_320, "MP3", bitrate=320)
        assert result.skipped and result.error is None

    def test_lossless_is_refused(self, mp3_320):
        result = convert_file(mp3_320, "FLAC")
        assert result.error == "Lossy-to-lossless conversion is not supported"

    def test_other_lossy_formats_are_refused(self, tmp_path):
        ogg = tmp_path / "x.ogg"
        ogg.write_bytes(b"")
        result = convert_file(str(ogg), "MP3", bitrate=128)
        assert result.error == "Only an MP3 source can be re-encoded to MP3"


class TestTheCliDryRun:
    """The third call site: the dry run predicts what convert_file does."""

    def _report(self, path, to, bitrate, capsys):
        import json

        from src import cli
        from tests.test_cli_convert import _make_args

        cli.run_convert(_make_args(path=path, to=to, bitrate=bitrate,
                                   dry_run=True, format="json"))
        return json.loads(capsys.readouterr().out)[0]["status"]

    def test_a_lower_bitrate_is_planned(self, mp3_320, capsys):
        assert self._report(mp3_320, "MP3", 192, capsys) == "planned"

    def test_the_same_bitrate_is_skipped(self, mp3_320, capsys):
        assert self._report(mp3_320, "MP3", 320, capsys) == "skipped"

    def test_lossless_is_blocked(self, mp3_320, capsys):
        assert self._report(mp3_320, "FLAC", 320, capsys) == "blocked"
