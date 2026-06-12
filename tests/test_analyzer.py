"""Integration tests for the audio analyzer module.

These tests verify the analyzer API works correctly. Tests that require
actual audio files are marked with pytest.mark.skip when files aren't
available.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.analysis.analyzer import (
    AnalysisResult,
    analyze_file,
    analyze_files,
    find_audio_files,
    SUPPORTED_EXTENSIONS,
)


class TestAnalysisResult:
    """Tests for the AnalysisResult dataclass."""

    def test_filename_property(self):
        """Test extracting filename from full path."""
        result = AnalysisResult(
            file_path="/path/to/track.mp3",
            bpm=128.0,
            bpm_confidence=0.9,
            key="Am",
            key_confidence=0.85,
            keycode="8A",
        )
        assert result.filename == "track.mp3"

    def test_to_dict(self):
        """Test dictionary conversion."""
        result = AnalysisResult(
            file_path="/path/to/track.mp3",
            bpm=128.0,
            bpm_confidence=0.9,
            key="Am",
            key_confidence=0.85,
            keycode="8A",
        )
        d = result.to_dict()
        assert d["file_path"] == "/path/to/track.mp3"
        assert d["filename"] == "track.mp3"
        assert d["bpm"] == 128.0
        assert d["key"] == "Am"
        assert d["keycode"] == "8A"
        assert d["error"] is None

    def test_to_dict_with_error(self):
        """Test dictionary conversion with error."""
        result = AnalysisResult(
            file_path="/path/to/bad.mp3",
            bpm=0.0,
            bpm_confidence=0.0,
            key="",
            key_confidence=0.0,
            keycode="",
            error="File not found",
        )
        d = result.to_dict()
        assert d["error"] == "File not found"


class TestAnalyzeFile:
    """Tests for the analyze_file function."""

    def test_returns_result_on_error(self):
        """Test that errors are caught and returned in result."""
        result = analyze_file("/nonexistent/file.mp3")
        assert result.error is not None
        assert result.bpm == 0.0
        assert result.key == ""


class TestAnalyzeFiles:
    """Tests for batch analysis."""

    def test_empty_list(self):
        """Test handling of empty file list."""
        results = analyze_files([])
        assert results == []

    @patch("src.analysis.analyzer.analyze_file")
    def test_single_file_no_multiprocessing(self, mock_analyze):
        """Test that single file skips multiprocessing."""
        mock_result = AnalysisResult(
            file_path="/test.mp3",
            bpm=128.0,
            bpm_confidence=0.9,
            key="Am",
            key_confidence=0.85,
            keycode="8A",
        )
        mock_analyze.return_value = mock_result

        results = analyze_files(["/test.mp3"])

        assert len(results) == 1
        assert results[0].bpm == 128.0
        mock_analyze.assert_called_once()

    def test_progress_callback(self):
        """Test that progress callback is called."""
        callback_calls = []

        def callback(completed, total):
            callback_calls.append((completed, total))

        # Use mock to avoid actual file processing
        with patch("src.analysis.analyzer.analyze_file") as mock:
            mock.return_value = AnalysisResult(
                file_path="/test.mp3",
                bpm=128.0,
                bpm_confidence=0.9,
                key="Am",
                key_confidence=0.85,
                keycode="8A",
            )
            analyze_files(["/test.mp3"], progress_callback=callback)

        assert len(callback_calls) == 1
        assert callback_calls[0] == (1, 1)


class TestFindAudioFiles:
    """Tests for the find_audio_files function."""

    def test_not_a_directory(self, tmp_path):
        """Test error when path is not a directory."""
        fake_file = tmp_path / "file.txt"
        fake_file.write_text("test")

        with pytest.raises(NotADirectoryError):
            find_audio_files(str(fake_file))

    def test_finds_supported_formats(self, tmp_path):
        """Test finding files with supported extensions."""
        # Create test files
        (tmp_path / "track1.mp3").write_text("")
        (tmp_path / "track2.wav").write_text("")
        (tmp_path / "track3.flac").write_text("")
        (tmp_path / "track4.aiff").write_text("")
        (tmp_path / "notes.txt").write_text("")  # Should be ignored

        files = find_audio_files(str(tmp_path))

        assert len(files) == 4
        filenames = [Path(f).name for f in files]
        assert "track1.mp3" in filenames
        assert "track2.wav" in filenames
        assert "track3.flac" in filenames
        assert "track4.aiff" in filenames
        assert "notes.txt" not in filenames

    def test_recursive_search(self, tmp_path):
        """Test recursive directory search."""
        # Create nested structure
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (tmp_path / "top.mp3").write_text("")
        (subdir / "nested.mp3").write_text("")

        # Recursive (default)
        files = find_audio_files(str(tmp_path), recursive=True)
        assert len(files) == 2

        # Non-recursive
        files = find_audio_files(str(tmp_path), recursive=False)
        assert len(files) == 1
        assert "top.mp3" in files[0]

    def test_case_insensitive_extensions(self, tmp_path):
        """Test that uppercase extensions are found."""
        (tmp_path / "track.MP3").write_text("")
        (tmp_path / "track.WAV").write_text("")

        files = find_audio_files(str(tmp_path))
        assert len(files) == 2

    def test_returns_sorted_paths(self, tmp_path):
        """Test that results are sorted."""
        (tmp_path / "z_track.mp3").write_text("")
        (tmp_path / "a_track.mp3").write_text("")
        (tmp_path / "m_track.mp3").write_text("")

        files = find_audio_files(str(tmp_path))

        filenames = [Path(f).name for f in files]
        assert filenames == sorted(filenames)


class TestSupportedExtensions:
    """Tests for the SUPPORTED_EXTENSIONS constant."""

    def test_common_formats_supported(self):
        """Test that common DJ formats are supported."""
        assert ".mp3" in SUPPORTED_EXTENSIONS
        assert ".wav" in SUPPORTED_EXTENSIONS
        assert ".flac" in SUPPORTED_EXTENSIONS
        assert ".aiff" in SUPPORTED_EXTENSIONS
        assert ".aif" in SUPPORTED_EXTENSIONS

    def test_extensions_are_lowercase(self):
        """Test that all extensions are lowercase."""
        for ext in SUPPORTED_EXTENSIONS:
            assert ext == ext.lower()
            assert ext.startswith(".")
