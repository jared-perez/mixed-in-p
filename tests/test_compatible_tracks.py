"""The Compatible Tracks query and its ranking (Part A, phase 1).

Two layers, tested apart: `compatibility.rank_matches` is pure and gets the
ordering cases, `Library.compatible_tracks` gets the ones that are really
about SQL — that the tempo window is applied before Python sees the row,
that a track tagged "Am" matches a seed tagged "8A", and that a row with no
tempo survives the filter instead of being quietly dropped.
"""

from __future__ import annotations

import pytest

from src.library import Library
from src.library.compatibility import (
    KEY_ADJACENT,
    KEY_RELATIVE,
    KEY_SAME,
    TEMPO_DOUBLE,
    TEMPO_HALF,
    TEMPO_SAME,
    TEMPO_UNKNOWN,
    key_relation,
    rank_matches,
    tempo_relation,
)
from src.library.library import Track


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "library.db")
    yield library
    library.close()


def add(lib, tmp_path, name, **tags):
    f = tmp_path / name
    f.write_bytes(b"audio-" + name.encode())
    return lib.add_track(str(f), **tags)


def make_track(track_id=1, **fields) -> Track:
    base = dict(
        id=track_id,
        path=f"/music/{track_id}.mp3",
        filename=f"{track_id}.mp3",
        artist="",
        title="",
        album="",
        genre="",
        comment="",
        bpm=None,
        key="",
        keycode="",
        energy=None,
        year=None,
        track_number=None,
        label=None,
        bitrate=None,
        bit_depth=None,
        duration=None,
        size=None,
        mtime=None,
        content_id=None,
        added_at="2026-08-15T00:00:00",
    )
    base.update(fields)
    return Track(**base)


class TestKeyRelation:
    @pytest.mark.parametrize(
        "candidate,expected",
        [
            ("8A", KEY_SAME),
            ("8B", KEY_RELATIVE),
            ("7A", KEY_ADJACENT),
            ("9A", KEY_ADJACENT),
            ("7B", None),
            ("9B", None),
            ("3A", None),
        ],
    )
    def test_the_four_compatible_codes_and_nothing_else(self, candidate, expected):
        assert key_relation("8A", candidate) == expected

    def test_the_wheel_wraps_at_twelve(self):
        assert key_relation("12A", "1A") == KEY_ADJACENT
        assert key_relation("1A", "12A") == KEY_ADJACENT
        assert key_relation("12B", "1B") == KEY_ADJACENT

    @pytest.mark.parametrize("code", ["", "  ", "Am", "13A", "8C", "A"])
    def test_an_unparseable_code_is_not_compatible_with_anything(self, code):
        """An empty `keycode` column means "we could not read this track's
        key" — it must never read as a match, in either position."""
        assert key_relation("8A", code) is None
        assert key_relation(code, "8A") is None

    def test_lowercase_and_padding_are_accepted(self):
        assert key_relation(" 8a ", "8b") == KEY_RELATIVE


class TestTempoRelation:
    def test_inside_the_window_is_a_same_tempo_match(self):
        relation, delta = tempo_relation(128.0, 130.0)
        assert relation == TEMPO_SAME
        assert delta == pytest.approx(2.0)

    def test_outside_the_window_is_no_match(self):
        assert tempo_relation(128.0, 145.0) is None

    def test_the_window_is_eight_percent_by_default(self):
        assert tempo_relation(100.0, 108.0) is not None
        assert tempo_relation(100.0, 108.1) is None
        assert tempo_relation(100.0, 92.0) is not None
        assert tempo_relation(100.0, 91.9) is None

    def test_a_half_time_candidate_counts_and_is_labelled(self):
        relation, delta = tempo_relation(128.0, 64.0)
        assert relation == TEMPO_HALF
        assert delta == pytest.approx(0.0)

    def test_a_double_time_candidate_counts_and_is_labelled(self):
        relation, delta = tempo_relation(128.0, 256.0)
        assert relation == TEMPO_DOUBLE
        assert delta == pytest.approx(0.0)

    @pytest.mark.parametrize(
        "seed_bpm,candidate_bpm", [(None, 128.0), (128.0, None), (0.0, 128.0), (128.0, 0.0)]
    )
    def test_a_missing_tempo_is_unknown_not_a_rejection(self, seed_bpm, candidate_bpm):
        assert tempo_relation(seed_bpm, candidate_bpm) == (TEMPO_UNKNOWN, None)

    def test_a_tolerance_wide_enough_to_reach_both_readings_prefers_same(self):
        """At ±60% a 100 BPM candidate is within reach of a 128 seed both
        as itself and doubled (200 is not, but 50 doubled is 100). The
        closer reading wins, and same-tempo wins a tie."""
        relation, delta = tempo_relation(128.0, 100.0, tolerance=0.6)
        assert relation == TEMPO_SAME
        assert delta == pytest.approx(28.0)


class TestRanking:
    def test_key_tier_beats_everything_else(self):
        seed = make_track(1, keycode="8A", bpm=128.0, energy=5)
        adjacent_perfect = make_track(2, keycode="9A", bpm=128.0, energy=5)
        same_worse = make_track(3, keycode="8A", bpm=133.0, energy=1)
        ranked = rank_matches(seed, [adjacent_perfect, same_worse])
        assert [m.track.id for m in ranked] == [3, 2]

    def test_same_tempo_outranks_half_time_within_a_key_tier(self):
        seed = make_track(1, keycode="8A", bpm=128.0)
        halved = make_track(2, keycode="8A", bpm=64.0)  # 0.0 away, doubled
        same = make_track(3, keycode="8A", bpm=126.0)  # 2.0 away
        ranked = rank_matches(seed, [halved, same])
        assert [m.track.id for m in ranked] == [3, 2]
        assert ranked[1].tempo_relation == TEMPO_HALF

    def test_a_track_with_no_tempo_is_last_but_present(self):
        seed = make_track(1, keycode="8A", bpm=128.0)
        untagged = make_track(2, keycode="8A")
        matched = make_track(3, keycode="8A", bpm=130.0)
        ranked = rank_matches(seed, [untagged, matched])
        assert [m.track.id for m in ranked] == [3, 2]
        assert ranked[1].tempo_relation == TEMPO_UNKNOWN
        assert ranked[1].bpm_delta is None

    def test_energy_breaks_a_tie(self):
        seed = make_track(1, keycode="8A", bpm=128.0, energy=6)
        far = make_track(2, keycode="8A", bpm=128.0, energy=1)
        near = make_track(3, keycode="8A", bpm=128.0, energy=7)
        ranked = rank_matches(seed, [far, near])
        assert [m.track.id for m in ranked] == [3, 2]
        assert [m.energy_delta for m in ranked] == [1, 5]

    def test_a_track_with_no_energy_sits_at_the_end_of_its_tier(self):
        seed = make_track(1, keycode="8A", bpm=128.0, energy=6)
        blank = make_track(2, keycode="8A", bpm=128.0)
        far = make_track(3, keycode="8A", bpm=128.0, energy=1)
        ranked = rank_matches(seed, [blank, far])
        assert [m.track.id for m in ranked] == [3, 2]
        assert ranked[1].energy_delta is None

    def test_a_seed_without_energy_ranks_nobody_by_energy(self):
        """Not the same as everyone tying at distance zero: with no seed
        energy the field is meaningless, so the alphabetical tiebreak
        decides rather than whichever candidate happens to hold a 1."""
        seed = make_track(1, keycode="8A", bpm=128.0)
        loud = make_track(2, keycode="8A", bpm=128.0, energy=10, artist="Zed")
        quiet = make_track(3, keycode="8A", bpm=128.0, energy=1, artist="Ada")
        ranked = rank_matches(seed, [loud, quiet])
        assert [m.track.id for m in ranked] == [3, 2]
        assert [m.energy_delta for m in ranked] == [None, None]

    def test_the_seed_never_matches_itself(self):
        seed = make_track(1, keycode="8A", bpm=128.0)
        assert rank_matches(seed, [seed]) == []

    def test_incompatible_candidates_are_dropped_even_if_unfiltered(self):
        seed = make_track(1, keycode="8A", bpm=128.0)
        wrong_key = make_track(2, keycode="3B", bpm=128.0)
        wrong_tempo = make_track(3, keycode="8A", bpm=160.0)
        assert rank_matches(seed, [wrong_key, wrong_tempo]) == []

    def test_the_cap_takes_the_best_rows(self):
        seed = make_track(1, keycode="8A", bpm=128.0)
        candidates = [make_track(9, keycode="9A", bpm=128.0)] + [
            make_track(i, keycode="8A", bpm=128.0) for i in range(10, 20)
        ]
        ranked = rank_matches(seed, candidates, limit=3)
        assert len(ranked) == 3
        assert all(m.key_relation == KEY_SAME for m in ranked)


class TestCompatibleTracksQuery:
    def test_the_four_codes_come_back_and_nothing_else(self, lib, tmp_path):
        seed = add(lib, tmp_path, "seed.mp3", key="8A", bpm=128.0)
        add(lib, tmp_path, "same.mp3", key="8A", bpm=128.0)
        add(lib, tmp_path, "relative.mp3", key="8B", bpm=128.0)
        add(lib, tmp_path, "adjacent.mp3", key="9A", bpm=128.0)
        add(lib, tmp_path, "unrelated.mp3", key="3B", bpm=128.0)
        names = [m.track.filename for m in lib.compatible_tracks(seed)]
        assert names == ["same.mp3", "relative.mp3", "adjacent.mp3"]

    def test_a_key_spelled_any_way_still_matches(self, lib, tmp_path):
        """The stored `key` is whatever the file's tag said; the derived
        `keycode` column is what the query matches on, which is the whole
        reason it exists."""
        seed = add(lib, tmp_path, "seed.mp3", key="Am", bpm=128.0)
        add(lib, tmp_path, "code.mp3", key="8A", bpm=128.0)
        add(lib, tmp_path, "words.mp3", key="A minor", bpm=128.0)
        add(lib, tmp_path, "relative.mp3", key="C major", bpm=128.0)
        assert len(lib.compatible_tracks(seed)) == 3

    def test_the_tempo_window_is_applied_in_sql(self, lib, tmp_path):
        seed = add(lib, tmp_path, "seed.mp3", key="8A", bpm=128.0)
        add(lib, tmp_path, "close.mp3", key="8A", bpm=132.0)
        add(lib, tmp_path, "far.mp3", key="8A", bpm=150.0)
        names = [m.track.filename for m in lib.compatible_tracks(seed)]
        assert names == ["close.mp3"]

    def test_half_time_survives_the_sql_filter(self, lib, tmp_path):
        seed = add(lib, tmp_path, "seed.mp3", key="8A", bpm=128.0)
        add(lib, tmp_path, "halved.mp3", key="8A", bpm=64.0)
        add(lib, tmp_path, "doubled.mp3", key="8A", bpm=256.0)
        matches = {m.track.filename: m.tempo_relation for m in lib.compatible_tracks(seed)}
        assert matches == {"halved.mp3": TEMPO_HALF, "doubled.mp3": TEMPO_DOUBLE}

    def test_an_unanalysed_track_is_kept_and_ranked_last(self, lib, tmp_path):
        seed = add(lib, tmp_path, "seed.mp3", key="8A", bpm=128.0)
        add(lib, tmp_path, "no_bpm.mp3", key="8A")
        add(lib, tmp_path, "matched.mp3", key="8A", bpm=128.0)
        names = [m.track.filename for m in lib.compatible_tracks(seed)]
        assert names == ["matched.mp3", "no_bpm.mp3"]

    def test_a_tolerance_of_zero_still_matches_an_exact_tempo(self, lib, tmp_path):
        seed = add(lib, tmp_path, "seed.mp3", key="8A", bpm=128.0)
        add(lib, tmp_path, "exact.mp3", key="8A", bpm=128.0)
        add(lib, tmp_path, "near.mp3", key="8A", bpm=129.0)
        names = [m.track.filename for m in lib.compatible_tracks(seed, bpm_tolerance=0.0)]
        assert names == ["exact.mp3"]

    def test_a_seed_with_no_tempo_matches_on_key_alone(self, lib, tmp_path):
        seed = add(lib, tmp_path, "seed.mp3", key="8A")
        add(lib, tmp_path, "slow.mp3", key="8A", bpm=90.0)
        add(lib, tmp_path, "fast.mp3", key="8A", bpm=174.0)
        assert len(lib.compatible_tracks(seed)) == 2

    def test_a_seed_with_no_readable_key_returns_nothing(self, lib, tmp_path):
        seed = add(lib, tmp_path, "seed.mp3", bpm=128.0)
        add(lib, tmp_path, "other.mp3", key="8A", bpm=128.0)
        assert lib.compatible_tracks(seed) == []

    def test_an_unknown_seed_id_returns_nothing(self, lib, tmp_path):
        add(lib, tmp_path, "other.mp3", key="8A", bpm=128.0)
        assert lib.compatible_tracks(9999) == []

    def test_the_seed_is_excluded_from_its_own_results(self, lib, tmp_path):
        seed = add(lib, tmp_path, "seed.mp3", key="8A", bpm=128.0)
        assert lib.compatible_tracks(seed) == []

    def test_the_limit_caps_the_ranked_list(self, lib, tmp_path):
        seed = add(lib, tmp_path, "seed.mp3", key="8A", bpm=128.0)
        for i in range(6):
            add(lib, tmp_path, f"t{i}.mp3", key="8A", bpm=128.0)
        assert len(lib.compatible_tracks(seed, limit=4)) == 4
        assert len(lib.compatible_tracks(seed, limit=None)) == 6

    def test_energy_from_the_library_orders_the_result(self, lib, tmp_path):
        seed = add(lib, tmp_path, "seed.mp3", key="8A", bpm=128.0, energy=7)
        add(lib, tmp_path, "calm.mp3", key="8A", bpm=128.0, energy=2)
        add(lib, tmp_path, "close.mp3", key="8A", bpm=128.0, energy=8)
        names = [m.track.filename for m in lib.compatible_tracks(seed)]
        assert names == ["close.mp3", "calm.mp3"]
