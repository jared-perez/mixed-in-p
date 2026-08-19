"""The seam a metadata provider plugs into.

v1 registers exactly one provider (Discogs). The protocol exists so a second —
MusicBrainz is the designated candidate — can be added without the GUI knowing
which one it is talking to. Spotify is shelved (see the plan doc's appendix);
the seam is what keeps that decision cheap to revisit.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .result import Candidate, ProposedTags, TrackQuery


@runtime_checkable
class MetadataProvider(Protocol):
    """Two calls: find releases, then read the chosen one.

    Implementations raise :class:`~src.online.result.LookupFailed` for every
    failure the UI has a sentence for, and are expected to be usable off the
    main thread (they are driven by a QThread worker, and hold no Qt objects).
    """

    #: Stable identifier used in logs, config and ``ProposedTags.provider``.
    name: str

    #: What the UI credits in the review dialog, e.g. "Discogs".
    display_name: str

    def is_configured(self) -> bool:
        """True if the provider has everything it needs to run a lookup."""
        ...

    def search(self, query: TrackQuery, limit: int = 10) -> list[Candidate]:
        """Candidate releases for one file, best first."""
        ...

    def fetch(self, candidate: Candidate, query: TrackQuery) -> ProposedTags:
        """Read the chosen release and turn it into proposed tag values."""
        ...
