"""The generated spin-box arrows, and the two places that must agree about them.

Left to the platform, QMacStyle draws a QSpinBox's stepper over the frame's
border box — it paints out the right edge (the focus ring stops where the
stepper starts) and its arrows are hairlines. Styling the sub-controls fixes
both, but styling ``::up-button`` stops Qt drawing any arrow, so we have to
supply one; a committed image cannot work because theme.py ships four palettes,
so it is drawn per palette at stylesheet load.

None of that is visible from here. The suite runs offscreen, which resolves to
Fusion, where the native stepper was already fine — a rendered assertion would
pass identically against the broken build. The pixels were ground-truthed by
hand against QMacStyle, QFusionStyle and QWindowsStyle. What IS worth holding
here is everything that would silently produce an EMPTY sub-control: a token
that never got substituted, a path Qt's CSS parser cannot read, and the two
independent statements of the padding that reserves room for the arrows.
"""

from __future__ import annotations

import re

import pytest

from src.gui.app import _SPIN_BEGIN, _SPIN_END, _apply_spin_arrows, load_stylesheet
from src.gui.styles.spin_arrows import ARROW_H, ARROW_W, arrow_urls


@pytest.fixture
def urls():
    made = arrow_urls("#ffffff", "#606060")
    assert made is not None, "the isolated app data dir should be writable"
    return made


def test_it_writes_all_four_arrows(urls):
    from pathlib import Path

    assert set(urls) == {"up", "down", "up_off", "down_off"}
    for path in urls.values():
        assert Path(path).is_file()


def test_the_off_pair_is_a_different_picture(urls):
    """A dimmed arrow, not the same file — a spin box at its limit still reads
    as a spin box, where `image: none` would leave an empty box."""
    from pathlib import Path

    assert urls["up"] != urls["up_off"]
    assert Path(urls["up"]).read_bytes() != Path(urls["up_off"]).read_bytes()


def test_it_writes_the_retina_siblings(urls):
    """Qt picks up the @2x/@3x file beside a stylesheet image on a scaled
    screen. Without them a Retina Mac gets a blurry 9x6 triangle."""
    from pathlib import Path

    one = Path(urls["up"])
    for scale in (2, 3):
        sibling = one.with_name(f"{one.stem}@{scale}x{one.suffix}")
        assert sibling.is_file()
        assert sibling.stat().st_size > one.stat().st_size


def test_the_paths_use_forward_slashes(urls):
    """Backslashes are escape characters to Qt's CSS parser, and the Windows
    app data dir sits under a user name that may well contain one."""
    for path in urls.values():
        assert "\\" not in path


def test_it_is_idempotent_and_bounded(urls):
    """Named after the colour, so a second launch reuses the files and a
    palette change writes new ones instead of leaving a stale picture."""
    from pathlib import Path

    before = {p: Path(p).stat().st_mtime_ns for p in urls.values()}
    again = arrow_urls("#ffffff", "#606060")
    assert again == urls
    assert {p: Path(p).stat().st_mtime_ns for p in again.values()} == before


def test_a_different_palette_gets_its_own_files(urls):
    other = arrow_urls("#101010", "#909090")
    assert other is not None
    assert other["up"] != urls["up"]


# ------------------------------------------------------------ the stylesheet


def test_every_image_url_in_the_stylesheet_resolves():
    """The strongest form of the check, and the one that catches both ways this
    breaks: an @TOKEN@ that was never substituted, and a path Qt cannot read.
    Either leaves a styled sub-control with no image, which draws NOTHING — an
    empty box, read as a placeholder rather than as damage."""
    from pathlib import Path

    qss = load_stylesheet()
    urls = re.findall(r'image:\s*url\("([^"]*)"\)', qss)
    assert urls, "the spin arrows should be referenced by url()"
    for url in urls:
        assert "@" not in url, f"unsubstituted token in {url!r}"
        assert Path(url).is_file(), f"missing image {url!r}"


def test_the_styled_rules_are_dropped_when_generation_fails(monkeypatch):
    """Falling back to the platform stepper is worse-looking on macOS; falling
    back to a styled button with no image is an empty box. It must be the
    former, so the whole block goes."""
    monkeypatch.setattr("src.gui.styles.spin_arrows.arrow_urls", lambda *a: None)
    template = (
        "QSpinBox { padding-right: 34px; }\n"
        f"{_SPIN_BEGIN}\n"
        "QSpinBox::up-button {{ width: 15px; }}\n"
        "QSpinBox::up-arrow { image: url(\"@SPIN_ARROW_UP@\"); }\n"
        f"{_SPIN_END}\n"
        "QLabel { color: red; }\n"
    )
    out = _apply_spin_arrows(template)
    assert "up-button" not in out
    assert "SPIN_ARROW" not in out
    assert "QSpinBox { padding-right: 34px; }" in out
    assert "QLabel { color: red; }" in out


def test_the_arrow_box_matches_the_generated_image():
    """The QSS states the triangle's size; spin_arrows.py draws it. Two records
    of one fact, so they are compared rather than kept in step by hand."""
    qss = load_stylesheet()
    block = qss[qss.index("QSpinBox::up-arrow"):]
    assert re.search(rf"width:\s*{ARROW_W}px", block)
    assert re.search(rf"height:\s*{ARROW_H}px", block)


def test_settings_reserves_the_same_arrow_room_as_the_app_sheet(qtbot):
    """The Settings panel restates QSpinBox padding in its own stylesheet, so
    it also restates the room the arrows need. A panel-level rule that keeps
    only the app sheet's left padding puts the arrows on top of the number —
    and nothing else in the app would notice.
    """
    from src.gui.widgets.settings_panel import SettingsPanel

    app_sheet = load_stylesheet()
    app_pad = re.search(
        r"QSpinBox, QDoubleSpinBox \{[^}]*?padding-right:\s*(\d+)px", app_sheet, re.S
    )
    assert app_pad, "the app sheet should reserve room on the right"

    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel_pad = re.search(
        r"QSpinBox \{[^}]*?padding:\s*\d+px\s+(\d+)px", panel.styleSheet(), re.S
    )
    assert panel_pad, "the Settings QSpinBox rule should state a right padding"
    assert panel_pad.group(1) == app_pad.group(1)
