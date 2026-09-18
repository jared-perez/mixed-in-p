"""The playing context's bookkeeping, without Qt.

Every list here holds duplicate paths, because a duplicate is where identity
and path disagree — and where a by-value comparison would look right while
following the wrong copy.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.gui.play_context import (
    PlayContext,
    index_of,
    locate,
    next_index,
    prev_index,
    resync,
)


@dataclass
class Entry:
    """Stands in for PlaylistEntry: a dataclass, so == compares fields."""

    file_path: str


def entries(*paths: str) -> list[Entry]:
    return [Entry(p) for p in paths]


def ctx_at(order: list[Entry], i: int, node_id: int = 1) -> PlayContext:
    return PlayContext(node_id=node_id, entry=order[i], position=i)


def without(order: list[Entry], *gone: Entry) -> list[Entry]:
    return [e for e in order if all(e is not g for g in gone)]


class TestIndexOf:
    def test_is_identity_not_equality(self):
        a1, b, a2 = entries("a", "b", "a")
        assert a1 == a2  # the trap: equal fields
        assert index_of([a1, b, a2], a2) == 2
        assert index_of([a1, b], a2) == -1


class TestResync:
    def test_removing_another_row_moves_the_position(self):
        old = entries("a", "b", "c", "d")
        ctx = ctx_at(old, 2)
        new = without(old, old[0])
        got = resync(ctx, old, new)
        assert got.entry is old[2]
        assert got.position == 1 and not got.orphaned

    def test_removing_a_duplicate_copy_keeps_the_playing_copy(self):
        old = entries("a", "b", "a")
        ctx = ctx_at(old, 2)  # the second copy
        new = without(old, old[0])  # remove the FIRST copy
        got = resync(ctx, old, new)
        assert got.entry is old[2] and got.position == 1 and not got.orphaned

    def test_removing_the_playing_row_orphans_it_before_its_successor(self):
        old = entries("a", "b", "a", "c")
        ctx = ctx_at(old, 0)
        new = without(old, old[0])
        got = resync(ctx, old, new)
        assert got.orphaned
        assert got.position == 0 and got.successor is old[1]
        assert next_index(got, len(new)) == 0  # b, the row that followed
        assert prev_index(got, len(new)) is None

    def test_removing_the_playing_row_and_its_successor(self):
        old = entries("a", "b", "c", "d")
        ctx = ctx_at(old, 1)
        new = without(old, old[1], old[2])
        got = resync(ctx, old, new)
        assert got.orphaned and got.successor is old[3] and got.position == 1

    def test_removing_the_last_row_while_it_plays(self):
        old = entries("a", "b", "a")
        ctx = ctx_at(old, 2)
        new = without(old, old[2])
        got = resync(ctx, old, new)
        assert got.orphaned and got.successor is None
        assert got.position == 2
        assert next_index(got, len(new)) is None
        assert prev_index(got, len(new)) == 1

    def test_removing_every_row(self):
        old = entries("a", "a", "b")
        ctx = ctx_at(old, 1)
        got = resync(ctx, old, [])
        assert got.orphaned and got.position == 0 and got.successor is None
        assert next_index(got, 0) is None and prev_index(got, 0) is None

    def test_reorder_while_orphaned_follows_the_successor(self):
        old = entries("a", "b", "c", "d")
        ctx = resync(ctx_at(old, 1), old, without(old, old[1]))  # gap before c
        mid = without(old, old[1])  # [a, c, d]
        moved = [mid[1], mid[2], mid[0]]  # [c, d, a]
        got = resync(ctx, mid, moved)
        assert got.orphaned and got.successor is old[2]
        assert got.position == 0

    def test_an_orphans_successor_removed_later_moves_the_gap_on(self):
        old = entries("a", "b", "c", "d")
        ctx = resync(ctx_at(old, 1), old, without(old, old[1]))
        mid = without(old, old[1])  # [a, c, d], gap before c
        new = without(mid, mid[1])  # c goes too
        got = resync(ctx, mid, new)
        assert got.successor is old[3] and got.position == 1

    def test_an_end_gap_reaches_rows_appended_after_it(self):
        old = entries("a", "b")
        ctx = resync(ctx_at(old, 1), old, [old[0]])
        assert ctx.position == 1 and ctx.successor is None
        extra = Entry("z")
        got = resync(ctx, [old[0]], [old[0], extra])
        assert got.successor is extra
        assert next_index(got, 2) == 1

    def test_the_orphan_does_not_rebind_to_a_same_path_copy(self):
        old = entries("a", "b", "a")
        ctx = resync(ctx_at(old, 0), old, without(old, old[0]))
        got = resync(ctx, [old[1], old[2]], [old[1], old[2]])
        assert got.orphaned  # the other "a" is a different copy


class TestLocate:
    def test_nothing_moved(self):
        ctx = PlayContext(1, Entry("b"), 1)
        assert locate(ctx, ["a", "b", "c"]) is ctx

    def test_after_an_append(self):
        ctx = PlayContext(1, Entry("b"), 1)
        got = locate(ctx, ["a", "b", "c", "d", "b"])
        assert got.position == 1 and not got.orphaned

    def test_after_a_shift(self):
        ctx = PlayContext(1, Entry("b"), 1)
        got = locate(ctx, ["x", "a", "b", "c"])
        assert got.position == 2 and not got.orphaned

    def test_after_a_removal(self):
        ctx = PlayContext(1, Entry("b"), 3)
        got = locate(ctx, ["a", "c"])
        assert got.orphaned and got.position == 2
        assert next_index(got, 2) is None and prev_index(got, 2) == 1

    def test_a_duplicate_on_each_side_picks_the_nearer(self):
        ctx = PlayContext(1, Entry("b"), 3)
        assert locate(ctx, ["b", "x", "x", "y", "b"]).position == 4
        assert locate(ctx, ["x", "x", "b", "y", "x", "x", "b"]).position == 2

    def test_a_tie_goes_to_the_later_copy(self):
        ctx = PlayContext(1, Entry("b"), 2)
        assert locate(ctx, ["x", "b", "y", "b"]).position == 3

    def test_an_orphan_follows_its_successors_path(self):
        ctx = PlayContext(1, Entry("a"), 1, orphaned=True, successor=Entry("c"))
        got = locate(ctx, ["x", "b", "c"])
        assert got.orphaned and got.position == 2

    def test_an_orphan_never_rebinds_to_its_own_path(self):
        ctx = PlayContext(1, Entry("a"), 0, orphaned=True, successor=Entry("b"))
        got = locate(ctx, ["a", "b"])
        assert got.orphaned and got.position == 1


class TestNextPrev:
    def test_a_row_steps_from_itself(self):
        ctx = PlayContext(1, Entry("b"), 1)
        assert next_index(ctx, 3) == 2 and prev_index(ctx, 3) == 0
        assert next_index(ctx, 2) is None

    def test_a_gap_steps_to_either_side(self):
        ctx = PlayContext(1, Entry("b"), 1, orphaned=True)
        assert next_index(ctx, 3) == 1 and prev_index(ctx, 3) == 0
