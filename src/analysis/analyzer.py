"""High-level audio analysis API combining BPM and key detection.

Provides a unified interface for analyzing audio files with support
for batch processing using multiprocessing.
"""

from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Callable

from .bpm_detector import detect_bpm
from .cancellation import AnalysisCancelled, ShouldCancel, check_cancelled
from .energy_detector import detect_energy
from .key_detector import detect_key_with_alternatives
from .keycode import key_to_keycode
from .result import AnalysisResult


def analyze_file(
    file_path: str,
    min_bpm: float = 85.0,
    max_bpm: float = 175.0,
    should_cancel: ShouldCancel | None = None,
) -> AnalysisResult:
    """Analyze a single audio file for BPM and key.

    Args:
        file_path: Path to the audio file
        min_bpm: Minimum expected BPM for range adjustment
        max_bpm: Maximum expected BPM for range adjustment
        should_cancel: Optional predicate polled at stage boundaries; when it
            returns True the analysis unwinds with AnalysisCancelled rather
            than running the remaining stages

    Returns:
        AnalysisResult with detected BPM, key, and key code

    Raises:
        AnalysisCancelled: If should_cancel returned True at a stage boundary
    """
    try:
        check_cancelled(should_cancel)

        # Detect BPM
        bpm, bpm_confidence = detect_bpm(file_path, min_bpm, max_bpm)

        # The key stage is by far the most expensive (~79% of a file, nearly
        # all of it one uninterruptible HPSS call), so the boundary in front of
        # it is the most valuable cancellation point in the pipeline.
        check_cancelled(should_cancel)

        # Detect key (primary + runner-up candidates in one pass)
        key, key_confidence, alternatives = detect_key_with_alternatives(
            file_path, should_cancel=should_cancel
        )

        # Convert to Key Code
        try:
            keycode = key_to_keycode(key)
        except ValueError:
            keycode = ""

        key_alternatives = []
        for alt_key, alt_confidence in alternatives:
            try:
                alt_keycode = key_to_keycode(alt_key)
            except ValueError:
                alt_keycode = ""
            key_alternatives.append(
                {"key": alt_key, "keycode": alt_keycode, "confidence": alt_confidence}
            )

        check_cancelled(should_cancel)

        # Detect energy level
        try:
            energy, energy_confidence = detect_energy(file_path)
        except Exception:
            energy, energy_confidence = None, None

        return AnalysisResult(
            file_path=file_path,
            bpm=bpm,
            bpm_confidence=bpm_confidence,
            key=key,
            key_confidence=key_confidence,
            keycode=keycode,
            energy=energy,
            energy_confidence=energy_confidence,
            key_alternatives=key_alternatives,
        )

    except AnalysisCancelled:
        # Not a failure — must not become an error result, or a cancelled run
        # is reported to the user as a broken file.
        raise

    except Exception as e:
        return AnalysisResult(
            file_path=file_path,
            bpm=0.0,
            bpm_confidence=0.0,
            key="",
            key_confidence=0.0,
            keycode="",
            error=str(e),
        )


def _analyze_file_wrapper(args: tuple) -> AnalysisResult:
    """Wrapper for multiprocessing compatibility."""
    file_path, min_bpm, max_bpm = args
    return analyze_file(file_path, min_bpm, max_bpm)


def analyze_files(
    file_paths: list[str],
    workers: int = 4,
    min_bpm: float = 85.0,
    max_bpm: float = 175.0,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[AnalysisResult]:
    """Batch analyze multiple audio files with multiprocessing.

    Args:
        file_paths: List of paths to audio files
        workers: Number of parallel workers (default 4)
        min_bpm: Minimum expected BPM for range adjustment
        max_bpm: Maximum expected BPM for range adjustment
        progress_callback: Optional callback(completed, total) for progress updates

    Returns:
        List of AnalysisResult objects in the same order as input
    """
    if not file_paths:
        return []

    # For single file, don't bother with multiprocessing
    if len(file_paths) == 1:
        result = analyze_file(file_paths[0], min_bpm, max_bpm)
        if progress_callback:
            progress_callback(1, 1)
        return [result]

    # Prepare arguments for each file
    args_list = [(fp, min_bpm, max_bpm) for fp in file_paths]

    # Use ProcessPoolExecutor for true parallelism (GIL bypass)
    results: dict[str, AnalysisResult] = {}
    completed = 0

    with ProcessPoolExecutor(max_workers=workers) as executor:
        # Submit all tasks
        future_to_path = {
            executor.submit(_analyze_file_wrapper, args): args[0]
            for args in args_list
        }

        # Collect results as they complete
        for future in as_completed(future_to_path):
            file_path = future_to_path[future]
            try:
                result = future.result()
                results[file_path] = result
            except Exception as e:
                results[file_path] = AnalysisResult(
                    file_path=file_path,
                    bpm=0.0,
                    bpm_confidence=0.0,
                    key="",
                    key_confidence=0.0,
                    keycode="",
                    error=str(e),
                )

            completed += 1
            if progress_callback:
                progress_callback(completed, len(file_paths))

    # Return results in original order
    return [results[fp] for fp in file_paths]


from .result import SUPPORTED_EXTENSIONS, find_audio_files
