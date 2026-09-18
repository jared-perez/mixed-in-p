"""Which row, in which playlist, is playing — kept apart from the list on screen.

Qt-free on purpose, like convert_pipeline.py: the Player owns one context and
does all the I/O, so what is worth isolating is the bookkeeping. Two things
the Player used to conflate:

- the **playing context**: the playlist play was pressed in, and the exact row;
- the **viewed list**: whatever is on screen and being edited.

A row has no stable id. playlist_items is rewritten wholesale by set_items, so
a row's identity exists only as a PlaylistEntry *object* while its list is
loaded, and as a position in the database. Everything here therefore works in
two currencies: identity (``is``) while the list is in memory, and position
plus path when it has been re-read from the library.

Never compare entries with ``==``, ``in`` or ``list.index``: PlaylistEntry is a
dataclass, so those compare *fields*, and two copies of one file are equal.
That is the one mistake that makes everything look fixed except duplicates.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Sequence


@dataclass
class PlayContext:
    """The row that is playing, and where it sits in its playlist."""

    # None = started from a search result set (see ``snapshot``).
    node_id: int | None
    # The row that is playing. Compared by IDENTITY, never by value.
    entry: Any
    # An index in the node's STORED order at the last sync. Not orphaned: the
    # entry's own index. Orphaned: the index of whatever followed it, i.e. a
    # gap between two rows (len(list) when nothing followed it).
    position: int
    # The row was removed from its playlist; it plays on, but is not a row.
    orphaned: bool = False
    # A search context's list, as it was when play was pressed. It keeps
    # driving Next/Previous after the search is dismissed.
    snapshot: list | None = None
    # Orphans only: the entry the gap sits in front of, or None at the end.
    # What keeps the gap anchored when rows above it are removed or moved.
    successor: Any = None


def index_of(items: Sequence, entry: Any) -> int:
    """Index of *entry* in *items* by identity, or -1."""
    if entry is None:
        return -1
    for i, item in enumerate(items):
        if item is entry:
            return i
    return -1


def _nearest(paths: Sequence[str], path: str, position: int) -> int:
    """Index of the occurrence of *path* nearest to *position*, or -1.

    A tie goes to the later one: the usual reason a row is one further down
    than remembered is that something was re-inserted above it (an undo).
    """
    best = -1
    best_distance = None
    for i, p in enumerate(paths):
        if p != path:
            continue
        distance = abs(i - position)
        # <= while walking forward: a tie is won by the later index.
        if best_distance is None or distance <= best_distance:
            best, best_distance = i, distance
    return best


def _gap(old_order: Sequence, new_order: Sequence, start: int) -> tuple[int, Any]:
    """Walk *old_order* forward from *start* to the first entry still present
    in *new_order*. Returns (its index in new_order, the entry), or
    (len(new_order), None) when nothing after *start* survived."""
    for candidate in old_order[max(start, 0):]:
        i = index_of(new_order, candidate)
        if i >= 0:
            return i, candidate
    return len(new_order), None


def resync(ctx: PlayContext, old_order: Sequence, new_order: Sequence) -> PlayContext:
    """Follow the playing row through an edit of the list it plays from.

    Both orders are the node's stored (canonical) order, before and after,
    holding the same entry objects. Identity decides everything.
    """
    i = index_of(new_order, ctx.entry)
    if i >= 0:
        return replace(ctx, position=i, orphaned=False, successor=None)
    if not ctx.orphaned:
        old = index_of(old_order, ctx.entry)
        start = old + 1 if old >= 0 else ctx.position
    elif ctx.successor is not None:
        old = index_of(old_order, ctx.successor)
        start = old if old >= 0 else ctx.position
    else:
        # A gap at the end stays after whatever preceded it, so rows appended
        # later are what Next reaches — the same answer locate() gives.
        position = min(ctx.position, len(new_order))
        successor = new_order[position] if position < len(new_order) else None
        return replace(ctx, position=position, orphaned=True, successor=successor)
    position, successor = _gap(old_order, new_order, start)
    return replace(ctx, position=position, orphaned=True, successor=successor)


def locate(ctx: PlayContext, paths: Sequence[str]) -> PlayContext:
    """Re-find the playing row in a list just re-read from the library.

    Used when the playing list is not on screen (or has just been loaded), so
    its entries are new objects and only paths and positions can be compared.
    The caller re-binds ``entry``/``successor`` to the new objects if it has
    them; this only settles ``position`` and ``orphaned``.
    """
    n = len(paths)
    if not ctx.orphaned:
        if 0 <= ctx.position < n and paths[ctx.position] == ctx.entry.file_path:
            return ctx
        i = _nearest(paths, ctx.entry.file_path, ctx.position)
        if i >= 0:
            return replace(ctx, position=i)
        return replace(ctx, position=min(ctx.position, n), orphaned=True, successor=None)
    if ctx.successor is not None:
        i = _nearest(paths, ctx.successor.file_path, ctx.position)
        if i >= 0:
            return replace(ctx, position=i)
    return replace(ctx, position=min(ctx.position, n), successor=None)


def next_index(ctx: PlayContext, n: int) -> int | None:
    """The index Next plays in a list of length *n*, or None at the end."""
    target = ctx.position if ctx.orphaned else ctx.position + 1
    return target if 0 <= target < n else None


def prev_index(ctx: PlayContext, n: int) -> int | None:
    """The index Previous plays in a list of length *n*, or None at the top.

    An orphan's Previous is the row before the gap.
    """
    target = min(ctx.position, n) - 1
    return target if 0 <= target < n else None
