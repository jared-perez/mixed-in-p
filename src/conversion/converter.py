"""Core audio conversion logic.

Converts between WAV, FLAC, and AIFF using soundfile.
Supports encoding to MP3 via lameenc.
Blocks lossy-to-lossless conversions entirely.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.metadata.tags import read_metadata, write_metadata

from .result import (
    LOSSLESS_EXTENSIONS,
    LOSSY_EXTENSIONS,
    FORMAT_EXTENSION,
    ConversionResult,
    is_lossless,
    resolve_output_path,
)

logger = logging.getLogger(__name__)


def _convert_to_mp3(
    source_path: str,
    output_path: Path,
    bitrate: int = 320,
) -> None:
    """Encode a lossless source to MP3 using lameenc.

    Args:
        source_path: Path to the lossless source file.
        output_path: Destination .mp3 path.
        bitrate: MP3 bitrate in kbps (e.g. 128, 192, 256, 320).
    """
    import lameenc
    import soundfile as sf

    data, samplerate = sf.read(source_path, dtype="int16", always_2d=True)
    channels = data.shape[1]

    encoder = lameenc.Encoder()
    encoder.set_bit_rate(bitrate)
    encoder.set_in_sample_rate(samplerate)
    encoder.set_channels(channels)
    encoder.set_quality(2)  # 2 = high quality

    mp3_data = encoder.encode(data.tobytes())
    mp3_data += encoder.flush()

    with open(output_path, "wb") as f:
        f.write(mp3_data)


_BIT_DEPTH_SUBTYPE = {
    8: "PCM_S8",
    16: "PCM_16",
    24: "PCM_24",
    32: "PCM_32",
}

# Bytes-per-sample by soundfile subtype, for truncation diagnosis.
_SUBTYPE_BYTES = {
    "PCM_S8": 1,
    "PCM_U8": 1,
    "PCM_16": 2,
    "PCM_24": 3,
    "PCM_32": 4,
    "FLOAT": 4,
    "DOUBLE": 8,
}


def _diagnose_truncation(source_path: str) -> str | None:
    """If a file looks truncated (actual size far smaller than its header claims),
    return a user-facing message. Otherwise return None.

    FLAC compresses to roughly 40-70% of raw PCM. A file under ~15% of the
    uncompressed size is almost certainly an incomplete download / truncated copy.
    """
    try:
        import soundfile as sf
        info = sf.info(source_path)
        bytes_per_sample = _SUBTYPE_BYTES.get(info.subtype)
        if not bytes_per_sample:
            return None
        expected_uncompressed = info.frames * info.channels * bytes_per_sample
        if expected_uncompressed <= 0:
            return None
        actual_size = Path(source_path).stat().st_size
        if actual_size < expected_uncompressed * 0.15:
            percent = (actual_size / expected_uncompressed) * 100
            return (
                f"File appears to be incomplete — only {percent:.1f}% of the "
                "expected audio data is present. Try re-downloading."
            )
    except Exception:
        pass
    return None


def _resolve_subtype(bit_depth: int | None, target_ext: str, source_subtype: str) -> str:
    """Map (bit_depth, target format) -> a soundfile subtype, with FLAC fallbacks."""
    if bit_depth is None:
        return source_subtype
    subtype = _BIT_DEPTH_SUBTYPE.get(bit_depth, source_subtype)
    if target_ext == ".flac":
        if bit_depth == 32:
            logger.warning("FLAC does not support 32-bit PCM; falling back to 24-bit")
            subtype = "PCM_24"
        elif bit_depth == 8:
            logger.warning("FLAC does not support 8-bit PCM; falling back to 16-bit")
            subtype = "PCM_16"
    return subtype


def convert_file(
    source_path: str,
    target_format: str,
    output_dir: str | None = None,
    bitrate: int = 320,
    sample_rate: int | None = None,
    bit_depth: int | None = None,
) -> ConversionResult:
    """Convert an audio file to a target format.

    Args:
        source_path: Path to the source audio file.
        target_format: Target format key ("WAV", "FLAC", "AIFF", or "MP3").
        output_dir: Optional output directory. Defaults to same directory as source.
        bitrate: MP3 bitrate in kbps (only used when target_format is "MP3").

    Returns:
        ConversionResult with outcome details. Errors are captured, never raised.
    """
    src_path = Path(source_path)
    target_ext = FORMAT_EXTENSION.get(target_format)

    if target_ext is None:
        return ConversionResult(
            source_path=source_path,
            output_path="",
            target_format=target_format,
            error=f"Unknown target format: {target_format}",
        )

    # Block lossy sources
    src_ext = src_path.suffix.lower()
    if src_ext in LOSSY_EXTENSIONS:
        return ConversionResult(
            source_path=source_path,
            output_path="",
            target_format=target_format,
            error="Lossy-to-lossless conversion is not supported",
        )

    if src_ext not in LOSSLESS_EXTENSIONS:
        return ConversionResult(
            source_path=source_path,
            output_path="",
            target_format=target_format,
            error=f"Unsupported source format: {src_ext}",
        )

    # Skip same-format (including .aif -> .aiff)
    normalised_src = ".aiff" if src_ext == ".aif" else src_ext
    if normalised_src == target_ext:
        return ConversionResult(
            source_path=source_path,
            output_path="",
            target_format=target_format,
            skipped=True,
        )

    # Build output path. Dedupes against existing files; shared with the CLI
    # dry-run (resolve_output_path) so the preview shows the exact name written.
    output_path = resolve_output_path(source_path, target_ext, output_dir)

    try:
        # Read metadata before conversion
        logger.debug(f"Reading metadata from {src_path.name}")
        try:
            metadata = read_metadata(source_path)
        except Exception as e:
            logger.warning(f"Could not read metadata from {src_path.name}: {e}")
            metadata = None

        logger.info(f"Converting {src_path.name} -> {output_path.name}")

        if target_format == "MP3":
            _convert_to_mp3(source_path, output_path, bitrate=bitrate)
        else:
            # Lazy import soundfile only when actually converting
            import soundfile as sf

            # Read audio data
            info = sf.info(source_path)
            source_subtype = info.subtype
            logger.debug(f"  Source subtype: {source_subtype}, samplerate: {info.samplerate}")

            data, samplerate = sf.read(source_path, always_2d=True)

            # Optional resampling
            if sample_rate is not None and sample_rate != samplerate:
                import librosa
                logger.info(f"  Resampling {samplerate} Hz -> {sample_rate} Hz")
                # librosa expects shape (channels, samples)
                data = librosa.resample(
                    data.T.astype("float32"),
                    orig_sr=samplerate,
                    target_sr=sample_rate,
                ).T
                samplerate = sample_rate

            # Resolve target subtype (bit depth)
            subtype = _resolve_subtype(bit_depth, target_ext, source_subtype)

            # Write to target format
            sf.write(str(output_path), data, samplerate, subtype=subtype)

        logger.info(f"Audio written to {output_path.name}")

        # Write metadata to converted file
        if metadata is not None:
            try:
                write_metadata(str(output_path), metadata)
                logger.info(f"Metadata written to {output_path.name}")
            except Exception as e:
                logger.warning(f"Could not write metadata to {output_path.name}: {e}")

        return ConversionResult(
            source_path=source_path,
            output_path=str(output_path),
            target_format=target_format,
        )

    except Exception as e:
        err_str = str(e)
        incomplete = False
        # libsndfile / libFLAC report truncated streams as "lost sync" or
        # "premature end of file" — translate those into a friendlier message.
        lowered = err_str.lower()
        if "lost sync" in lowered or "premature end" in lowered or "end of file" in lowered:
            diagnosis = _diagnose_truncation(source_path)
            if diagnosis is not None:
                err_str = diagnosis
                incomplete = True
        logger.error(f"Conversion failed for {src_path.name}: {err_str}")
        return ConversionResult(
            source_path=source_path,
            output_path="",
            target_format=target_format,
            error=err_str,
            incomplete=incomplete,
        )
