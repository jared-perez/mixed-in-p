"""Lightweight conversion result types and constants.

This module has NO heavy dependencies (no soundfile).
Import freely without triggering slow library loads.
"""

from __future__ import annotations

from dataclasses import dataclass

LOSSLESS_EXTENSIONS = {".wav", ".flac", ".aiff", ".aif"}
LOSSY_EXTENSIONS = {".mp3", ".m4a", ".ogg"}
FORMAT_EXTENSION = {"WAV": ".wav", "FLAC": ".flac", "AIFF": ".aiff", "MP3": ".mp3"}


def is_lossless(file_path: str) -> bool:
    """Check if a file is a lossless audio format."""
    from pathlib import Path
    return Path(file_path).suffix.lower() in LOSSLESS_EXTENSIONS


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
