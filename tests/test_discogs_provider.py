"""DiscogsProvider against canned payloads — no network, no wall-clock waits.

The provider takes an injectable opener and sleeper precisely so these two
absolutes hold: nothing here reaches api.discogs.com, and the rate-limit tests
finish in microseconds instead of really waiting out a window.
"""

from __future__ import annotations

import urllib.error

import pytest

from src.online import discogs
from src.online.result import (
    ERROR_AUTH,
    ERROR_BAD_RESPONSE,
    ERROR_NETWORK,
    ERROR_NO_TOKEN,
    ERROR_NOT_FOUND,
    ERROR_RATE_LIMIT,
    ERROR_SERVER,
    Candidate,
    LookupFailed,
    TrackQuery,
)

from .discogs_fixtures import (
    MASTER_RESPONSE,
    RELEASE_RESPONSE,
    SEARCH_RESPONSE,
    VA_RELEASE_RESPONSE,
    VINYL_RELEASE_RESPONSE,
    FakeOpener,
    http_error,
)

QUERY = TrackQuery(artist="Underworld", title="Born Slippy", duration=584.0)


def _provider(routes, headers=None, **kwargs):
    """A provider wired to canned routes, a recorded sleep and no real clock."""
    opener = FakeOpener(routes, headers)
    slept: list[float] = []
    waited: list[float] = []
    provider = discogs.DiscogsProvider(
        token="tok",
        opener=opener,
        sleeper=slept.append,
        on_wait=waited.append,
        **kwargs,
    )
    return provider, opener, slept, waited


# --- request shape ----------------------------------------------------------


def test_every_request_carries_the_token_and_a_distinctive_user_agent():
    # urllib's default UA is exactly the one Discogs blocks, and the token is
    # what buys 60 req/min and non-blank images.
    provider, opener, _, _ = _provider({"/database/search": SEARCH_RESPONSE})
    provider.search(QUERY)
    request = opener.requests[0]
    assert request.get_header("Authorization") == "Discogs token=tok"
    assert request.get_header("User-agent").startswith("MixedInP/")
    assert "Python-urllib" not in request.get_header("User-agent")


def test_search_puts_only_the_artist_and_title_on_the_wire():
    # The privacy claim the Settings help text makes: album and duration are
    # used to rank what comes back, never sent.
    query = TrackQuery(
        artist="Underworld", title="Born Slippy", album="Second Toughest", duration=584.0
    )
    provider, opener, _, _ = _provider({"/database/search": SEARCH_RESPONSE})
    provider.search(query)
    url = opener.urls[0]
    assert "artist=Underworld" in url and "track=Born+Slippy" in url
    assert "Second+Toughest" not in url and "584" not in url


def test_a_lookup_without_a_token_fails_before_any_request():
    provider = discogs.DiscogsProvider(token="", opener=FakeOpener({}))
    assert not provider.is_configured()
    with pytest.raises(LookupFailed) as excinfo:
        provider.search(QUERY)
    assert excinfo.value.kind == ERROR_NO_TOKEN


def test_an_unsearchable_query_spends_no_request():
    provider, opener, _, _ = _provider({"/database/search": SEARCH_RESPONSE})
    assert provider.search(TrackQuery(artist="Underworld", title="")) == []
    assert opener.requests == []


# --- search results ---------------------------------------------------------


def test_search_drops_the_bootleg_and_the_unrelated_artist_and_collapses_repressings():
    provider, _, _, _ = _provider({"/database/search": SEARCH_RESPONSE})
    results = provider.search(QUERY)
    # Four results in, one record out: two pressings of one master collapse,
    # the "Unofficial Release" goes, and Leftfield shares no artist word.
    assert len(results) == 1
    assert results[0].master_id == 77
    # The CD survives the collapse (its tracklist is the trustworthy one) but
    # inherits the earliest year seen in the group.
    assert results[0].release_id == 1002
    assert results[0].year == 1996


def test_search_reads_the_fields_the_dialog_shows():
    provider, _, _, _ = _provider({"/database/search": SEARCH_RESPONSE})
    candidate = provider.search(QUERY)[0]
    assert candidate.artist == "Underworld"
    assert candidate.album == "Born Slippy"
    assert candidate.label == "Junior Boy's Own"
    assert candidate.country == "Europe"
    assert candidate.cover_url.endswith("cover-1002.jpg")
    assert candidate.page_url == "https://www.discogs.com/release/1002"
    assert "Born Slippy" in candidate.label_line()
    # The pressing is on the line too, or the single, the EP and the
    # compilation read as three near-identical rows in the switcher.
    assert "CD, Single" in candidate.label_line()


# --- the switcher's line ----------------------------------------------------


def test_a_record_size_beats_the_medium_name_on_the_line():
    # "Vinyl" says less than '12"', and Discogs gives both.
    candidate = Candidate(formats=("Vinyl", '12"', "45 RPM", "Single", "Stereo"))
    assert candidate.format_line() == '12", Single'


def test_the_line_keeps_the_medium_when_there_is_no_size():
    assert Candidate(formats=("CD", "Compilation", "Mixed")).format_line() == (
        "CD, Compilation"
    )


def test_a_format_with_nothing_to_say_adds_nothing():
    assert Candidate(formats=()).format_line() == ""
    assert Candidate(
        album="Born Slippy", label="Junior Boy's Own", year=1995
    ).label_line() == "Born Slippy — Junior Boy's Own — 1995"


def test_a_search_response_without_results_is_a_bad_response():
    provider, _, _, _ = _provider({"/database/search": {"pagination": {}}})
    with pytest.raises(LookupFailed) as excinfo:
        provider.search(QUERY)
    assert excinfo.value.kind == ERROR_BAD_RESPONSE


# --- fetch ------------------------------------------------------------------


def _release_provider(**kwargs):
    return _provider(
        {"/releases/1001": RELEASE_RESPONSE, "/masters/77": MASTER_RESPONSE}, **kwargs
    )


def test_fetch_proposes_the_matched_track_not_the_first_one():
    provider, _, _, _ = _release_provider()
    query = TrackQuery(artist="Underworld", title="Born Slippy (Nuxx) (Radio Edit)")
    proposed = provider.fetch(Candidate(release_id=1001), query)
    assert proposed.title == "Born Slippy (Nuxx) (Radio Edit)"
    assert proposed.track_number == 2  # "B1" is a side, so the count is used


def test_fetch_writes_styles_as_the_genre_not_the_coarse_genre_field():
    # "Electronic" is not a genre a DJ sorts by; "Techno" is.
    provider, _, _, _ = _release_provider()
    proposed = provider.fetch(Candidate(release_id=1001), QUERY)
    assert proposed.genre == "Techno; Progressive House"


def test_fetch_prefers_the_master_year_over_the_pressing_year():
    provider, opener, _, _ = _release_provider()
    proposed = provider.fetch(Candidate(release_id=1001), QUERY)
    assert proposed.year == 1995  # master; the release itself says 1996
    assert any("/masters/77" in url for url in opener.urls)


def test_the_master_year_can_be_turned_off_and_then_costs_no_request():
    provider, opener, _, _ = _release_provider(prefer_master_year=False)
    proposed = provider.fetch(Candidate(release_id=1001), QUERY)
    assert proposed.year == 1996
    assert not any("/masters/" in url for url in opener.urls)


def test_a_master_that_cannot_be_read_leaves_the_pressing_year_standing():
    # Best-effort: the extra call must never fail the whole lookup.
    provider, _, _, _ = _provider(
        {"/releases/1001": RELEASE_RESPONSE, "/masters/77": http_error(500)}
    )
    assert provider.fetch(Candidate(release_id=1001), QUERY).year == 1996


def test_fetch_strips_discogs_disambiguation_from_the_label():
    provider, _, _, _ = _release_provider()
    assert provider.fetch(Candidate(release_id=1001), QUERY).label == "Junior Boy's Own"


def test_fetch_takes_the_primary_image_not_the_first_one():
    provider, _, _, _ = _release_provider()
    proposed = provider.fetch(Candidate(release_id=1001), QUERY)
    assert proposed.artwork_url.endswith("front-1001.jpg")


def test_fetch_never_proposes_a_bpm_or_a_key():
    # The standing decision: those are local analysis only, and Discogs has
    # neither. Asserted as a field-level fact so it can't drift in.
    provider, _, _, _ = _release_provider()
    fields = provider.fetch(Candidate(release_id=1001), QUERY).as_fields()
    assert "bpm" not in fields and "key" not in fields and "energy" not in fields


def test_a_heading_row_is_not_a_track():
    provider, _, _, _ = _release_provider()
    query = TrackQuery(artist="Underworld", title="Side A")
    proposed = provider.fetch(Candidate(release_id=1001), query)
    assert proposed.title != "Side A"


def test_a_compilation_proposes_the_track_artist_not_various():
    provider, _, _, _ = _provider({"/releases/2001": VA_RELEASE_RESPONSE})
    query = TrackQuery(artist="Future Sound Of London", title="Papua New Guinea")
    proposed = provider.fetch(Candidate(release_id=2001), query)
    assert proposed.artist == "The Future Sound Of London"
    assert proposed.album == "Renaissance: The Mix Collection"
    assert proposed.track_number == 2  # "1-2" is disc 1, track 2


def test_a_vinyl_release_with_no_durations_still_matches():
    provider, _, _, _ = _provider({"/releases/3001": VINYL_RELEASE_RESPONSE})
    query = TrackQuery(artist="Phuture", title="Acid Tracks", duration=690.0)
    candidate = Candidate(release_id=3001)
    proposed = provider.fetch(candidate, query)
    assert proposed.title == "Acid Tracks"
    assert candidate.score >= 0.9  # the blank duration cost it nothing


# --- rate limiting and failures --------------------------------------------


def test_a_429_is_waited_out_and_retried():
    provider, opener, slept, waited = _provider(
        {"/database/search": [http_error(429), SEARCH_RESPONSE]}
    )
    assert provider.search(QUERY)
    assert slept == [discogs.RETRY_WAIT_S]
    assert waited == [discogs.RETRY_WAIT_S]  # the UI can say why it paused


def test_a_persistent_429_is_reported_rather_than_retried_forever():
    provider, opener, slept, _ = _provider(
        {"/database/search": [http_error(429)] * discogs.MAX_RETRIES}
    )
    with pytest.raises(LookupFailed) as excinfo:
        provider.search(QUERY)
    assert excinfo.value.kind == ERROR_RATE_LIMIT
    assert len(opener.requests) == discogs.MAX_RETRIES


def test_the_pacer_reads_the_live_headers_rather_than_a_hardcoded_sixty():
    provider, _, slept, _ = _provider(
        {"/database/search": SEARCH_RESPONSE, "/releases/1001": RELEASE_RESPONSE},
        headers={"x-discogs-ratelimit": "60", "x-discogs-ratelimit-remaining": "1"},
    )
    provider.search(QUERY)
    assert provider.rate_limit == 60 and provider.rate_remaining == 1
    # The first request had no counters to go on; the second sees the window
    # nearly spent and slows down instead of walking into a 429.
    assert slept == []
    provider.fetch(Candidate(release_id=1001), QUERY)
    assert slept and slept[0] == discogs.PACE_WAIT_S


def test_a_full_window_does_not_pace():
    provider, _, slept, _ = _provider(
        {"/database/search": SEARCH_RESPONSE},
        headers={"x-discogs-ratelimit-remaining": "59"},
    )
    provider.search(QUERY)
    provider.search(QUERY)
    assert slept == []


@pytest.mark.parametrize(
    "code,kind",
    [(401, ERROR_AUTH), (403, ERROR_AUTH), (404, ERROR_NOT_FOUND), (500, ERROR_SERVER)],
)
def test_http_failures_map_to_one_readable_kind_each(code, kind):
    provider, _, _, _ = _provider({"/database/search": http_error(code)})
    with pytest.raises(LookupFailed) as excinfo:
        provider.search(QUERY)
    assert excinfo.value.kind == kind


def test_being_offline_is_a_network_failure_not_a_crash():
    provider, _, _, _ = _provider(
        {"/database/search": urllib.error.URLError("no route to host")}
    )
    with pytest.raises(LookupFailed) as excinfo:
        provider.search(QUERY)
    assert excinfo.value.kind == ERROR_NETWORK


def test_a_timeout_mid_read_is_a_network_failure_too():
    provider, _, _, _ = _provider({"/database/search": TimeoutError("timed out")})
    with pytest.raises(LookupFailed) as excinfo:
        provider.search(QUERY)
    assert excinfo.value.kind == ERROR_NETWORK


def test_html_where_json_was_expected_is_a_bad_response():
    provider, _, _, _ = _provider({"/database/search": b"<html>maintenance</html>"})
    with pytest.raises(LookupFailed) as excinfo:
        provider.search(QUERY)
    assert excinfo.value.kind == ERROR_BAD_RESPONSE


# --- artwork ----------------------------------------------------------------


def test_artwork_is_fetched_only_when_asked_for():
    provider, opener, _, _ = _release_provider()
    proposed = provider.fetch(Candidate(release_id=1001), QUERY)
    # The address is cheap, the image is not — fetch() gets the URL and stops.
    assert proposed.artwork_url
    assert not any("img.discogs.com" in url for url in opener.urls)


def test_fetch_artwork_returns_the_bytes():
    provider, _, _, _ = _provider({"img.discogs.com": b"\x89PNG\r\n\x1a\n"})
    assert provider.fetch_artwork(
        "https://img.discogs.com/front-1001.jpg"
    ).startswith(b"\x89PNG")


def test_fetch_artwork_with_no_url_asks_for_nothing():
    provider, opener, _, _ = _provider({})
    assert provider.fetch_artwork("") == b""
    assert opener.requests == []


# --- the tracklist the picker offers ----------------------------------------


def test_fetch_keeps_the_whole_filtered_tracklist():
    # The dialog's track picker offers an override, and re-reading a release
    # we have already downloaded to populate a dropdown would be a request
    # spent on nothing.
    provider, _, _, _ = _provider({"/releases/2001": VA_RELEASE_RESPONSE})
    candidate = Candidate(release_id=2001)
    provider.fetch(candidate, TrackQuery(artist="M People", title="Sunrise"))
    assert [e.title for e in candidate.tracklist] == [
        e["title"] for e in VA_RELEASE_RESPONSE["tracklist"] if e["type_"] == "track"
    ]
    # The matched row is one *of* that list, not a copy beside it — the dialog
    # pre-selects by identity.
    assert candidate.track in candidate.tracklist


def test_every_row_carries_the_number_it_would_write():
    provider, _, _, _ = _provider({"/releases/2001": VA_RELEASE_RESPONSE})
    candidate = Candidate(release_id=2001)
    provider.fetch(candidate, TrackQuery(artist="M People", title="Sunrise"))
    # "1-1" is disc 1 track 1; the position is read once, here, so an override
    # in the dialog needs no knowledge of how Discogs spells a position.
    assert [e.number for e in candidate.tracklist] == [1, 2]
