"""Tests for the `convert` CLI subcommand.

Covers argument wiring, the dry-run planner (no disk writes), and real
WAV->FLAC conversion driven through run_convert(). Conversion tests are
skipped if soundfile is unavailable.
"""

import json
import sys

import pytest

from src import cli
from src.conversion.result import ConversionResult, resolve_output_path


def _make_args(**overrides):
    """Build a Namespace matching the convert subparser defaults."""
    import argparse

    defaults = dict(
        command="convert",
        path=None,
        recursive=False,
        to="FLAC",
        output_dir=None,
        bitrate=320,
        sample_rate=None,
        bit_depth=None,
        format="table",
        dry_run=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture
def wav_file(tmp_path):
    """Write a short, real WAV file so conversion actually runs."""
    sf = pytest.importorskip("soundfile")
    import numpy as np

    path = tmp_path / "tone.wav"
    samplerate = 44100
    t = np.linspace(0, 0.25, int(samplerate * 0.25), endpoint=False)
    data = (0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32")
    sf.write(str(path), data, samplerate, subtype="PCM_16")
    return path


class TestConvertArgWiring:
    """The subparser is registered and parses as expected."""

    def test_convert_subcommand_parses(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(cli, "run_convert", lambda args: captured.update(vars(args)))
        monkeypatch.setattr(sys, "argv", ["mixed-in-p", "convert", "song.wav", "-t", "MP3"])
        cli.main()
        assert captured["command"] == "convert"
        assert captured["to"] == "MP3"
        assert captured["path"] == "song.wav"

    def test_to_is_required(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["mixed-in-p", "convert", "song.wav"])
        with pytest.raises(SystemExit):
            cli.main()


class TestConvertDryRun:
    """Dry run classifies files without writing anything."""

    def test_plan_skip_and_block(self, tmp_path, capsys):
        # WAV -> FLAC: planned. FLAC -> FLAC: skipped. MP3 -> FLAC: blocked.
        (tmp_path / "a.wav").write_text("")
        (tmp_path / "b.flac").write_text("")
        (tmp_path / "c.mp3").write_text("")

        cli.run_convert(_make_args(path=str(tmp_path), to="FLAC", dry_run=True, format="json"))
        report = json.loads(capsys.readouterr().out)

        by_status = {r["status"] for r in report}
        assert by_status == {"planned", "skipped", "blocked"}

        planned = [r for r in report if r["status"] == "planned"][0]
        assert planned["source_path"].endswith("a.wav")
        assert planned["output_path"].endswith("a.flac")

        blocked = [r for r in report if r["status"] == "blocked"][0]
        assert blocked["source_path"].endswith("c.mp3")
        assert "lossy" in blocked["error"]

    def test_dry_run_writes_nothing(self, tmp_path):
        (tmp_path / "a.wav").write_text("")
        cli.run_convert(_make_args(path=str(tmp_path), to="FLAC", dry_run=True))
        # No .flac produced.
        assert list(tmp_path.glob("*.flac")) == []

    def test_aif_normalises_to_aiff_skip(self, tmp_path, capsys):
        (tmp_path / "x.aif").write_text("")
        cli.run_convert(_make_args(path=str(tmp_path), to="AIFF", dry_run=True, format="json"))
        report = json.loads(capsys.readouterr().out)
        assert report[0]["status"] == "skipped"

    def test_dry_run_predicts_deduped_name(self, tmp_path, capsys):
        # An existing tone.flac forces the real run to write "tone (1).flac";
        # the dry run must predict that exact name, not "tone.flac".
        (tmp_path / "tone.wav").write_text("")
        (tmp_path / "tone.flac").write_text("")
        cli.run_convert(_make_args(path=str(tmp_path), to="FLAC", dry_run=True, format="json"))
        report = json.loads(capsys.readouterr().out)
        planned = [r for r in report if r["status"] == "planned"]
        assert len(planned) == 1
        assert planned[0]["output_path"].endswith("tone (1).flac")


class TestResolveOutputPath:
    """The shared name resolver — single source of truth for output names."""

    def test_basic_name(self, tmp_path):
        src = tmp_path / "tone.wav"
        src.write_text("")
        assert resolve_output_path(str(src), ".flac") == tmp_path / "tone.flac"

    def test_collision_appends_counter(self, tmp_path):
        src = tmp_path / "tone.wav"
        src.write_text("")
        (tmp_path / "tone.flac").write_text("")
        assert resolve_output_path(str(src), ".flac") == tmp_path / "tone (1).flac"

    def test_multiple_collisions(self, tmp_path):
        src = tmp_path / "tone.wav"
        src.write_text("")
        (tmp_path / "tone.flac").write_text("")
        (tmp_path / "tone (1).flac").write_text("")
        assert resolve_output_path(str(src), ".flac") == tmp_path / "tone (2).flac"

    def test_output_dir_honored(self, tmp_path):
        src = tmp_path / "tone.wav"
        src.write_text("")
        dest = tmp_path / "out"
        dest.mkdir()
        assert resolve_output_path(str(src), ".flac", str(dest)) == dest / "tone.flac"


class TestConvertExecution:
    """Real conversion through the engine."""

    def test_wav_to_flac(self, wav_file, capsys):
        cli.run_convert(_make_args(path=str(wav_file), to="FLAC", format="json"))
        report = json.loads(capsys.readouterr().out)

        assert len(report) == 1
        assert report[0]["status"] == "ok"
        assert report[0]["output_path"].endswith(".flac")
        assert (wav_file.parent / "tone.flac").exists()

    def test_same_format_skipped(self, wav_file, capsys):
        cli.run_convert(_make_args(path=str(wav_file), to="WAV", format="json"))
        report = json.loads(capsys.readouterr().out)
        assert report[0]["status"] == "skipped"
        assert report[0]["output_path"] is None

    def test_missing_path_exits(self):
        with pytest.raises(SystemExit):
            cli.run_convert(_make_args(path="/no/such/path", to="FLAC"))


class TestConvertOutputHelpers:
    """Output formatters handle the three non-error outcomes."""

    def test_json_status_mapping(self, capsys):
        results = [
            ConversionResult("a.wav", "a.flac", "FLAC"),
            ConversionResult("b.flac", "", "FLAC", skipped=True),
            ConversionResult("c.flac", "", "FLAC", error="lost sync", incomplete=True),
        ]
        cli.convert_output_json(results)
        report = json.loads(capsys.readouterr().out)
        assert [r["status"] for r in report] == ["ok", "skipped", "error"]
        assert report[1]["output_path"] is None
        assert report[2]["incomplete"] is True

    def test_table_summary_counts(self, capsys):
        results = [
            ConversionResult("a.wav", "a.flac", "FLAC"),
            ConversionResult("b.flac", "", "FLAC", skipped=True),
            ConversionResult("c.flac", "", "FLAC", error="boom"),
        ]
        cli.convert_output_table(results)
        out = capsys.readouterr().out
        assert "1 converted, 1 skipped, 1 failed." in out
