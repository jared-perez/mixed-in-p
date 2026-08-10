"""Lightweight conversion result types and constants.

This module has NO heavy dependencies (no soundfile).
Import freely without triggering slow library loads.
"""

from __future__ import annotations

from dataclasses import dataclass

LOSSLESS_EXTENSIONS = {".wav", ".flac", ".aiff", ".aif"}
LOSSY_EXTENSIONS = {".mp3", ".m4a", ".ogg"}
FORMAT_EXTENSION = {"WAV": ".wav", "FLAC": ".flac", "AIFF": ".aiff", "MP3": ".mp3"}

# Bits per sample by soundfile subtype. FLOAT/DOUBLE keep their storage width
# so a 32-bit float source still reads as wider than 24-bit PCM.
SUBTYPE_BITS = {
    "PCM_S8": 8,
    "PCM_U8": 8,
    "PCM_16": 16,
    "PCM_24": 24,
    "PCM_32": 32,
    "FLOAT": 32,
    "DOUBLE": 64,
}


def is_lossless(file_path: str) -> bool:
    """Check if a file is a lossless audio format."""
    from pathlib import Path
    return Path(file_path).suffix.lower() in LOSSLESS_EXTENSIONS


def read_audio_quality(file_path: str) -> tuple[int | None, int | None]:
    """Return (sample rate, bit depth) for a file, or (None, None) if unreadable.

    Unreadable is not an error here — it is the "we don't know" answer that
    is_quality_downgrade turns into a skip.
    """
    try:
        import soundfile as sf
        info = sf.info(file_path)
        return info.samplerate, SUBTYPE_BITS.get(info.subtype)
    except Exception:
        return None, None


def effective_bit_depth(bit_depth: int | None, target_ext: str) -> int | None:
    """The bit depth actually written for a target format.

    FLAC has no 32- or 8-bit PCM, so the writer clamps to 24 / 16 (see
    _resolve_subtype in converter.py). The downgrade rule has to compare
    against what lands on disk, not what was asked for, or "24-bit FLAC ->
    32 bit" reads as an upgrade when it would rewrite the same 24 bits.
    """
    if bit_depth is None:
        return None
    if target_ext == ".flac":
        if bit_depth == 32:
            return 24
        if bit_depth == 8:
            return 16
    return bit_depth


def is_same_format(file_path: str, target_ext: str) -> bool:
    """True when the file already is the target format (.aif counts as .aiff)."""
    from pathlib import Path

    ext = Path(file_path).suffix.lower()
    return (".aiff" if ext == ".aif" else ext) == target_ext


def _resolved_target(
    source_rate: int,
    source_bits: int,
    target_ext: str,
    sample_rate: int | None,
    bit_depth: int | None,
) -> tuple[int, int]:
    """The (rate, bit depth) a conversion would actually write. A None setting
    means "keep the source's" — that is what the CLI passes when the flag is
    omitted, and it must not read as a change in either direction."""
    return (
        source_rate if sample_rate is None else sample_rate,
        source_bits if bit_depth is None else effective_bit_depth(bit_depth, target_ext),
    )


def raises_quality(
    source_rate: int | None,
    source_bits: int | None,
    target_ext: str,
    sample_rate: int | None = None,
    bit_depth: int | None = None,
) -> bool:
    """True when the requested settings would push the sample rate or bit depth
    above the source's.

    Quality is never invented: the app refuses to upsample for the same reason
    it refuses a lossy source, and this is that rule for a conversion between
    two formats. Equal settings are not a raise, so the everyday container
    change (44.1 kHz/16-bit WAV -> FLAC at 44.1 kHz/16-bit) is untouched.
    Unknown source values answer False, leaving an unmeasurable file to fail —
    or succeed — on its own merits rather than on a guess.
    """
    if source_rate is None or source_bits is None:
        return False
    rate, bits = _resolved_target(source_rate, source_bits, target_ext, sample_rate, bit_depth)
    return rate > source_rate or bits > source_bits


def is_quality_downgrade(
    source_rate: int | None,
    source_bits: int | None,
    target_ext: str,
    sample_rate: int | None = None,
    bit_depth: int | None = None,
) -> bool:
    """True when the requested settings lower the sample rate or bit depth and
    raise neither.

    This is what makes converting a file into its own format worth doing — a
    96 kHz/24-bit FLAC down to 44.1 kHz/16-bit FLAC plays on older CDJs, while
    the reverse only inflates the file. Equal settings are not a downgrade, so
    a same-format conversion with nothing to lower stays skipped. Unknown
    source values (unreadable file) answer False rather than guessing, so a
    file we can't measure is never rewritten on a hunch.
    """
    if source_rate is None or source_bits is None:
        return False
    rate, bits = _resolved_target(source_rate, source_bits, target_ext, sample_rate, bit_depth)
    if rate > source_rate or bits > source_bits:
        return False
    return rate < source_rate or bits < source_bits


def resolve_output_path(source_path: str, target_ext: str, output_dir: str | None = None):
    """Compute the destination path for a conversion, avoiding overwrites.

    The output lives in `output_dir` (or alongside the source), named
    `<stem><target_ext>`. If that name already exists on disk, a ` (N)` counter
    is appended until a free name is found, so an existing file is never
    clobbered. Pure path logic — no audio I/O — so the CLI dry-run preview and
    the real conversion in convert_file share one source of truth and can never
    disagree on the name (for names already present on disk).
    """
    from pathlib import Path

    src_path = Path(source_path)
    out_dir = Path(output_dir) if output_dir else src_path.parent
    output_path = out_dir / (src_path.stem + target_ext)

    if output_path.exists():
        counter = 1
        while output_path.exists():
            output_path = out_dir / f"{src_path.stem} ({counter}){target_ext}"
            counter += 1

    return output_path


@dataclass
class ConversionResult:
    """Result of a single file conversion."""

    source_path: str
    output_path: str
    target_format: str
    skipped: bool = False
    error: str | None = None
    incomplete: bool = False
