"""State enums and application state management."""

from enum import Enum


class TrackState(Enum):
    """State of a track in the application workflow."""

    QUEUED = "queued"  # In queue, awaiting analysis
    PENDING = "pending"  # Sent to analysis worker
    ANALYSING = "analysing"  # Currently processing
    ANALYSED = "analysed"  # Complete
    ERROR = "error"  # Failed


class AppPage(Enum):
    """Application navigation pages."""

    QUEUE = "queue"
    ANALYSIS = "analysis"
    RENAME = "rename"
    KEYCODE = "keycode"
    HISTORY = "history"
