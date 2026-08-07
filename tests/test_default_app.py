"""Becoming the default audio player — the parts that can be tested safely.

What is deliberately *not* here: any test that actually sets a handler. On
macOS that would reassign the developer's own file associations for real, and
on Windows the only writable route is a Settings page a human has to click.
So the tests cover the decisions around the OS calls — the guard that stops a
source checkout registering Python, which registry hive the deep link is
derived from, and the shape of the URL — and the calls themselves are covered
by the manual checklist.

The macOS write *was* verified by hand once, against the installed bundle
(2026-08-07), by snapshotting every handler, setting, and restoring. Worth
knowing before anyone tries to automate it: the change is **asynchronous**, so
the set-then-read-back that such a test would obviously do reports the old
handler and looks like a failure — and a set-then-restore in quick succession
races itself and leaves one type pointing at the wrong app. That is why this
stays manual and careful rather than becoming a fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.utils import default_app
from src.utils.default_app import Outcome

REPO = Path(__file__).resolve().parent.parent


def test_the_content_types_match_the_bundle_declaration():
    """LaunchServices refuses to make an app the handler for a type its bundle
    does not declare, so a type here that is missing from the spec is a silent
    no-op — the one failure mode this pairing has."""
    spec = (REPO / "mixedinp.spec").read_text()
    declared = spec.split("'LSItemContentTypes': [", 1)[1].split("]", 1)[0]
    for uti in default_app.CONTENT_TYPES:
        assert f"'{uti}'" in declared, f"{uti} is not in the spec's LSItemContentTypes"


def test_the_bundle_id_matches_the_spec():
    spec = (REPO / "mixedinp.spec").read_text()
    assert f"APP_BUNDLE_ID = '{default_app.APP_BUNDLE_ID}'" in spec


def test_the_windows_app_name_matches_the_installer():
    """The deep link's parameter is this exact string; the installer writes it
    under RegisteredApplications. They are one value in two files."""
    iss = (REPO / "installer.iss").read_text()
    assert 'ValueName: "{#MyAppName}"' in iss
    assert f'#define MyAppName "{default_app.WINDOWS_APP_NAME}"' in iss


def test_the_control_is_offered_only_where_there_is_a_route():
    assert default_app.available() is (sys.platform in ("darwin", "win32"))


# ── The deep link (Windows) ─────────────────────────────────────


def test_the_url_names_the_hive_the_registration_was_found_in():
    """An admin install is HKLM and wants registeredAppMachine; a per-user one
    is HKCU and wants registeredAppUser. Hardcoding either sends half the
    installs to a page that shrugs."""
    assert default_app.settings_url("Machine") == (
        "ms-settings:defaultapps?registeredAppMachine=Mixed%20in%20P"
    )
    assert default_app.settings_url("User") == (
        "ms-settings:defaultapps?registeredAppUser=Mixed%20in%20P"
    )


def test_the_space_in_the_name_is_encoded():
    """Verified working on Windows 11 in this exact form."""
    assert "%20" in default_app.settings_url("Machine")
    assert " " not in default_app.settings_url("Machine")


# ── The macOS guard ─────────────────────────────────────────────


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS LaunchServices")
class TestMacOS:
    def test_a_source_checkout_has_no_bundle_identifier(self):
        """The guard's whole basis: a bare python is not an app bundle."""
        assert default_app._bundle_id() is None

    def test_running_from_source_refuses_rather_than_registering_python(self):
        """Without this the developer's audio files would open in Python.app —
        a handler is named by bundle id, and ours is not the one running."""
        result = default_app.make_default()
        assert result.outcome is Outcome.UNSUPPORTED
        assert "com.mixedinp.app" in result.detail

    def test_it_refuses_even_when_a_bundle_id_is_present_but_not_ours(
        self, monkeypatch
    ):
        """The None case is the common one; a *wrong* id is the dangerous one,
        and the check is an equality against ours, not a None test."""
        monkeypatch.setattr(default_app, "_bundle_id", lambda: "org.python.python")
        assert default_app.make_default().outcome is Outcome.UNSUPPORTED

    def test_the_current_handler_is_readable(self):
        """The ctypes plumbing end to end, read-only: CoreServices resolves,
        the CFString round-trips, and a real UTI gives a real bundle id."""
        ls = default_app._launch_services()
        handler = default_app._current_handler(ls, "public.mp3")
        assert handler and "." in handler

    def test_an_unknown_type_has_no_handler_rather_than_raising(self):
        ls = default_app._launch_services()
        assert default_app._current_handler(ls, "com.example.nope") is None

    def test_is_default_answers_the_question(self):
        """False here, because this checkout is not an installed bundle — the
        point is that macOS *can* be asked, unlike Windows."""
        assert default_app.is_default() is False


@pytest.mark.skipif(sys.platform == "darwin", reason="the non-macOS answer")
def test_is_default_is_unknowable_off_macos():
    """Windows 11 reports the wrong answer confidently — assoc and UserChoice
    both named Windows Media Player while our exe was the one launching. None
    means "do not display a state", not "no"."""
    assert default_app.is_default() is None
