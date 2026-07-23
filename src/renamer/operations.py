"""Core rename operations for transforming filenames.

Provides atomic operations that can be composed together to build
complex filename transformations while preserving file extensions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

# A dash flanked by non-space characters on both sides (e.g. the "-" in "a-b").
_TIGHT_DASH = re.compile(r"(?<=\S)-(?=\S)")

if TYPE_CHECKING:
    from ..analysis.analyzer import AnalysisResult


@dataclass
class RenameOperation:
    """Base class for all rename operations."""

    pass


@dataclass
class TrimStart(RenameOperation):
    """Remove N characters from start of filename (not extension)."""

    count: int


@dataclass
class TrimEnd(RenameOperation):
    """Remove N characters from end of filename (before extension)."""

    count: int


@dataclass
class AddPrefix(RenameOperation):
    """Add text to start of filename."""

    prefix: str


@dataclass
class AddSuffix(RenameOperation):
    """Add text to end of filename (before extension)."""

    suffix: str


@dataclass
class Replace(RenameOperation):
    """Find and replace text in filename."""

    find: str
    replace: str


@dataclass
class SpaceDashes(RenameOperation):
    """Add a space on each side of a dash that has none.

    Only affects a dash tightly wedged between two non-space characters
    (``a-b`` -> ``a - b``); dashes that already have spacing (``a - b``),
    one-sided spacing (``a -b``), or a leading/trailing position are left
    untouched. Useful when a name separates artist and track with a bare
    ``-`` and no spaces, which some DJ software can't search well.
    """

    pass


@dataclass
class AddAnalysis(RenameOperation):
    """Add BPM/Key to filename with configurable format.

    Attributes:
        include_bpm: Whether to include BPM in output
        include_key: Whether to include key in output
        key_format: "keycode" (8A) or "standard" (Am)
        order: "bpm_first" or "key_first"
        position: "start" or "end" of filename
        separator: Text between BPM and key
        bracket_style: "square" [128], "round" (128), or "none" 128
    """

    include_bpm: bool = True
    include_key: bool = True
    key_format: Literal["keycode", "standard"] = "keycode"
    order: Literal["bpm_first", "key_first"] = "key_first"
    position: Literal["start", "end"] = "end"
    separator: str = " "
    bracket_style: Literal["square", "round", "none"] = "square"


def _format_bracket(value: str, style: Literal["square", "round", "none"]) -> str:
    """Wrap a value in brackets according to style."""
    if style == "square":
        return f"[{value}]"
    elif style == "round":
        return f"({value})"
    else:
        return value


def _format_analysis(op: AddAnalysis, analysis: AnalysisResult) -> str:
    """Format BPM/Key string according to operation settings."""
    parts = []

    # Determine key value based on format
    if op.include_key:
        if op.key_format == "keycode":
            key_value = analysis.keycode if analysis.keycode else analysis.key
        else:
            key_value = analysis.key
        if key_value:
            parts.append(("key", _format_bracket(key_value, op.bracket_style)))

    # Format BPM as whole number
    if op.include_bpm and analysis.bpm > 0:
        bpm_value = str(int(round(analysis.bpm)))
        parts.append(("bpm", _format_bracket(bpm_value, op.bracket_style)))

    # Order the parts
    if op.order == "bpm_first":
        parts.sort(key=lambda x: 0 if x[0] == "bpm" else 1)
    else:
        parts.sort(key=lambda x: 0 if x[0] == "key" else 1)

    return op.separator.join(p[1] for p in parts)


def apply_operation(
    filename: str,
    op: RenameOperation,
    analysis: AnalysisResult | None = None,
) -> str:
    """Apply a single operation to a filename, returning new name.

    Args:
        filename: The filename (with or without path)
        op: The operation to apply
        analysis: Analysis result needed for AddAnalysis operations

    Returns:
        The transformed filename
    """
    # Split into path, stem, and extension
    path = Path(filename)
    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    if isinstance(op, TrimStart):
        if op.count > 0:
            stem = stem[op.count:]

    elif isinstance(op, TrimEnd):
        if op.count > 0 and len(stem) > op.count:
            stem = stem[:-op.count]
        elif op.count > 0:
            stem = ""

    elif isinstance(op, AddPrefix):
        stem = op.prefix + stem

    elif isinstance(op, AddSuffix):
        stem = stem + op.suffix

    elif isinstance(op, Replace):
        stem = stem.replace(op.find, op.replace)

    elif isinstance(op, SpaceDashes):
        stem = _TIGHT_DASH.sub(" - ", stem)

    elif isinstance(op, AddAnalysis):
        if analysis is None:
            raise ValueError("AddAnalysis requires an AnalysisResult")

        formatted = _format_analysis(op, analysis)
        if formatted:
            if op.position == "start":
                stem = formatted + op.separator + stem
            else:
                stem = stem + op.separator + formatted

    # Reconstruct the filename
    new_name = stem + suffix
    if parent and str(parent) != ".":
        return str(parent / new_name)
    return new_name


def apply_operations(
    filename: str,
    ops: list[RenameOperation],
    analysis: AnalysisResult | None = None,
) -> str:
    """Apply multiple operations in sequence.

    Args:
        filename: The filename to transform
        ops: List of operations to apply in order
        analysis: Analysis result needed for AddAnalysis operations

    Returns:
        The transformed filename after all operations
    """
    result = filename
    for op in ops:
        result = apply_operation(result, op, analysis)
    return result


def operations_to_dict(ops: list[RenameOperation]) -> list[dict]:
    """Serialize operations to dictionaries for JSON storage."""
    result = []
    for op in ops:
        if isinstance(op, TrimStart):
            result.append({"type": "trim_start", "count": op.count})
        elif isinstance(op, TrimEnd):
            result.append({"type": "trim_end", "count": op.count})
        elif isinstance(op, AddPrefix):
            result.append({"type": "add_prefix", "prefix": op.prefix})
        elif isinstance(op, AddSuffix):
            result.append({"type": "add_suffix", "suffix": op.suffix})
        elif isinstance(op, Replace):
            result.append({"type": "replace", "find": op.find, "replace": op.replace})
        elif isinstance(op, SpaceDashes):
            result.append({"type": "space_dashes"})
        elif isinstance(op, AddAnalysis):
            result.append({
                "type": "add_analysis",
                "include_bpm": op.include_bpm,
                "include_key": op.include_key,
                "key_format": op.key_format,
                "order": op.order,
                "position": op.position,
                "separator": op.separator,
                "bracket_style": op.bracket_style,
            })
    return result


def operations_from_dict(data: list[dict]) -> list[RenameOperation]:
    """Deserialize operations from dictionaries."""
    result = []
    for item in data:
        op_type = item.get("type")
        if op_type == "trim_start":
            result.append(TrimStart(count=item["count"]))
        elif op_type == "trim_end":
            result.append(TrimEnd(count=item["count"]))
        elif op_type == "add_prefix":
            result.append(AddPrefix(prefix=item["prefix"]))
        elif op_type == "add_suffix":
            result.append(AddSuffix(suffix=item["suffix"]))
        elif op_type == "replace":
            result.append(Replace(find=item["find"], replace=item["replace"]))
        elif op_type == "space_dashes":
            result.append(SpaceDashes())
        elif op_type == "add_analysis":
            result.append(AddAnalysis(
                include_bpm=item.get("include_bpm", True),
                include_key=item.get("include_key", True),
                key_format=item.get("key_format", "keycode"),
                order=item.get("order", "key_first"),
                position=item.get("position", "end"),
                separator=item.get("separator", " "),
                bracket_style=item.get("bracket_style", "square"),
            ))
    return result
