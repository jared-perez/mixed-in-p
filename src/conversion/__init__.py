"""Audio conversion module (lossless formats only)."""

# Lightweight imports (no soundfile) - safe to load eagerly
from .result import (
    LOSSLESS_EXTENSIONS,
    LOSSY_EXTENSIONS,
    ConversionResult,
    is_lossless,
)

__all__ = [
    "LOSSLESS_EXTENSIONS",
    "LOSSY_EXTENSIONS",
    "ConversionResult",
    "convert_file",
    "is_lossless",
]


def __getattr__(name: str):
    """Lazy import convert_file (pulls in soundfile) on first access."""
    if name == "convert_file":
        from .converter import convert_file
        return convert_file

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
