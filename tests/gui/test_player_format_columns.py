"""Format and Bit Depth: two optional Player columns, and two different
answers to "where does a value that is not a tag come from?".

**Format** is free. It is the extension, so it needs no storage, no file open
and no read — which also means it cannot go stale: it is a property on the
entry, so a rename or a relocate moves it, and a track whose file has gone
missing still shows what it was.

**Bit Depth** is the opposite, and the interesting one. It lives in the
stream, so it costs an open — and it is *absent* rather than unknown for every
lossy file, which is what makes the cost bounded: only a lossless file whose
depth we do not already hold is worth opening for. What it learns is written
onto the library row (schema v8), so that open happens once per file ever.
Both halves are load-bearing: without the trigger, every row that predates the
column would show a blank cell forever; without the store, a fully-tagged
playlist would open every one of its files on every single load.

The third thing under test is the width. Both columns hold a **closed set** of
values — six format codes, four depths — so they can be sized so nothing ever
clips, and they must be, because `NoElideDelegate` cuts a value with no
ellipsis to admit it: "24 bi" reads as a number rather than as damage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.gui.widgets.player_panel import (
    _BIT_DEPTHS,
    _FORMAT_LABELS,
    PlayerPanel,
    _format_label,
    _has_bit_depth,
    _widest_depth,
)
from src.library import Library
from src.metadata.tags import read_bit_depth, read_metadata

FORMAT_COLUMN = PlayerPanel._FORMAT_COLUMN
BIT_DEPTH_COLUMN = PlayerPanel._BIT_DEPTH_COLUMN


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "library.db")
    yield library
    library.close()


@pytest.fixture
def player(qtbot, lib):
    panel = PlayerPanel()
    qtbot.addWidget(panel)
    panel.set_library(lib)
    return panel


@pytest.fixture
def sf():
    return pytest.importorskip("soundfile")


def write_audio(sf, path, *, subtype="PCM_16", fmt=None, rate=44100):
    import numpy as np

    sf.write(str(path), np.zeros(rate // 10, dtype=np.float32), rate,
             format=fmt, subtype=subtype)
    return path


def add(player, path) -> None:
    player.add_tracks(
        [{"file_path": str(path), "display_name": Path(path).name}],
        allow_duplicates=True,
    )


def cell(player, row, col) -> str:
    return player._table.item(row, col).text()


class TestTheFormatLabel:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("a.mp3", "MP3"),
            ("a.wav", "WAV"),
            ("a.flac", "FLAC"),
            ("a.aiff", "AIFF"),
            ("a.WAV", "WAV"),
            ("a.b.flac", "FLAC"),
        ],
    )
    def test_it_is_the_extension_in_capitals(self, name, expected):
        assert _format_label(f"/music/{name}") == expected

    @pytest.mark.parametrize("name", ["a.aif", "a.aifc"])
    def test_the_other_spellings_of_aiff_read_as_aiff(self, name):
        """The column says what the *format* is, not which three letters this
        particular file happened to be named with — and "AIF" beside "AIFF"
        in a sort reads as two formats when there is one."""
        assert _format_label(f"/music/{name}") == "AIFF"

    def test_a_file_with_no_extension_is_blank_rather_than_a_guess(self):
        assert _format_label("/music/untitled") == ""

    def test_every_measured_label_is_one_a_real_file_can_produce(self):
        """`_FORMAT_LABELS` is what the column is sized against, so a label in
        it that nothing produces makes the column wider than it needs to be —
        and one that is missing makes it too narrow, silently."""
        from src.gui.widgets.drop_zone import AUDIO_EXTENSIONS

        produced = {_format_label(f"x{ext}") for ext in AUDIO_EXTENSIONS}
        assert produced == set(_FORMAT_LABELS)


class TestFormatNeedsNothingButThePath:
    def test_it_shows_for_a_file_that_was_never_opened(self, player, qtbot, tmp_path):
        """No tags, no library row, not even a real audio stream."""
        path = tmp_path / "silence.aiff"
        path.write_bytes(b"not really an aiff")
        add(player, path)
        qtbot.wait(10)

        assert cell(player, 0, FORMAT_COLUMN) == "AIFF"

    def test_it_follows_the_path_rather_than_being_stored(self, player, qtbot, tmp_path):
        """A derived value cannot drift. Renaming to another format is not
        something the app does on its own, but a relocate or a conversion
        moves an entry's path underneath it and the column must agree."""
        path = tmp_path / "a.wav"
        path.write_bytes(b"\0" * 64)
        add(player, path)
        qtbot.wait(10)
        entry = player._playlist[0]
        assert entry.file_type == "WAV"

        entry.file_path = str(tmp_path / "a.flac")

        assert entry.file_type == "FLAC"

    def test_a_missing_file_still_says_what_it_was(self, player, qtbot, tmp_path):
        path = tmp_path / "gone.mp3"
        path.write_bytes(b"\0" * 64)
        add(player, path)
        qtbot.wait(10)
        player.wait_for_readers()
        path.unlink()
        player._rebuild_table()

        assert cell(player, 0, FORMAT_COLUMN) == "MP3"


class TestWhichFilesHaveABitDepth:
    @pytest.mark.parametrize("name", ["a.wav", "a.flac", "a.aiff", "a.aif", "a.AIFF"])
    def test_the_lossless_containers_do(self, name):
        assert _has_bit_depth(f"/music/{name}")

    @pytest.mark.parametrize("name", ["a.mp3", "a.m4a", "a.ogg"])
    def test_the_lossy_ones_do_not(self, name):
        """Not "we failed to read it" — there is no such number. Which is
        what keeps the read in `add_tracks` bounded: it can only ever fire for
        a file that really has one, so it cannot become an open-per-row."""
        assert not _has_bit_depth(f"/music/{name}")

    def test_a_lossy_stream_reports_none(self):
        class Mp3Info:
            bitrate = 320000

        assert read_bit_depth(Mp3Info()) is None


class TestBitDepthComesOffTheFile:
    @pytest.mark.parametrize("subtype,expected", [("PCM_16", 16), ("PCM_24", 24)])
    def test_a_wav_reports_its_own(self, sf, tmp_path, subtype, expected):
        path = write_audio(sf, tmp_path / "a.wav", subtype=subtype)

        assert read_metadata(str(path)).bit_depth == expected

    def test_flac_too(self, sf, tmp_path):
        path = write_audio(sf, tmp_path / "a.flac", fmt="FLAC", subtype="PCM_24")

        assert read_metadata(str(path)).bit_depth == 24

    def test_and_aiff(self, sf, tmp_path):
        path = write_audio(sf, tmp_path / "a.aiff", fmt="AIFF", subtype="PCM_16")

        assert read_metadata(str(path)).bit_depth == 16


class TestWhatTheCellSays:
    def test_the_number_carries_the_word(self, player, qtbot, sf, tmp_path):
        add(player, write_audio(sf, tmp_path / "a.wav", subtype="PCM_24"))
        qtbot.wait(10)

        assert cell(player, 0, BIT_DEPTH_COLUMN) == "24 bit"

    def test_the_entry_keeps_the_bare_number(self, player, qtbot, sf, tmp_path):
        """The split that lets the value sort as a number and store as one,
        while the cell says it in whichever language is running."""
        add(player, write_audio(sf, tmp_path / "a.wav", subtype="PCM_24"))
        qtbot.wait(10)

        assert player._playlist[0].bit_depth == "24"

    def test_a_lossy_file_shows_nothing_at_all(self, player, qtbot, tmp_path):
        path = tmp_path / "a.mp3"
        path.write_bytes(b"\0" * 64)
        add(player, path)
        qtbot.wait(10)

        assert cell(player, 0, BIT_DEPTH_COLUMN) == ""

    def test_a_blank_depth_is_not_dressed_up_as_a_word(self, player):
        assert player._format_bit_depth("") == ""


class TestItIsRememberedRatherThanReRead:
    def test_the_library_row_keeps_it(self, player, qtbot, sf, tmp_path, lib):
        path = write_audio(sf, tmp_path / "a.flac", fmt="FLAC", subtype="PCM_24")
        add(player, path)
        qtbot.wait(10)

        assert lib.get_track_by_path(str(path)).bit_depth == 24

    def test_a_load_fills_a_row_that_predates_the_column(
        self, player, qtbot, sf, tmp_path, lib
    ):
        """The v8 upgrade path. The column is forward-only — a migration does
        not open a whole library's worth of files — so the value arrives the
        first time the playlist is opened, and is kept.

        The row is deliberately complete in every *other* field: an
        under-tagged one would be opened anyway for its key or its year, and
        would pass this test with no trigger for the depth at all. A
        well-tagged library is the case that needs one.
        """
        path = write_audio(sf, tmp_path / "a.wav", subtype="PCM_24")
        track_id = lib.add_track(
            str(path), artist="A", title="T", album="Al", genre="G",
            bpm=128.0, key="8A", comment="c", year="1997", track_number="3",
            label="L", bitrate=2116, duration=0.1,
        )
        node_id = lib.create_playlist("Set")
        lib.set_items(node_id, [track_id])
        assert lib.get_track(track_id).bit_depth is None

        player.load_node(node_id)
        qtbot.wait(10)

        assert lib.get_track(track_id).bit_depth == 24
        assert cell(player, 0, BIT_DEPTH_COLUMN) == "24 bit"

    def test_a_fully_known_row_opens_no_file(
        self, player, qtbot, sf, tmp_path, lib, monkeypatch
    ):
        """The point of storing it. A row that already answers every question
        must not be opened again — otherwise the column would cost one file
        open per row on every load of every playlist, forever."""
        path = write_audio(sf, tmp_path / "a.wav", subtype="PCM_24")
        track_id = lib.add_track(
            str(path), artist="A", title="T", album="Al", genre="G",
            bpm=128.0, key="8A", comment="c", year="1997", track_number="3",
            label="L", bitrate=2116, bit_depth=24, duration=0.1,
        )
        node_id = lib.create_playlist("Set")
        lib.set_items(node_id, [track_id])

        opens = []
        import src.metadata.tags as tags

        real = tags.read_metadata
        monkeypatch.setattr(
            tags, "read_metadata",
            lambda p, *a, **k: (opens.append(p), real(p, *a, **k))[1],
        )
        player.load_node(node_id)
        qtbot.wait(10)

        assert opens == []
        assert cell(player, 0, BIT_DEPTH_COLUMN) == "24 bit"

    def test_a_lossy_row_with_no_depth_opens_no_file_either(
        self, player, qtbot, tmp_path, lib, monkeypatch
    ):
        """The blank that is an answer. An MP3 never gains a bit depth, so a
        trigger that only asked "is it empty?" would re-open every lossy file
        in the library on every load and learn nothing — the same trap the
        label and track-number fields are kept out of the trigger for."""
        path = tmp_path / "a.mp3"
        path.write_bytes(b"\0" * 64)
        track_id = lib.add_track(
            str(path), artist="A", title="T", album="Al", genre="G",
            bpm=128.0, key="8A", comment="c", year="1997", bitrate=320,
            duration=0.1,
        )
        node_id = lib.create_playlist("Set")
        lib.set_items(node_id, [track_id])

        opens = []
        import src.metadata.tags as tags

        monkeypatch.setattr(
            tags, "read_metadata", lambda p, *a, **k: opens.append(p)
        )
        player.load_node(node_id)
        qtbot.wait(10)

        assert opens == []


class TestSorting:
    def add_all(self, player, qtbot, sf, tmp_path):
        for name, subtype, fmt in [
            ("c.flac", "PCM_24", "FLAC"),
            ("a.wav", "PCM_16", None),
            ("b.aiff", "PCM_32", "AIFF"),
        ]:
            add(player, write_audio(sf, tmp_path / name, subtype=subtype, fmt=fmt))
        qtbot.wait(10)

    def test_format_sorts_by_its_label(self, player, qtbot, sf, tmp_path):
        self.add_all(player, qtbot, sf, tmp_path)

        player._on_header_clicked(FORMAT_COLUMN)

        assert [e.file_type for e in player._playlist] == ["AIFF", "FLAC", "WAV"]

    def test_bit_depth_sorts_as_a_number_not_as_text(
        self, player, qtbot, sf, tmp_path
    ):
        """As text, "32" sorts before "8". The sort reads the entry's bare
        number, which is also why it is untouched by the cell's wording."""
        self.add_all(player, qtbot, sf, tmp_path)

        player._on_header_clicked(BIT_DEPTH_COLUMN)

        assert [e.bit_depth for e in player._playlist] == ["16", "24", "32"]


class TestTheyStartOff:
    def test_hidden_until_asked_for(self, player):
        assert player._table.isColumnHidden(FORMAT_COLUMN)
        assert player._table.isColumnHidden(BIT_DEPTH_COLUMN)

    def test_the_header_menu_offers_both(self, player, qtbot):
        menu = player._build_column_menu()
        qtbot.addWidget(menu)

        labels = [a.text() for a in menu.actions() if a.isCheckable()]

        assert {"Format", "Bit Depth"} <= set(labels)

    def test_revealing_one_shows_what_was_already_there(
        self, player, qtbot, sf, tmp_path
    ):
        add(player, write_audio(sf, tmp_path / "a.wav", subtype="PCM_16"))
        qtbot.wait(10)

        player._set_column_visible(BIT_DEPTH_COLUMN, True)

        assert not player._table.isColumnHidden(BIT_DEPTH_COLUMN)
        assert cell(player, 0, BIT_DEPTH_COLUMN) == "16 bit"


class TestNeitherEverClips:
    """Both hold a closed set of values, so "wide enough for anything this
    column can hold" has an answer — and `NoElideDelegate` means a value that
    outgrows its column loses its tail with nothing to admit it.

    Asserted through the style, never against a pixel count: the suite runs
    offscreen under Fusion with no stylesheet, so a number written here is a
    true statement about a table the app never paints.
    """

    @pytest.mark.parametrize("col", [FORMAT_COLUMN, BIT_DEPTH_COLUMN])
    @pytest.mark.parametrize("size", ["small", "medium", "large"])
    @pytest.mark.parametrize("reveal_first", [True, False])
    def test_it_fits_its_widest_value_at_every_text_size(
        self, player, qtbot, col, size, reveal_first
    ):
        if reveal_first:
            player._set_column_visible(col, True)
        player.set_text_size(size)
        if not reveal_first:
            player._set_column_visible(col, True)
        qtbot.wait(10)

        assert player._content_fit_widths[col] <= player._table.columnWidth(col), (
            f"{size}: column {col} is narrower than the widest value it holds"
        )

    @pytest.mark.parametrize("col", [FORMAT_COLUMN, BIT_DEPTH_COLUMN])
    def test_the_header_word_fits_too(self, player, qtbot, col):
        player._set_column_visible(col, True)
        qtbot.wait(10)

        header = player._table.horizontalHeader()
        assert header.sectionSizeHint(col) <= player._table.columnWidth(col)

    def test_the_widest_real_value_is_one_of_the_measured_ones(
        self, player, qtbot, sf, tmp_path
    ):
        """The measurement is only honest if the domain is complete: a value
        the column can hold but was never measured against is exactly the one
        that clips."""
        path = write_audio(sf, tmp_path / "a.flac", fmt="FLAC", subtype="PCM_24")
        add(player, path)
        qtbot.wait(10)
        player._set_column_visible(FORMAT_COLUMN, True)
        player._set_column_visible(BIT_DEPTH_COLUMN, True)
        qtbot.wait(10)

        assert player._playlist[0].file_type in _FORMAT_LABELS
        assert player._playlist[0].bit_depth in _BIT_DEPTHS
        # Bit Depth is measured from the widest *digit* rather than from that
        # list, so a depth nobody thought of (a 20-bit FLAC master) is covered
        # too — the list is only what a fixture can actually write.
        assert len(_widest_depth(player._table)) == 2
        for col in (FORMAT_COLUMN, BIT_DEPTH_COLUMN):
            assert player._table.sizeHintForColumn(col) <= player._table.columnWidth(col)
