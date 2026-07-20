"""Background worker that checks GitHub for a newer app release.

Manual/button-triggered only — there is no automatic startup check, so the
app never touches the network unless the user asks it to. The check hits the
public GitHub "latest release" endpoint, compares the release tag against the
installed version, and reports one of three outcomes back to the UI.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

from src import __version__

# Public "latest release" endpoint for the distribution repo. Returns JSON with
# a ``tag_name`` like "v1.3.4"; the leading "v" is stripped before comparison.
_LATEST_RELEASE_API = (
    "https://api.github.com/repos/jared-perez/mixed-in-p/releases/latest"
)
# Human-facing page the "Download" / "see all releases" links open in a browser.
RELEASES_PAGE_URL = "https://github.com/jared-perez/mixed-in-p/releases"

# Outcome codes carried by UpdateCheckResult.status. These are logic values, not
# UI prose — the human-readable strings are built (and translated) in the dialog.
STATUS_CURRENT = "current"
STATUS_AVAILABLE = "available"
STATUS_ERROR = "error"


def _parse_version(text: str) -> tuple[int, ...]:
    """Parse a version string into a comparable tuple of ints.

    Tolerant of a leading "v" and of pre-release suffixes (e.g. "1.3.4-rc1"):
    each dot-separated part contributes its leading digits, so "1.3.4-rc1"
    parses the same as "1.3.4". Unparseable parts count as 0.
    """
    cleaned = text.strip().lstrip("vV")
    parts: list[int] = []
    for part in cleaned.split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _is_newer(latest: str, current: str) -> bool:
    """True if ``latest`` is a strictly higher version than ``current``."""
    a = _parse_version(latest)
    b = _parse_version(current)
    # Zero-pad the shorter tuple so "1.3" and "1.3.0" compare equal.
    length = max(len(a), len(b))
    a += (0,) * (length - len(a))
    b += (0,) * (length - len(b))
    return a > b


@dataclass
class UpdateCheckResult:
    """Outcome of an update check.

    ``status`` is one of the STATUS_* codes. ``latest_version`` holds the
    tag (without the leading "v") when status is STATUS_AVAILABLE.
    """

    status: str
    latest_version: str = ""


class UpdateCheckThread(QThread):
    """Fetches the latest release tag off the UI thread and reports the result.

    Emits ``result_ready`` with the outcome. (The built-in ``QThread.finished``
    is left free for lifecycle cleanup — e.g. ``deleteLater`` — by the caller.)
    """

    result_ready = Signal(UpdateCheckResult)

    def run(self) -> None:
        try:
            # GitHub's API rejects requests without a User-Agent header.
            request = urllib.request.Request(
                _LATEST_RELEASE_API,
                headers={
                    "User-Agent": "MixedInP-UpdateCheck",
                    "Accept": "application/vnd.github+json",
                },
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            latest = str(payload.get("tag_name", "")).strip()
        except Exception:
            # Any failure (offline, DNS, timeout, rate limit, bad JSON) is a
            # single "couldn't check" outcome — the UI offers the releases page
            # as a manual fallback.
            self.result_ready.emit(UpdateCheckResult(STATUS_ERROR))
            return

        if not latest:
            self.result_ready.emit(UpdateCheckResult(STATUS_ERROR))
            return

        if _is_newer(latest, __version__):
            self.result_ready.emit(
                UpdateCheckResult(STATUS_AVAILABLE, latest.lstrip("vV"))
            )
        else:
            self.result_ready.emit(UpdateCheckResult(STATUS_CURRENT))
