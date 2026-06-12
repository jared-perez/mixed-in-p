"""Audio analysis modules for BPM and key detection.

This package provides:
- key code mapping (keycode.py) - pure Python, no dependencies
- BPM detection (bpm_detector.py) - requires librosa
- Key detection (key_detector.py) - requires librosa
- High-level analyzer API (analyzer.py) - combines all detection

Import directly from submodules to avoid loading unnecessary dependencies:
    from src.analysis.keycode import key_to_keycode
    from src.analysis.analyzer import analyze_file
"""

# Lightweight imports (no heavy deps) - safe to load eagerly
from .result import AnalysisResult, SUPPORTED_EXTENSIONS, find_audio_files

__all__ = [
    "key_to_keycode",
    "keycode_to_key",
    "get_compatible_keys",
    "detect_bpm",
    "detect_key",
    "analyze_file",
    "analyze_files",
    "find_audio_files",
    "AnalysisResult",
    "SUPPORTED_EXTENSIONS",
]


def __getattr__(name: str):
    """Lazy import attributes on first access (heavy deps only)."""
    if name in ("key_to_keycode", "keycode_to_key", "get_compatible_keys"):
        from .keycode import key_to_keycode, keycode_to_key, get_compatible_keys
        return locals()[name]

    if name == "detect_bpm":
        from .bpm_detector import detect_bpm
        return detect_bpm

    if name == "detect_key":
        from .key_detector import detect_key
        return detect_key

    if name in ("analyze_file", "analyze_files"):
        from .analyzer import analyze_file, analyze_files
        return locals()[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
