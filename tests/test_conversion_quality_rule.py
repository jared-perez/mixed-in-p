"""Quality only ever goes down.

One rule, applied in two places. Between two formats, equal settings are the
point — a container change — so only a *raise* is refused. Into the format the
file already has, equal settings would just rewrite it, so it takes a strict
downgrade to be worth doing: a 96 kHz/24-bit FLAC becoming 44.1 kHz/16-bit
FLAC to play on older CDJs.

The two are deliberately different verdicts. A same-format no-op is `skipped`
(nothing was asked for that isn't already true); an upsample is an `error`,
the same refusal a lossy source gets, because the user did ask for something
and is not going to get it.
"""

from __future__ import annotations

import pytest

from src.conversion.converter import convert_file
from src.conversion.result import (
    effective_bit_depth,
    is_quality_downgrade,
    is_same_format,
    raises_quality,
)


def _write(path, samplerate: int, subtype: str) -> str:
    """Write a short real tone so soundfile can read its rate/depth back."""
    sf = pytest.importorskip("soundfile")
    import numpy as np

    t = np.linspace(0, 0.1, int(samplerate * 0.1), endpoint=False)
    data = (0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32")
    # soundfile can read a .aif but cannot infer the format when writing one.
    fmt = "AIFF" if path.suffix.lower() == ".aif" else None
    sf.write(str(path), data, samplerate, subtype=subtype, format=fmt)
    return str(path)


class TestIsQualityDowngrade:
    """The pure rule, shared by the engine, the CLI dry run and the panel."""

    def test_lower_bit_depth_at_same_rate(self):
        assert is_quality_downgrade(44100, 24, ".flac", 44100, 16)

    def test_lower_rate_at_same_depth(self):
        assert is_quality_downgrade(96000, 16, ".wav", 44100, 16)

    def test_both_lower(self):
        assert is_quality_downgrade(96000, 24, ".flac", 44100, 16)

    def test_identical_settings_are_not(self):
        assert not is_quality_downgrade(44100, 16, ".flac", 44100, 16)

    def test_higher_is_not(self):
        assert not is_quality_downgrade(44100, 16, ".flac", 96000, 24)

    def test_mixed_is_not(self):
        """One down, one up is still an upsample on the axis that went up."""
        assert not is_quality_downgrade(96000, 16, ".flac", 44100, 24)
        assert not is_quality_downgrade(44100, 24, ".flac", 96000, 16)

    def test_none_target_means_keep_the_source(self):
        assert not is_quality_downgrade(96000, 24, ".flac", None, None)
        assert is_quality_downgrade(96000, 24, ".flac", None, 16)
        assert is_quality_downgrade(96000, 24, ".flac", 44100, None)

    def test_unknown_source_is_never_a_downgrade(self):
        """An unreadable file is skipped rather than rewritten on a guess."""
        assert not is_quality_downgrade(None, None, ".flac", 44100, 16)
        assert not is_quality_downgrade(44100, None, ".flac", 44100, 16)

    def test_flac_clamp_is_applied_before_comparing(self):
        """FLAC writes 32-bit as 24, so asking for 32 on a 24-bit FLAC would
        rewrite the same 24 bits — not a downgrade, and not an upgrade either."""
        assert effective_bit_depth(32, ".flac") == 24
        assert effective_bit_depth(8, ".flac") == 16
        assert effective_bit_depth(32, ".wav") == 32
        assert not is_quality_downgrade(44100, 24, ".flac", 44100, 32)
        # ...but on WAV, 32-bit really is 32-bit, so it is an upsample.
        assert not is_quality_downgrade(44100, 24, ".wav", 44100, 32)

    def test_float_source_counts_as_its_storage_width(self):
        """32-bit float WAV -> 24-bit PCM WAV loses width, so it converts."""
        assert is_quality_downgrade(44100, 32, ".wav", 44100, 24)


class TestRaisesQuality:
    """The cross-format half: equal is fine, higher is not."""

    def test_equal_settings_are_not_a_raise(self):
        """The everyday container change — WAV 44.1/16 -> FLAC 44.1/16."""
        assert not raises_quality(44100, 16, ".flac", 44100, 16)

    def test_higher_rate_is(self):
        assert raises_quality(44100, 16, ".flac", 96000, 16)

    def test_higher_depth_is(self):
        assert raises_quality(44100, 16, ".wav", 44100, 24)

    def test_lower_is_not(self):
        assert not raises_quality(96000, 24, ".flac", 44100, 16)

    def test_one_axis_up_is_enough(self):
        """Trading rate for depth still invents the depth."""
        assert raises_quality(96000, 16, ".flac", 44100, 24)

    def test_none_target_means_keep_the_source(self):
        assert not raises_quality(44100, 16, ".flac", None, None)

    def test_unknown_source_is_never_a_raise(self):
        """Unmeasurable files convert or fail on their own merits, as before."""
        assert not raises_quality(None, None, ".flac", 96000, 24)

    def test_flac_clamp_applies_here_too(self):
        """32-bit into FLAC really writes 24, so it doesn't raise a 24-bit source."""
        assert not raises_quality(44100, 24, ".flac", 44100, 32)
        assert raises_quality(44100, 24, ".wav", 44100, 32)


class TestIsSameFormat:
    def test_matches_by_extension(self):
        assert is_same_format("/music/a.flac", ".flac")
        assert not is_same_format("/music/a.wav", ".flac")

    def test_aif_counts_as_aiff(self):
        assert is_same_format("/music/a.aif", ".aiff")
        assert is_same_format("/music/A.AIFF", ".aiff")


class TestSameFormatConversion:
    """End-to-end through convert_file, which owns the skip decision."""

    def test_flac_24_to_16_converts(self, tmp_path):
        sf = pytest.importorskip("soundfile")
        src = _write(tmp_path / "tone.flac", 96000, "PCM_24")

        result = convert_file(src, "FLAC", sample_rate=44100, bit_depth=16)

        assert result.error is None
        assert not result.skipped
        # The source is never clobbered: its own name is taken, so the output
        # dedupes to "tone (1).flac".
        assert result.output_path.endswith("tone (1).flac")
        info = sf.info(result.output_path)
        assert info.samplerate == 44100
        assert info.subtype == "PCM_16"
        # Source untouched.
        assert sf.info(src).samplerate == 96000

    def test_bit_depth_only_downgrade_converts(self, tmp_path):
        sf = pytest.importorskip("soundfile")
        src = _write(tmp_path / "tone.flac", 44100, "PCM_24")

        result = convert_file(src, "FLAC", sample_rate=44100, bit_depth=16)

        assert not result.skipped and result.error is None
        assert sf.info(result.output_path).subtype == "PCM_16"

    def test_sample_rate_only_downgrade_converts(self, tmp_path):
        sf = pytest.importorskip("soundfile")
        src = _write(tmp_path / "tone.wav", 96000, "PCM_16")

        result = convert_file(src, "WAV", sample_rate=44100, bit_depth=16)

        assert not result.skipped and result.error is None
        assert sf.info(result.output_path).samplerate == 44100

    def test_identical_settings_skip(self, tmp_path):
        src = _write(tmp_path / "tone.flac", 44100, "PCM_16")
        result = convert_file(src, "FLAC", sample_rate=44100, bit_depth=16)
        assert result.skipped
        assert result.output_path == ""

    def test_upsample_skips(self, tmp_path):
        src = _write(tmp_path / "tone.flac", 44100, "PCM_16")
        result = convert_file(src, "FLAC", sample_rate=96000, bit_depth=24)
        assert result.skipped
        assert not list(tmp_path.glob("tone (1).flac"))

    def test_mixed_up_and_down_skips(self, tmp_path):
        src = _write(tmp_path / "tone.flac", 96000, "PCM_16")
        result = convert_file(src, "FLAC", sample_rate=44100, bit_depth=24)
        assert result.skipped

    def test_no_settings_still_skips(self, tmp_path):
        """The CLI without --sample-rate/--bit-depth keeps the old behaviour."""
        src = _write(tmp_path / "tone.wav", 44100, "PCM_16")
        assert convert_file(src, "WAV").skipped

    def test_unreadable_same_format_skips(self, tmp_path):
        src = tmp_path / "broken.flac"
        src.write_text("")
        result = convert_file(str(src), "FLAC", sample_rate=44100, bit_depth=16)
        assert result.skipped
        assert result.error is None

    def test_aif_downgrades_as_aiff(self, tmp_path):
        sf = pytest.importorskip("soundfile")
        src = _write(tmp_path / "tone.aif", 48000, "PCM_24")

        result = convert_file(src, "AIFF", sample_rate=44100, bit_depth=16)

        assert not result.skipped and result.error is None
        assert result.output_path.endswith("tone.aiff")
        assert sf.info(result.output_path).subtype == "PCM_16"

    def test_cross_format_at_equal_settings_still_converts(self, tmp_path):
        """The container change is the point; it must not become a downgrade test."""
        src = _write(tmp_path / "tone.wav", 44100, "PCM_16")
        result = convert_file(src, "FLAC", sample_rate=44100, bit_depth=16)
        assert not result.skipped and result.error is None


class TestKeepSource:
    """bit_depth=None hands the source's own subtype to the writer, and the
    containers do not all hold the same ones."""

    def test_float_wav_to_flac_falls_back_to_24_bit(self, tmp_path):
        """FLAC has no FLOAT, and 32-bit float is what a DAW exports. Without
        a fallback this is the everyday file that "Keep source" would fail on."""
        sf = pytest.importorskip("soundfile")
        src = _write(tmp_path / "render.wav", 44100, "FLOAT")

        result = convert_file(src, "FLAC")

        assert result.error is None and not result.skipped
        assert sf.info(result.output_path).subtype == "PCM_24"

    def test_eight_bit_wav_to_flac_stays_eight_bit(self, tmp_path):
        """FLAC has no PCM_U8 but does have PCM_S8 — match the width, don't
        jump to 24-bit just because it is the first thing that fits."""
        sf = pytest.importorskip("soundfile")
        src = _write(tmp_path / "old.wav", 22050, "PCM_U8")

        result = convert_file(src, "FLAC")

        assert result.error is None
        assert sf.info(result.output_path).subtype == "PCM_S8"

    def test_rate_is_untouched(self, tmp_path):
        """The rescue case: 22.05 kHz is below every rate the GUI offers."""
        sf = pytest.importorskip("soundfile")
        src = _write(tmp_path / "old.wav", 22050, "PCM_16")

        result = convert_file(src, "FLAC", sample_rate=None, bit_depth=None)

        assert result.error is None
        info = sf.info(result.output_path)
        assert info.samplerate == 22050
        assert info.subtype == "PCM_16"

    def test_one_axis_kept_one_lowered(self, tmp_path):
        sf = pytest.importorskip("soundfile")
        src = _write(tmp_path / "tone.flac", 96000, "PCM_24")

        result = convert_file(src, "AIFF", sample_rate=None, bit_depth=16)

        assert result.error is None
        info = sf.info(result.output_path)
        assert info.samplerate == 96000
        assert info.subtype == "PCM_16"

    def test_keeping_both_into_the_same_format_is_a_no_op(self, tmp_path):
        src = _write(tmp_path / "tone.flac", 96000, "PCM_24")
        assert convert_file(src, "FLAC", sample_rate=None, bit_depth=None).skipped


class TestCrossFormatUpsample:
    """A different format is free to keep the quality — never to raise it."""

    def test_higher_rate_is_refused(self, tmp_path):
        src = _write(tmp_path / "tone.wav", 44100, "PCM_16")

        result = convert_file(src, "FLAC", sample_rate=96000, bit_depth=16)

        assert result.error == (
            "Upsampling to a higher sample rate or bit depth is not supported"
        )
        assert result.output_path == ""
        assert not result.skipped
        assert not list(tmp_path.glob("*.flac"))

    def test_higher_bit_depth_is_refused(self, tmp_path):
        src = _write(tmp_path / "tone.wav", 44100, "PCM_16")
        result = convert_file(src, "AIFF", sample_rate=44100, bit_depth=24)
        # Pinned to the message, not just "an error" — a soundfile failure
        # would otherwise let this pass for the wrong reason.
        assert result.error is not None and result.error.startswith("Upsampling")
        assert not list(tmp_path.glob("*.aiff"))

    def test_downgrade_across_formats_still_converts(self, tmp_path):
        sf = pytest.importorskip("soundfile")
        src = _write(tmp_path / "tone.flac", 96000, "PCM_24")

        result = convert_file(src, "AIFF", sample_rate=44100, bit_depth=16)

        assert result.error is None and not result.skipped
        assert sf.info(result.output_path).samplerate == 44100

    def test_no_settings_keeps_the_source_and_converts(self, tmp_path):
        """`convert -t FLAC` with no rate/depth flags is not an upsample."""
        src = _write(tmp_path / "tone.wav", 96000, "PCM_24")
        result = convert_file(src, "FLAC")
        assert result.error is None and not result.skipped

    def test_mp3_target_is_exempt(self, tmp_path):
        """MP3's axis is the bitrate; _convert_to_mp3 ignores rate/depth."""
        pytest.importorskip("lameenc")
        src = _write(tmp_path / "tone.wav", 44100, "PCM_16")

        result = convert_file(src, "MP3", sample_rate=96000, bit_depth=32, bitrate=320)

        assert result.error is None and not result.skipped
        assert result.output_path.endswith(".mp3")

    def test_unreadable_source_is_not_preblocked(self, tmp_path):
        """We can't measure it, so it goes through and fails for a real reason."""
        src = tmp_path / "broken.flac"
        src.write_text("")
        result = convert_file(str(src), "WAV", sample_rate=96000, bit_depth=24)
        assert result.error is not None
        assert "Upsampling" not in result.error
