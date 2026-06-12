"""Tests for the renamer module."""

import json
import tempfile
from pathlib import Path

import pytest

from src.renamer.operations import (
    TrimStart,
    TrimEnd,
    AddPrefix,
    AddSuffix,
    Replace,
    AddAnalysis,
    apply_operation,
    apply_operations,
    operations_to_dict,
    operations_from_dict,
)
from src.renamer.preview import (
    RenamePreview,
    preview_rename,
    detect_conflicts,
    format_preview_table,
    has_conflicts,
    has_changes,
)
from src.renamer.history import (
    RenameRecord,
    RenameSession,
    create_session,
    save_session,
    load_session,
    list_sessions,
    delete_session,
    undo_session,
    get_history_dir,
)
from src.analysis.analyzer import AnalysisResult


class TestTrimStart:
    """Tests for TrimStart operation."""

    def test_trim_start_basic(self):
        result = apply_operation("01 - Track Name.mp3", TrimStart(count=5))
        assert result == "Track Name.mp3"

    def test_trim_start_preserves_extension(self):
        result = apply_operation("ABC Song.flac", TrimStart(count=4))
        assert result == "Song.flac"

    def test_trim_start_zero(self):
        result = apply_operation("Track.mp3", TrimStart(count=0))
        assert result == "Track.mp3"

    def test_trim_start_entire_name(self):
        result = apply_operation("ABC.mp3", TrimStart(count=3))
        assert result == ".mp3"


class TestTrimEnd:
    """Tests for TrimEnd operation."""

    def test_trim_end_basic(self):
        result = apply_operation("Track Name (Edit).mp3", TrimEnd(count=7))
        assert result == "Track Name.mp3"

    def test_trim_end_preserves_extension(self):
        result = apply_operation("Song ABC.flac", TrimEnd(count=4))
        assert result == "Song.flac"

    def test_trim_end_zero(self):
        result = apply_operation("Track.mp3", TrimEnd(count=0))
        assert result == "Track.mp3"

    def test_trim_end_entire_name(self):
        result = apply_operation("ABC.mp3", TrimEnd(count=10))
        assert result == ".mp3"


class TestAddPrefix:
    """Tests for AddPrefix operation."""

    def test_add_prefix_basic(self):
        result = apply_operation("Track.mp3", AddPrefix(prefix="Artist - "))
        assert result == "Artist - Track.mp3"

    def test_add_prefix_empty(self):
        result = apply_operation("Track.mp3", AddPrefix(prefix=""))
        assert result == "Track.mp3"

    def test_add_prefix_with_path(self):
        result = apply_operation("/music/Track.mp3", AddPrefix(prefix="01 "))
        assert result == "/music/01 Track.mp3"


class TestAddSuffix:
    """Tests for AddSuffix operation."""

    def test_add_suffix_basic(self):
        result = apply_operation("Track.mp3", AddSuffix(suffix=" (Remix)"))
        assert result == "Track (Remix).mp3"

    def test_add_suffix_empty(self):
        result = apply_operation("Track.mp3", AddSuffix(suffix=""))
        assert result == "Track.mp3"

    def test_add_suffix_with_path(self):
        result = apply_operation("/music/Track.mp3", AddSuffix(suffix=" v2"))
        assert result == "/music/Track v2.mp3"


class TestReplace:
    """Tests for Replace operation."""

    def test_replace_basic(self):
        result = apply_operation("Track_Name.mp3", Replace(find="_", replace=" "))
        assert result == "Track Name.mp3"

    def test_replace_multiple(self):
        result = apply_operation("A_B_C.mp3", Replace(find="_", replace="-"))
        assert result == "A-B-C.mp3"

    def test_replace_not_found(self):
        result = apply_operation("Track.mp3", Replace(find="X", replace="Y"))
        assert result == "Track.mp3"

    def test_replace_empty(self):
        result = apply_operation("Track (Edit).mp3", Replace(find=" (Edit)", replace=""))
        assert result == "Track.mp3"


class TestAddAnalysis:
    """Tests for AddAnalysis operation."""

    @pytest.fixture
    def analysis(self):
        return AnalysisResult(
            file_path="/music/Track.mp3",
            bpm=128.5,
            bpm_confidence=0.9,
            key="Am",
            key_confidence=0.85,
            keycode="8A",
        )

    def test_add_key_only_keycode(self, analysis):
        op = AddAnalysis(include_bpm=False, include_key=True, key_format="keycode")
        result = apply_operation("Track.mp3", op, analysis)
        assert result == "Track [8A].mp3"

    def test_add_key_only_standard(self, analysis):
        op = AddAnalysis(include_bpm=False, include_key=True, key_format="standard")
        result = apply_operation("Track.mp3", op, analysis)
        assert result == "Track [Am].mp3"

    def test_add_bpm_only(self, analysis):
        op = AddAnalysis(include_bpm=True, include_key=False)
        result = apply_operation("Track.mp3", op, analysis)
        assert result == "Track [128].mp3"

    def test_add_both_key_first(self, analysis):
        op = AddAnalysis(include_bpm=True, include_key=True, order="key_first")
        result = apply_operation("Track.mp3", op, analysis)
        assert result == "Track [8A] [128].mp3"

    def test_add_both_bpm_first(self, analysis):
        op = AddAnalysis(include_bpm=True, include_key=True, order="bpm_first")
        result = apply_operation("Track.mp3", op, analysis)
        assert result == "Track [128] [8A].mp3"

    def test_add_at_start(self, analysis):
        op = AddAnalysis(include_bpm=True, include_key=True, position="start")
        result = apply_operation("Track.mp3", op, analysis)
        assert result == "[8A] [128] Track.mp3"

    def test_round_brackets(self, analysis):
        op = AddAnalysis(include_bpm=True, include_key=True, bracket_style="round")
        result = apply_operation("Track.mp3", op, analysis)
        assert result == "Track (8A) (128).mp3"

    def test_no_brackets(self, analysis):
        op = AddAnalysis(include_bpm=True, include_key=True, bracket_style="none")
        result = apply_operation("Track.mp3", op, analysis)
        assert result == "Track 8A 128.mp3"

    def test_requires_analysis(self):
        op = AddAnalysis(include_bpm=True)
        with pytest.raises(ValueError, match="requires an AnalysisResult"):
            apply_operation("Track.mp3", op, None)


class TestApplyOperations:
    """Tests for applying multiple operations."""

    def test_chain_operations(self):
        ops = [
            TrimStart(count=5),  # "01 - Track.mp3" -> "Track.mp3"
            AddPrefix(prefix="Artist - "),  # -> "Artist - Track.mp3"
            AddSuffix(suffix=" (Remix)"),  # -> "Artist - Track (Remix).mp3"
        ]
        result = apply_operations("01 - Track.mp3", ops)
        assert result == "Artist - Track (Remix).mp3"

    def test_empty_operations(self):
        result = apply_operations("Track.mp3", [])
        assert result == "Track.mp3"


class TestOperationsSerialization:
    """Tests for operation serialization."""

    def test_roundtrip_all_operations(self):
        ops = [
            TrimStart(count=3),
            TrimEnd(count=5),
            AddPrefix(prefix="Pre-"),
            AddSuffix(suffix="-Suf"),
            Replace(find="A", replace="B"),
            AddAnalysis(
                include_bpm=True,
                include_key=True,
                key_format="standard",
                order="bpm_first",
                position="start",
                bracket_style="round",
            ),
        ]

        serialized = operations_to_dict(ops)
        deserialized = operations_from_dict(serialized)

        assert len(deserialized) == len(ops)
        assert isinstance(deserialized[0], TrimStart)
        assert deserialized[0].count == 3
        assert isinstance(deserialized[5], AddAnalysis)
        assert deserialized[5].key_format == "standard"


class TestPreview:
    """Tests for preview functionality."""

    def test_preview_basic(self):
        file_paths = ["/music/Track1.mp3", "/music/Track2.mp3"]
        ops = [AddPrefix(prefix="01 ")]

        previews = preview_rename(file_paths, ops)

        assert len(previews) == 2
        assert previews[0].original_name == "Track1.mp3"
        assert previews[0].new_name == "01 Track1.mp3"
        assert not previews[0].will_conflict

    def test_preview_with_analysis(self):
        file_paths = ["/music/Track.mp3"]
        analysis_results = {
            "/music/Track.mp3": AnalysisResult(
                file_path="/music/Track.mp3",
                bpm=128.0,
                bpm_confidence=0.9,
                key="Am",
                key_confidence=0.85,
                keycode="8A",
            )
        }
        ops = [AddAnalysis(include_key=True, include_bpm=False)]

        previews = preview_rename(file_paths, ops, analysis_results)

        assert previews[0].new_name == "Track [8A].mp3"


class TestConflictDetection:
    """Tests for conflict detection."""

    def test_detect_duplicate_targets(self):
        previews = [
            RenamePreview(
                original_path="/music/A.mp3",
                original_name="A.mp3",
                new_name="Same.mp3",
                new_path="/music/Same.mp3",
            ),
            RenamePreview(
                original_path="/music/B.mp3",
                original_name="B.mp3",
                new_name="Same.mp3",
                new_path="/music/Same.mp3",
            ),
        ]

        result = detect_conflicts(previews)

        assert result[0].will_conflict
        assert result[1].will_conflict

    def test_no_conflict_different_targets(self):
        previews = [
            RenamePreview(
                original_path="/music/A.mp3",
                original_name="A.mp3",
                new_name="New_A.mp3",
                new_path="/music/New_A.mp3",
            ),
            RenamePreview(
                original_path="/music/B.mp3",
                original_name="B.mp3",
                new_name="New_B.mp3",
                new_path="/music/New_B.mp3",
            ),
        ]

        result = detect_conflicts(previews)

        assert not result[0].will_conflict
        assert not result[1].will_conflict

    def test_has_conflicts(self):
        previews = [
            RenamePreview(
                original_path="A.mp3",
                original_name="A.mp3",
                new_name="B.mp3",
                new_path="B.mp3",
                will_conflict=True,
            ),
        ]
        assert has_conflicts(previews)

    def test_has_changes(self):
        previews = [
            RenamePreview(
                original_path="A.mp3",
                original_name="A.mp3",
                new_name="B.mp3",
                new_path="B.mp3",
            ),
        ]
        assert has_changes(previews)

    def test_no_changes(self):
        previews = [
            RenamePreview(
                original_path="A.mp3",
                original_name="A.mp3",
                new_name="A.mp3",
                new_path="A.mp3",
            ),
        ]
        assert not has_changes(previews)


class TestFormatPreviewTable:
    """Tests for preview table formatting."""

    def test_format_basic(self):
        previews = [
            RenamePreview(
                original_path="/music/Track.mp3",
                original_name="Track.mp3",
                new_name="New Track.mp3",
                new_path="/music/New Track.mp3",
            ),
        ]

        output = format_preview_table(previews)

        assert "Track.mp3" in output
        assert "New Track.mp3" in output
        assert "OK" in output

    def test_format_conflict(self):
        previews = [
            RenamePreview(
                original_path="/music/Track.mp3",
                original_name="Track.mp3",
                new_name="Conflict.mp3",
                new_path="/music/Conflict.mp3",
                will_conflict=True,
            ),
        ]

        output = format_preview_table(previews)

        assert "CONFLICT" in output


class TestHistory:
    """Tests for history/undo functionality."""

    def test_create_session(self):
        renames = [
            ("/music/old1.mp3", "/music/new1.mp3"),
            ("/music/old2.mp3", "/music/new2.mp3"),
        ]

        session = create_session(renames, description="Test session")

        assert len(session.records) == 2
        assert session.description == "Test session"
        assert session.file_count == 2

    def test_save_and_load_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = Path(tmpdir)
            renames = [("/music/old.mp3", "/music/new.mp3")]
            session = create_session(renames, description="Test")

            save_session(session, history_dir)
            loaded = load_session(session.session_id, history_dir)

            assert loaded.session_id == session.session_id
            assert len(loaded.records) == 1
            assert loaded.records[0].original_path == "/music/old.mp3"

    def test_list_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = Path(tmpdir)

            # Create multiple sessions
            for i in range(3):
                session = create_session(
                    [(f"/music/old{i}.mp3", f"/music/new{i}.mp3")],
                    description=f"Session {i}",
                )
                save_session(session, history_dir)

            sessions = list_sessions(history_dir, limit=10)

            assert len(sessions) == 3

    def test_delete_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_dir = Path(tmpdir)
            session = create_session([("/old.mp3", "/new.mp3")])
            save_session(session, history_dir)

            assert delete_session(session.session_id, history_dir)
            assert not delete_session(session.session_id, history_dir)  # Already deleted

    def test_undo_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            old_path = Path(tmpdir) / "old.mp3"
            new_path = Path(tmpdir) / "new.mp3"
            old_path.write_text("test content")
            old_path.rename(new_path)

            # Create session record
            session = create_session([(str(old_path), str(new_path))])

            # Undo
            results = undo_session(session)

            assert len(results) == 1
            assert results[0][2]  # success
            assert old_path.exists()
            assert not new_path.exists()

    def test_undo_missing_file(self):
        session = create_session([("/nonexistent/old.mp3", "/nonexistent/new.mp3")])

        results = undo_session(session)

        assert len(results) == 1
        assert not results[0][2]  # not success
        assert "not found" in results[0][3].lower()


class TestRenameRecord:
    """Tests for RenameRecord dataclass."""

    def test_to_dict(self):
        record = RenameRecord(
            original_path="/old.mp3",
            new_path="/new.mp3",
            timestamp="2024-01-01T00:00:00",
            operations=[{"type": "add_prefix", "prefix": "01 "}],
        )

        d = record.to_dict()

        assert d["original_path"] == "/old.mp3"
        assert d["new_path"] == "/new.mp3"
        assert len(d["operations"]) == 1

    def test_from_dict(self):
        d = {
            "original_path": "/old.mp3",
            "new_path": "/new.mp3",
            "timestamp": "2024-01-01T00:00:00",
            "operations": [],
        }

        record = RenameRecord.from_dict(d)

        assert record.original_path == "/old.mp3"
        assert record.new_path == "/new.mp3"


class TestRenameSession:
    """Tests for RenameSession dataclass."""

    def test_to_dict(self):
        session = RenameSession(
            session_id="abc123",
            timestamp="2024-01-01T00:00:00",
            description="Test",
            records=[
                RenameRecord(
                    original_path="/old.mp3",
                    new_path="/new.mp3",
                    timestamp="2024-01-01T00:00:00",
                )
            ],
        )

        d = session.to_dict()

        assert d["session_id"] == "abc123"
        assert len(d["records"]) == 1

    def test_from_dict(self):
        d = {
            "session_id": "abc123",
            "timestamp": "2024-01-01T00:00:00",
            "description": "Test",
            "records": [
                {
                    "original_path": "/old.mp3",
                    "new_path": "/new.mp3",
                    "timestamp": "2024-01-01T00:00:00",
                }
            ],
        }

        session = RenameSession.from_dict(d)

        assert session.session_id == "abc123"
        assert session.file_count == 1
