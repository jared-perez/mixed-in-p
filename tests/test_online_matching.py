"""Golden tests for the online matching layer.

These are the mis-tagging failure modes the plan named, written as cases that
fail loudly if the scoring ever drifts back into them: version suffixes
collapsed, a missing duration punished, a compilation matched on "Various", the
repress flood shown as twenty near-identical rows.
"""

from __future__ import annotations

from src.online import matching
from src.online.result import Candidate, TrackEntry, TrackQuery


def _candidate(**kwargs) -> Candidate:
    base = dict(
        provider="discogs",
        release_id=1,
        artist="Underworld",
        album="Born Slippy",
        formats=("Vinyl", '12"'),
    )
    base.update(kwargs)
    return Candidate(**base)


# --- normalisation ----------------------------------------------------------


def test_normalize_folds_case_accents_and_punctuation():
    assert matching.normalize("Björk — Jóga!") == "bjork joga"


def test_normalize_strips_feat_clauses_but_keeps_version_suffixes():
    # A credit varies between databases; a version is the record's identity.
    assert matching.normalize("Rez (feat. Darren Price)") == matching.normalize("Rez")
    assert matching.normalize("Rez feat. Darren Price") == matching.normalize("Rez")
    assert "extended mix" in matching.normalize("Rez (Extended Mix)")


def test_normalize_unifies_the_three_spellings_of_and():
    assert matching.normalize("Basement Jaxx & Friends") == matching.normalize(
        "Basement Jaxx and Friends"
    )


def test_strip_artist_suffix_removes_discogs_disambiguation():
    assert matching.strip_artist_suffix("The Future Sound Of London (2)") == (
        "The Future Sound Of London"
    )
    # Not a disambiguation number — part of the name.
    assert matching.strip_artist_suffix("Front 242") == "Front 242"


def test_similarity_of_two_blanks_is_zero_not_one():
    # "We know nothing about either" is not a match; 1.0 here would rank every
    # untagged field as a perfect one.
    assert matching.similarity("", "") == 0.0
    assert matching.similarity("Orbital", "") == 0.0


# --- track scoring ----------------------------------------------------------


def test_version_suffix_decides_between_two_mixes():
    query = TrackQuery(artist="Underworld", title="Born Slippy (Radio Edit)")
    extended = TrackEntry(title="Born Slippy (Extended Mix)", ordinal=1)
    radio = TrackEntry(title="Born Slippy (Radio Edit)", ordinal=2)
    picked, score = matching.pick_track(query, [extended, radio], "Underworld")
    assert picked is radio
    assert score > matching.score_track(query, extended, "Underworld")


def test_missing_duration_is_neutral_never_a_penalty():
    query = TrackQuery(artist="Phuture", title="Acid Tracks", duration=690.0)
    agreeing = TrackEntry(title="Acid Tracks", duration=692.0, ordinal=1)
    missing = TrackEntry(title="Acid Tracks", duration=None, ordinal=1)
    disagreeing = TrackEntry(title="Acid Tracks", duration=200.0, ordinal=1)

    missing_score = matching.score_track(query, missing, "Phuture")
    assert missing_score == matching.score_track(query, agreeing, "Phuture")
    assert missing_score > matching.score_track(query, disagreeing, "Phuture")


def test_duration_tolerance_is_a_few_seconds_not_exactness():
    query = TrackQuery(artist="Orbital", title="Halcyon", duration=300.0)
    inside = TrackEntry(title="Halcyon", duration=303.0, ordinal=1)
    outside = TrackEntry(title="Halcyon", duration=311.0, ordinal=1)
    assert matching.score_track(query, inside, "Orbital") > matching.score_track(
        query, outside, "Orbital"
    )


def test_compilation_matches_on_the_track_artist_not_various():
    query = TrackQuery(artist="M People", title="Sunrise")
    rows = [
        TrackEntry(title="Sunrise", artist="M People", ordinal=1),
        TrackEntry(title="Sunrise", artist="Someone Else", ordinal=2),
    ]
    picked, score = matching.pick_track(query, rows, release_artist="Various")
    assert picked is rows[0]
    assert score >= matching.MATCH_FLOOR


def test_a_wrong_track_scores_below_the_floor():
    query = TrackQuery(artist="Underworld", title="Born Slippy")
    entry = TrackEntry(title="Release The Pressure", artist="Leftfield", ordinal=1)
    assert matching.score_track(query, entry, "Leftfield") < matching.MATCH_FLOOR


def test_pick_track_on_an_empty_tracklist_answers_nothing():
    picked, score = matching.pick_track(TrackQuery(title="x"), [], "y")
    assert picked is None and score == 0.0


# --- candidate ranking ------------------------------------------------------


def test_rank_drops_bootlegs():
    query = TrackQuery(artist="Underworld", title="Born Slippy")
    official = _candidate(release_id=1)
    bootleg = _candidate(release_id=2, formats=("Vinyl", "Unofficial Release"))
    ranked = matching.rank_candidates(query, [official, bootleg])
    assert [c.release_id for c in ranked] == [1]


def test_rank_drops_results_sharing_no_artist_word():
    query = TrackQuery(artist="Underworld", title="Born Slippy")
    other = _candidate(release_id=9, artist="Leftfield", album="Leftism")
    ranked = matching.rank_candidates(query, [_candidate(), other])
    assert [c.release_id for c in ranked] == [1]


def test_rank_keeps_a_various_artists_release_through_the_artist_filter():
    # The release artist is "Various"; the real one is on the tracklist, which
    # this stage has not read yet, so it must not be dropped here.
    query = TrackQuery(artist="M People", title="Sunrise")
    va = _candidate(release_id=5, artist="Various", album="Renaissance")
    assert matching.rank_candidates(query, [va])


def test_repress_flood_collapses_to_one_row_per_master():
    query = TrackQuery(artist="Underworld", title="Born Slippy")
    pressings = [
        _candidate(release_id=i, master_id=77, year=1996 + i, formats=("Vinyl",))
        for i in range(1, 6)
    ]
    ranked = matching.rank_candidates(query, pressings)
    assert len(ranked) == 1


def test_the_survivor_of_a_collapse_inherits_the_earliest_year():
    # Every pressing shares an original release year; the earliest one seen is
    # a free approximation of the master's, which otherwise costs a request.
    query = TrackQuery(artist="Underworld", title="Born Slippy")
    vinyl = _candidate(release_id=1, master_id=77, year=1996, formats=("Vinyl",))
    cd = _candidate(release_id=2, master_id=77, year=1998, formats=("CD",))
    ranked = matching.rank_candidates(query, [vinyl, cd])
    assert len(ranked) == 1
    assert ranked[0].year == 1996


def test_orphan_releases_are_never_collapsed_together():
    query = TrackQuery(artist="Underworld", title="Born Slippy")
    orphans = [_candidate(release_id=i, master_id=None) for i in (1, 2, 3)]
    assert len(matching.rank_candidates(query, orphans)) == 3


def test_a_digital_release_outranks_a_vinyl_one_all_else_equal():
    # Not about audio quality — a CD tracklist's durations can be trusted.
    query = TrackQuery(artist="Underworld", title="Born Slippy")
    cd = _candidate(release_id=1, formats=("CD",))
    vinyl = _candidate(release_id=2, formats=("Vinyl", '12"'))
    ranked = matching.rank_candidates(query, [vinyl, cd])
    assert [c.release_id for c in ranked] == [1, 2]


def test_an_untagged_album_is_not_evidence_against_a_release():
    query_blank = TrackQuery(artist="Underworld", title="Born Slippy")
    query_wrong = TrackQuery(
        artist="Underworld", title="Born Slippy", album="Something Else Entirely"
    )
    blank = matching.score_candidate(query_blank, _candidate())
    wrong = matching.score_candidate(query_wrong, _candidate())
    assert blank > wrong


# --- filename fallback ------------------------------------------------------


def test_parse_filename_strips_the_apps_own_bpm_key_prefix():
    assert matching.parse_filename("128 8A - Underworld - Born Slippy") == (
        "Underworld",
        "Born Slippy",
    )


def test_parse_filename_strips_bracketed_and_suffixed_analysis():
    assert matching.parse_filename("[8A] [128] - Underworld - Born Slippy") == (
        "Underworld",
        "Born Slippy",
    )
    assert matching.parse_filename("Underworld - Born Slippy - 8A 128") == (
        "Underworld",
        "Born Slippy",
    )


def test_parse_filename_handles_underscores_and_track_numbers():
    assert matching.parse_filename("01_Underworld_-_Born_Slippy") == (
        "Underworld",
        "Born Slippy",
    )


def test_parse_filename_keeps_hyphens_inside_names():
    # "Hi-Fi" is a name, not a separator; only a spaced hyphen splits.
    assert matching.parse_filename("K-Klass - Rhythm Is A Mystery") == (
        "K-Klass",
        "Rhythm Is A Mystery",
    )


def test_parse_filename_keeps_the_version_suffix_in_the_title():
    artist, title = matching.parse_filename("Underworld - Born Slippy (Radio Edit)")
    assert (artist, title) == ("Underworld", "Born Slippy (Radio Edit)")


def test_parse_filename_gives_up_rather_than_guessing():
    # No separator: inventing an artist here would put a confident wrong query
    # on the wire.
    assert matching.parse_filename("track01") == ("", "")
    assert matching.parse_filename("") == ("", "")


def test_build_query_fills_only_the_fields_the_tags_left_empty():
    query = matching.build_query(
        artist="Underworld",
        title="",
        filename_stem="128 8A - Someone Else - Born Slippy",
    )
    assert query.artist == "Underworld"  # the tag wins
    assert query.title == "Born Slippy"


def test_build_query_reports_an_unsearchable_file_as_unusable():
    assert not matching.build_query("", "", filename_stem="track01").is_usable()
    assert matching.build_query("", "Born Slippy").is_usable()
