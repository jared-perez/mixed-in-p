"""Lightweight analysis result types and utilities.

This module has NO heavy dependencies (no librosa, numpy, soundfile).
Import freely without triggering slow library loads.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AnalysisResult:
    """Result of analyzing an audio file."""

    file_path: str
    bpm: float
    bpm_confidence: float
    key: str
    key_confidence: float
    keycode: str
    energy: int | None = None
    energy_confidence: float | None = None
    error: str | None = None
    # Runner-up key candidates from the same analysis pass, best first:
    # [{"key": "Fm", "keycode": "4A", "confidence": 0.27}, ...]
    key_alternatives: list[dict] = field(default_factory=list)

    @property
    def filename(self) -> str:
        """Return just the filename without path."""
        return Path(self.file_path).name

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "file_path": self.file_path,
            "filename": self.filename,
            "bpm": self.bpm,
            "bpm_confidence": self.bpm_confidence,
            "key": self.key,
            "key_confidence": self.key_confidence,
            "keycode": self.keycode,
            "energy": self.energy,
            "energy_confidence": self.energy_confidence,
            "error": self.error,
            "key_alternatives": self.key_alternatives,
        }


# Supported audio file extensions
SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".flac", ".aiff", ".aif", ".m4a", ".ogg"}


def find_audio_files(directory: str, recursive: bool = True) -> list[str]:
    """Find all supported audio files in a directory.

    Args:
        directory: Path to search
        recursive: Whether to search subdirectories (default True)

    Returns:
        List of absolute paths to audio files
    """
    path = Path(directory)

    if not path.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    pattern = "**/*" if recursive else "*"
    files: set[Path] = set()

    for ext in SUPPORTED_EXTENSIONS:
        files.update(path.glob(f"{pattern}{ext}"))
        files.update(path.glob(f"{pattern}{ext.upper()}"))

    # Skip dot-files (e.g. macOS AppleDouble "._track.aiff" sidecars and other
    # hidden files): they share a real file's extension but are not user media.
    return sorted(str(f.absolute()) for f in files if not f.name.startswith("."))
