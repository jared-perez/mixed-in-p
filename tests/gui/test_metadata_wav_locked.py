"""A WAV loads into the Metadata panel read-only, with a notice saying why.

mutagen rejects every field on a WAV and `write_metadata` still returns True,
so before this an edit looked saved and was gone on the next load. The panel
now asks `stores_tags()` on load and closes every route that writes: the form,
Add field, the cover, the Discogs tab's arrows and an approved lookup.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.gui.widgets import metadata_panel as mp_mod
from src.gui.widgets.metadata_panel import MetadataPanel
from src.gui.workers.lookup_worker import LookupResult
from src.online.result import Candidate, ProposedTags


def _write(path, fmt):
    sf = pytest.importorskip("soundfile")
    sf.write(str(path), np.zeros(4410, dtype=np.float32), 44100, format=fmt)
    return str(path)


@pytest.fixture
def wav(tmp_path):
    return _write(tmp_path / "Artist - Track.wav", "WAV")


@pytest.fixture
def flac(tmp_path):
    return _write(tmp_path / "Artist - Track.flac", "FLAC")


@pytest.fixture
def panel(qtbot):
    widget = MetadataPanel()
    qtbot.addWidget(widget)
    widget.set_online_lookup(True, token="tok")
    return widget


@pytest.fixture
def writes(monkeypatch):
    """Every tag write the panel attempts, recorded instead of performed."""
    calls: list[str] = []
    monkeypatch.setattr(mp_mod, "write_metadata", lambda *a, **k: calls.append("write"))
    monkeypatch.setattr(mp_mod, "write_comment", lambda *a, **k: calls.append("comment"))
    monkeypatch.setattr(
        mp_mod, "delete_metadata_fields", lambda *a, **k: calls.append("delete")
    )
    monkeypatch.setattr(
        mp_mod.lookup_flow, "apply_values", lambda *a, **k: calls.append("apply") or ""
    )
    return calls


def _result(path) -> LookupResult:
    chosen = Candidate(
        provider="discogs",
        release_id=1,
        artist="Artist",
        album="Album",
        label="Junior",
        country="UK",
        year=1996,
        page_url="https://www.discogs.com/release/1",
        score=0.9,
    )
    return LookupResult(
        path=path,
        candidates=[chosen],
        chosen=chosen,
        proposed=ProposedTags(
            title="Track", provider="discogs", source_url=chosen.page_url
        ),
    )


def test_a_wav_shows_the_notice_and_hides_every_way_to_add(panel, wav):
    panel._load_file(wav)
    assert not panel._tagless_notice.isHidden()
    assert "WAV" in panel._tagless_notice.text()
    assert panel._add_combo.isHidden()
    assert panel._artwork.isHidden()
    assert panel._add_artwork_btn.isHidden()
    assert panel._find_cover_btn.isHidden()


def test_a_wav_does_not_offer_to_fill_tags_it_cannot_keep(panel, wav):
    panel._load_file(wav)
    assert panel._empty_hint.isHidden()


def test_a_flac_is_editable_and_has_no_notice(panel, flac):
    panel._load_file(flac)
    assert panel._tagless_notice.isHidden()
    assert not panel._add_combo.isHidden()
    assert not panel._artwork.isHidden()
    assert not panel._add_artwork_btn.isHidden()


def test_the_lock_does_not_outlive_the_wav(panel, wav, flac):
    panel._load_file(wav)
    panel._load_file(flac)
    assert panel._tagless_notice.isHidden()
    assert not panel._add_combo.isHidden()
    panel._add_field_row("title", "Title", "x")
    assert not panel._field_edits["title"].isReadOnly()


def test_eject_takes_the_notice_down(panel, wav):
    panel._load_file(wav)
    panel._clear()
    assert panel._tagless_notice.isHidden()
    assert panel._tagless is False


def test_a_field_on_a_wav_is_read_only(panel, wav):
    panel._load_file(wav)
    panel._add_field_row("title", "Title", "x")
    assert panel._field_edits["title"].isReadOnly()


def test_nothing_is_written_to_a_wav(panel, wav, writes):
    panel._load_file(wav)
    panel._add_field_row("title", "Title", "x")
    panel._save_metadata()
    panel._on_artwork_changed(b"\x89PNG\r\n\x1a\n", "image/png")
    panel._on_artwork_changed(None, None)
    panel._apply_from_tab({"title": "x"})
    assert writes == []


def test_an_approved_lookup_writes_nothing_and_credits_nothing(panel, wav, writes):
    panel._load_file(wav)
    panel._last_result = _result(wav)
    panel._apply_lookup_values({"title": "Track"})
    assert writes == []
    assert panel._release_link.isHidden()


def test_the_discogs_arrows_are_disabled_on_a_wav(panel, wav):
    from PySide6.QtWidgets import QPushButton

    panel._load_file(wav)

    class _Stub:
        def set_result(self, result):
            pass

    panel._review_dialog = _Stub()
    try:
        panel._on_lookup_result(_result(wav))
    finally:
        panel._review_dialog = None
    arrows = [
        b for b in panel._discogs_body.parentWidget().findChildren(QPushButton)
        if b.objectName() == "discogsApplyButton"
    ]
    assert arrows, "the tab should have drawn the release's rows"
    assert not any(b.isEnabled() for b in arrows)
    assert all(b.toolTip() == panel._tagless_notice.text() for b in arrows)
