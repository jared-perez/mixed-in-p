"""Preview rename operations before applying them.

Generates previews of file renames and detects potential conflicts
like duplicate filenames before any files are actually modified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .operations import RenameOperation, apply_operations

if TYPE_CHECKING:
    from ..analysis.analyzer import AnalysisResult


@dataclass
class RenamePreview:
    """Preview of a single file rename operation."""

    original_path: str
    original_name: str
    new_name: str
    new_path: str
    will_conflict: bool = False
    conflict_with: str | None = None


def preview_rename(
    file_paths: list[str],
    operations: list[RenameOperation],
    analysis_results: dict[str, AnalysisResult] | None = None,
) -> list[RenamePreview]:
    """Generate preview for all files without making changes.

    Args:
        file_paths: List of file paths to rename
        operations: List of operations to apply to each file
        analysis_results: Optional dict mapping file paths to analysis results

    Returns:
        List of RenamePreview objects showing what would happen
    """
    previews = []

    for file_path in file_paths:
        path = Path(file_path)
        original_name = path.name

        # Get analysis result if available
        analysis = None
        if analysis_results:
            analysis = analysis_results.get(file_path)

        # Apply operations to get new name
        new_name = apply_operations(original_name, operations, analysis)
        new_path = str(path.parent / new_name)

        previews.append(RenamePreview(
            original_path=file_path,
            original_name=original_name,
            new_name=new_name,
            new_path=new_path,
        ))

    # Detect conflicts
    return detect_conflicts(previews)


def detect_conflicts(previews: list[RenamePreview]) -> list[RenamePreview]:
    """Find renames that would create duplicate filenames.

    Checks for:
    1. Two files being renamed to the same name
    2. A rename that would overwrite an existing file not being renamed

    Args:
        previews: List of rename previews to check

    Returns:
        The same list with will_conflict and conflict_with fields updated
    """
    # Build set of target paths and track duplicates
    target_counts: dict[str, list[str]] = {}

    for preview in previews:
        target = preview.new_path.lower()  # Case-insensitive for Windows
        if target not in target_counts:
            target_counts[target] = []
        target_counts[target].append(preview.original_path)

    # Also track original paths to detect overwrites
    original_paths = {p.original_path.lower() for p in previews}

    # Mark conflicts
    for preview in previews:
        target = preview.new_path.lower()
        sources = target_counts[target]

        # Multiple files going to same target
        if len(sources) > 1:
            preview.will_conflict = True
            # Find the other file(s) this conflicts with
            others = [s for s in sources if s != preview.original_path]
            if others:
                preview.conflict_with = others[0]

        # Target exists and is not one of the files being renamed
        elif (
            preview.new_path.lower() != preview.original_path.lower()
            and Path(preview.new_path).exists()
            and preview.new_path.lower() not in original_paths
        ):
            preview.will_conflict = True
            preview.conflict_with = preview.new_path  # Existing file

    return previews


def format_preview_table(previews: list[RenamePreview]) -> str:
    """Format previews as a human-readable table.

    Args:
        previews: List of rename previews to format

    Returns:
        Formatted string representation
    """
    if not previews:
        return "No files to rename."

    lines = []

    # Calculate column widths
    old_width = max(len(p.original_name) for p in previews)
    old_width = min(max(old_width, 8), 40)  # Clamp between 8-40
    new_width = max(len(p.new_name) for p in previews)
    new_width = min(max(new_width, 8), 40)

    # Header
    header = f"{'Original':<{old_width}}  →  {'New Name':<{new_width}}  Status"
    lines.append(header)
    lines.append("-" * len(header))

    # Rows
    conflicts = []
    for p in previews:
        old_name = p.original_name[:old_width] if len(p.original_name) > old_width else p.original_name
        new_name = p.new_name[:new_width] if len(p.new_name) > new_width else p.new_name

        if p.will_conflict:
            status = "⚠ CONFLICT"
            conflicts.append(p)
        elif p.original_name == p.new_name:
            status = "  (no change)"
        else:
            status = "  OK"

        lines.append(f"{old_name:<{old_width}}  →  {new_name:<{new_width}} {status}")

    # Conflict details
    if conflicts:
        lines.append("")
        lines.append("Conflicts detected:")
        for p in conflicts:
            if p.conflict_with:
                lines.append(f"  - '{p.original_name}' would conflict with '{Path(p.conflict_with).name}'")
            else:
                lines.append(f"  - '{p.original_name}' would create a duplicate")

    return "\n".join(lines)


def has_conflicts(previews: list[RenamePreview]) -> bool:
    """Check if any previews have conflicts.

    Args:
        previews: List of rename previews to check

    Returns:
        True if any preview has a conflict
    """
    return any(p.will_conflict for p in previews)


def has_changes(previews: list[RenamePreview]) -> bool:
    """Check if any files would actually be renamed.

    Args:
        previews: List of rename previews to check

    Returns:
        True if at least one file would change names
    """
    return any(p.original_name != p.new_name for p in previews)
