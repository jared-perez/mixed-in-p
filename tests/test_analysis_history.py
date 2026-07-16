"""Tests for the persistent analysis history."""

import json

from src.analysis.history import MAX_ENTRIES, add_entry, load_entries, update_paths


def _entry(path: str, key: str = "Am") -> dict:
    return {"file_path": path, "key": key, "keycode": "8A", "bpm": 128.0}


class TestAddAndLoad:
    def test_round_trip_newest_first(self, tmp_path):
        hist = tmp_path / "history.json"
        add_entry(_entry("/a.wav"), hist)
        add_entry(_entry("/b.wav"), hist)
        entries = load_entries(hist)
        assert [e["file_path"] for e in entries] == ["/b.wav", "/a.wav"]

    def test_reanalysis_replaces_existing_entry(self, tmp_path):
        hist = tmp_path / "history.json"
        add_entry(_entry("/a.wav", key="Am"), hist)
        add_entry(_entry("/b.wav"), hist)
        add_entry(_entry("/a.wav", key="C"), hist)
        entries = load_entries(hist)
        assert [e["file_path"] for e in entries] == ["/a.wav", "/b.wav"]
        assert entries[0]["key"] == "C"

    def test_trims_to_max_entries(self, tmp_path):
        hist = tmp_path / "history.json"
        for i in range(MAX_ENTRIES + 10):
            add_entry(_entry(f"/{i}.wav"), hist)
        entries = load_entries(hist)
        assert len(entries) == MAX_ENTRIES
        assert entries[0]["file_path"] == f"/{MAX_ENTRIES + 9}.wav"

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_entries(tmp_path / "nope.json") == []

    def test_corrupt_file_returns_empty(self, tmp_path):
        hist = tmp_path / "history.json"
        hist.write_text("{not json")
        assert load_entries(hist) == []

    def test_wrong_shape_returns_empty(self, tmp_path):
        hist = tmp_path / "history.json"
        hist.write_text(json.dumps({"a": 1}))
        assert load_entries(hist) == []


class TestUpdatePaths:
    def test_renamed_entry_repointed(self, tmp_path):
        hist = tmp_path / "history.json"
        add_entry(_entry("/old.wav"), hist)
        add_entry(_entry("/other.wav"), hist)
        update_paths([("/old.wav", "/new.wav")], hist)
        paths = [e["file_path"] for e in load_entries(hist)]
        assert "/new.wav" in paths
        assert "/old.wav" not in paths
        assert "/other.wav" in paths

    def test_empty_renames_noop(self, tmp_path):
        hist = tmp_path / "history.json"
        add_entry(_entry("/a.wav"), hist)
        update_paths([], hist)
        assert len(load_entries(hist)) == 1
