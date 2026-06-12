"""File renaming system for Mixed in P.

Provides flexible filename manipulation with preview, undo support,
and integration with audio analysis results.
"""

from .operations import (
    RenameOperation,
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

from .preview import (
    RenamePreview,
    preview_rename,
    detect_conflicts,
    format_preview_table,
    has_conflicts,
    has_changes,
)

from .history import (
    RenameRecord,
    RenameSession,
    save_session,
    load_session,
    list_sessions,
    delete_session,
    undo_session,
    create_session,
    format_session_list,
    get_history_dir,
)

__all__ = [
    # Operations
    "RenameOperation",
    "TrimStart",
    "TrimEnd",
    "AddPrefix",
    "AddSuffix",
    "Replace",
    "AddAnalysis",
    "apply_operation",
    "apply_operations",
    "operations_to_dict",
    "operations_from_dict",
    # Preview
    "RenamePreview",
    "preview_rename",
    "detect_conflicts",
    "format_preview_table",
    "has_conflicts",
    "has_changes",
    # History
    "RenameRecord",
    "RenameSession",
    "save_session",
    "load_session",
    "list_sessions",
    "delete_session",
    "undo_session",
    "create_session",
    "format_session_list",
    "get_history_dir",
]
