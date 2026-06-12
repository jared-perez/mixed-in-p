"""Audio-slice export helpers, decoupled from any Qt widget.

Extracts a [start, end) range from a source file and writes it to a new file in
the chosen format, copying the source's metadata onto the slice. Lossless
sources are read by frame range via soundfile; lossy sources are decoded by
librosa with an offset/duration window; MP3 output is encoded with lameenc.

Also holds the ``m:ss:mmm`` time formatting/parsing the slice UI uses (the
player's own m:ss helper drops the milliseconds the slicer needs).
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.conversion.result import FORMAT_EXTENSION, LOSSLESS_EXTENSIONS
from src.metadata.tags import read_metadata, write_metadata

logger = logging.getLogger(__name__)


def format_time_ms(ms: int, show_hours: bool = False) -> str:
    """Format milliseconds as ``m:ss:mmm`` or ``h:mm:ss:mmm``."""
    ms = max(0, ms)
    millis = ms % 1000
    total_seconds = ms // 1000
    seconds = total_seconds % 60
    minutes = total_seconds // 60
    if show_hours:
        hours = minutes // 60
        minutes = minutes % 60
        return f"{hours}:{minutes:02d}:{seconds:02d}:{millis:03d}"
    return f"{minutes}:{seconds:02d}:{millis:03d}"


def parse_time_ms(text: str) -> int | None:
    """Parse ``m:ss``, ``m:ss:mmm``, or ``h:mm:ss:mmm`` back to milliseconds."""
    text = text.strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        if len(parts) == 2:
            m, s = int(parts[0]), int(parts[1])
            return m * 60_000 + s * 1000
        elif len(parts) == 3:
            m, s, ms = int(parts[0]), int(parts[1]), int(parts[2])
            return m * 60_000 + s * 1000 + ms
        elif len(parts) == 4:
            h, m, s, ms = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            return h * 3_600_000 + m * 60_000 + s * 1000 + ms
    except ValueError:
        pass
    return None


def unique_path(path: Path) -> Path:
    """Return *path* if it doesn't exist, otherwise append (1), (2), … suffix."""
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.parent / f"{path.stem} ({counter}){path.suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def write_mp3(data, samplerate: int, output_path: Path, from_float: bool = True) -> None:
    """Encode audio data to MP3 via lameenc."""
    import numpy as np
    import lameenc

    if from_float:
        data_int16 = (data * 32767).astype(np.int16)
    else:
        data_int16 = data

    if data_int16.ndim == 1:
        data_int16 = data_int16.reshape(-1, 1)
    channels = data_int16.shape[1]

    encoder = lameenc.Encoder()
    encoder.set_bit_rate(320)
    encoder.set_in_sample_rate(samplerate)
    encoder.set_channels(channels)
    encoder.set_quality(2)

    mp3_data = encoder.encode(data_int16.tobytes())
    mp3_data += encoder.flush()

    with open(output_path, "wb") as f:
        f.write(mp3_data)


def export_slice(
    src_path: str,
    start_ms: int,
    end_ms: int,
    target_format: str,
    out_dir: str | None = None,
    filename: str | None = None,
) -> Path:
    """Extract [start_ms, end_ms) from *src_path* and write it as *target_format*.

    Returns the written path. Raises ValueError on an invalid range, or the
    underlying decode/encode exception on failure. Metadata is copied from the
    source onto the slice (best-effort — a copy failure is logged, not raised).
    """
    if end_ms <= start_ms:
        raise ValueError("Invalid range: end must be after start.")

    target_ext = FORMAT_EXTENSION.get(target_format, ".aiff")
    name = (filename or "").strip() or f"{Path(src_path).stem}_slice"
    save_dir = Path(out_dir) if out_dir else Path(src_path).parent
    output_path = unique_path(save_dir / f"{name}{target_ext}")

    src_ext = Path(src_path).suffix.lower()
    is_src_lossless = src_ext in LOSSLESS_EXTENSIONS

    if is_src_lossless:
        import soundfile as sf

        info = sf.info(src_path)
        sr = info.samplerate
        subtype = info.subtype
        start_frame = int(start_ms / 1000.0 * sr)
        end_frame = int(end_ms / 1000.0 * sr)

        data, _ = sf.read(src_path, start=start_frame, stop=end_frame, always_2d=True)

        if target_format == "MP3":
            write_mp3(data, sr, output_path)
        else:
            sf.write(str(output_path), data, sr, subtype=subtype)
    else:
        import librosa
        import numpy as np

        start_sec = start_ms / 1000.0
        duration_sec = (end_ms - start_ms) / 1000.0
        data, sr = librosa.load(src_path, sr=None, offset=start_sec, duration=duration_sec, mono=False)

        # librosa returns (channels, samples) for stereo — transpose for soundfile
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        else:
            data = data.T

        if target_format == "MP3":
            data_int16 = (data * 32767).astype(np.int16)
            write_mp3(data_int16, sr, output_path, from_float=False)
        else:
            import soundfile as sf

            sf.write(str(output_path), data, sr)

    # Copy metadata (best-effort).
    try:
        meta = read_metadata(src_path)
        write_metadata(str(output_path), meta)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not copy metadata to slice: {e}")

    logger.info(f"Slice saved to {output_path}")
    return output_path
