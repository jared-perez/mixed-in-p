"""Undo/redo support via JSON-based history logs.

Tracks rename operations and allows reverting changes by storing
original and new paths in session files.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def get_history_dir() -> Path:
    """Get the history directory, creating it if needed."""
    from src.utils.app_dirs import get_app_data_dir

    history_dir = get_app_data_dir() / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    # One-time migration from old path
    old_dir = Path.home() / ".musickey" / "history"
    if old_dir.exists() and any(old_dir.glob("session_*.json")):
        import shutil
        for f in old_dir.glob("session_*.json"):
            dest = history_dir / f.name
            if not dest.exists():
                shutil.copy2(f, dest)

    return history_dir


@dataclass
class RenameRecord:
    """Record of a single file rename."""

    original_path: str
    new_path: str
    timestamp: str
    operations: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "original_path": self.original_path,
            "new_path": self.new_path,
            "timestamp": self.timestamp,
            "operations": self.operations,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RenameRecord:
        """Create from dictionary."""
        return cls(
            original_path=data["original_path"],
            new_path=data["new_path"],
            timestamp=data.get("timestamp", ""),
            operations=data.get("operations", []),
        )


@dataclass
class RenameSession:
    """A group of renames performed together."""

    session_id: str
    records: list[RenameRecord]
    timestamp: str
    description: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "description": self.description,
            "records": [r.to_dict() for r in self.records],
        }

    @classmethod
    def from_dict(cls, data: dict) -> RenameSession:
        """Create from dictionary."""
        return cls(
            session_id=data["session_id"],
            timestamp=data.get("timestamp", ""),
            description=data.get("description", ""),
            records=[RenameRecord.from_dict(r) for r in data.get("records", [])],
        )

    @property
    def file_count(self) -> int:
        """Number of files in this session."""
        return len(self.records)


def generate_session_id() -> str:
    """Generate a unique session ID."""
    return uuid.uuid4().hex[:8]


def get_session_filename(session_id: str) -> str:
    """Get the filename for a session."""
    return f"session_{session_id}.json"


def save_session(
    session: RenameSession,
    history_dir: Path | None = None,
) -> Path:
    """Save rename session to JSON file for undo.

    Args:
        session: The session to save
        history_dir: Optional custom history directory

    Returns:
        Path to the saved session file
    """
    if history_dir is None:
        history_dir = get_history_dir()

    file_path = history_dir / get_session_filename(session.session_id)

    with open(file_path, "w") as f:
        json.dump(session.to_dict(), f, indent=2)

    return file_path


def load_session(
    session_id: str,
    history_dir: Path | None = None,
) -> RenameSession:
    """Load a previous rename session.

    Args:
        session_id: The session ID to load
        history_dir: Optional custom history directory

    Returns:
        The loaded session

    Raises:
        FileNotFoundError: If session file doesn't exist
    """
    if history_dir is None:
        history_dir = get_history_dir()

    file_path = history_dir / get_session_filename(session_id)

    with open(file_path, "r") as f:
        data = json.load(f)

    return RenameSession.from_dict(data)


def list_sessions(
    history_dir: Path | None = None,
    limit: int = 10,
) -> list[RenameSession]:
    """List recent rename sessions.

    Args:
        history_dir: Optional custom history directory
        limit: Maximum number of sessions to return

    Returns:
        List of sessions, most recent first
    """
    if history_dir is None:
        history_dir = get_history_dir()

    if not history_dir.exists():
        return []

    sessions = []
    session_files = sorted(
        history_dir.glob("session_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for file_path in session_files[:limit]:
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
            sessions.append(RenameSession.from_dict(data))
        except (json.JSONDecodeError, KeyError):
            # Skip corrupted files
            continue

    return sessions


def delete_session(
    session_id: str,
    history_dir: Path | None = None,
) -> bool:
    """Delete a session file.

    Args:
        session_id: The session ID to delete
        history_dir: Optional custom history directory

    Returns:
        True if deleted, False if not found
    """
    if history_dir is None:
        history_dir = get_history_dir()

    file_path = history_dir / get_session_filename(session_id)

    if file_path.exists():
        file_path.unlink()
        return True
    return False


def undo_session(
    session: RenameSession,
) -> list[tuple[str, str, bool, str | None]]:
    """Undo a rename session by reversing all renames.

    Args:
        session: The session to undo

    Returns:
        List of tuples: (old_path, new_path, success, error_message)
        where old_path is the current name and new_path is the restored name
    """
    results: list[tuple[str, str, bool, str | None]] = []

    # Process in reverse order to handle any dependencies
    for record in reversed(session.records):
        current_path = Path(record.new_path)
        original_path = Path(record.original_path)

        try:
            if not current_path.exists():
                results.append((
                    record.new_path,
                    record.original_path,
                    False,
                    f"File not found: {record.new_path}",
                ))
                continue

            if original_path.exists() and current_path != original_path:
                results.append((
                    record.new_path,
                    record.original_path,
                    False,
                    f"Target already exists: {record.original_path}",
                ))
                continue

            # Perform the rename
            current_path.rename(original_path)
            results.append((record.new_path, record.original_path, True, None))

        except OSError as e:
            results.append((
                record.new_path,
                record.original_path,
                False,
                str(e),
            ))

    return results


def create_session(
    renames: list[tuple[str, str]],
    operations: list[dict] | None = None,
    description: str = "",
) -> RenameSession:
    """Create a new rename session from a list of renames.

    Args:
        renames: List of (original_path, new_path) tuples
        operations: Optional list of operation dicts to store
        description: Optional description of the session

    Returns:
        New RenameSession ready to save
    """
    timestamp = datetime.now().isoformat()
    records = []

    for original_path, new_path in renames:
        records.append(RenameRecord(
            original_path=original_path,
            new_path=new_path,
            timestamp=timestamp,
            operations=operations or [],
        ))

    return RenameSession(
        session_id=generate_session_id(),
        records=records,
        timestamp=timestamp,
        description=description,
    )


def format_session_list(sessions: list[RenameSession]) -> str:
    """Format a list of sessions for display.

    Args:
        sessions: List of sessions to format

    Returns:
        Formatted string representation
    """
    if not sessions:
        return "No rename sessions found."

    lines = ["Recent rename sessions:", ""]

    # Header
    lines.append(f"{'ID':<10}  {'Date/Time':<20}  {'Files':>6}  Description")
    lines.append("-" * 60)

    for session in sessions:
        # Parse and format timestamp
        try:
            dt = datetime.fromisoformat(session.timestamp)
            time_str = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            time_str = session.timestamp[:16]

        desc = session.description[:20] if session.description else ""
        lines.append(
            f"{session.session_id:<10}  {time_str:<20}  {session.file_count:>6}  {desc}"
        )

    lines.append("")
    lines.append("Use 'mixed-in-p rename --undo SESSION_ID' to undo a session.")

    return "\n".join(lines)
