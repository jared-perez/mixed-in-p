"""Becoming the *default* audio player, on the user's initiative only.

Two ideas that are easy to confuse, and the whole module hangs on the
difference:

- **Being *a* handler** — appearing in "Open with". That is ours to declare,
  and it is done at build/install time: ``CFBundleDocumentTypes`` in
  ``mixedinp.spec`` on macOS, the ``[Registry]`` block in ``installer.iss`` on
  Windows.
- **Being *the* default** — a double-click opens us. **Neither platform lets
  an app take this silently**, and neither should. Everything here runs
  because the user pressed a button in Settings, never at install or startup.

The asymmetry between the platforms is real and is not worth hiding:

- **macOS** has an API. ``LSSetDefaultRoleHandlerForContentType`` is one call
  per content type and the change is immediate, so the button does the thing.
  Reached through ``ctypes`` rather than PyObjC, which would be a heavy new
  dependency for what is two functions.
- **Windows** has none. Since Windows 8 the ``UserChoice`` key that records
  the decision is protected by an undocumented per-user hash; writing it
  directly does not merely fail — Windows resets the association and AV
  vendors treat the attempt as hijacking. Be sceptical of any snippet that
  claims otherwise. So the button opens the Settings page that already lists
  us as one grouped app (that grouping is what the installer's
  ``Capabilities`` block buys) and the user confirms there.

**The macOS write is asynchronous, and reads are cached per process.** Measured
2026-08-07 against the installed bundle: every call returned ``noErr``, the
handler really did change (it appeared in
``~/Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist``
and a *newly started* process saw it), and yet reading it back in the same
process that had just written it still reported the **old** handler, for
several seconds. Two consequences, both counter-intuitive enough to be worth
stating:

- **Never confirm a set by reading it back.** It would report failure for a
  change that worked. ``noErr`` is the only success signal available.
- A process that read a value before writing it keeps serving the stale one,
  so a read → set → read sequence in one process is meaningless. ``is_default``
  is honest at startup and unreliable after a ``make_default`` in the same run.

**There is no reliable "are we the default?" question on Windows 11.** Measured
2026-08-06: with our exe demonstrably launching as the handler, ``assoc .wav``
still said Windows Media Player, ``UserChoice`` said ZuneMusic, and
``UserChoiceLatest`` carried a hash and no ProgID at all. So ``is_default``
answers ``None`` there — unknowable — and the UI offers the action rather than
displaying a state that would be wrong. macOS can answer it honestly.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import sys
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from urllib.parse import quote

logger = logging.getLogger(__name__)

# The content types we set ourselves as the handler for. Must stay in step
# with ``LSItemContentTypes`` in mixedinp.spec: LaunchServices refuses to make
# an app the handler for a type its bundle does not declare, so an entry here
# that is missing there is a silent no-op.
CONTENT_TYPES = (
    "public.mp3",
    "com.microsoft.waveform-audio",
    "org.xiph.flac",
    "public.aiff-audio",
    "public.aifc-audio",
    "com.apple.m4a-audio",
    "public.mpeg-4-audio",
    "org.xiph.ogg-audio",
)

# Must match ``bundle_identifier`` in mixedinp.spec. Checked rather than
# assumed before anything is set — see _bundle_id.
APP_BUNDLE_ID = "com.mixedinp.app"

# The name the installer writes under RegisteredApplications, which is also
# what the Settings deep link takes as its parameter. Must match installer.iss.
WINDOWS_APP_NAME = "Mixed in P"

_REGISTERED_APPS = r"Software\RegisteredApplications"


class Outcome(Enum):
    """What pressing the button actually achieved."""

    DONE = "done"
    """Set. macOS only — nothing else can finish the job by itself."""

    HANDED_OFF = "handed_off"
    """The OS took over: Windows Settings is open on our entry."""

    UNSUPPORTED = "unsupported"
    """Nothing to do from here — running from source, or a platform with no
    route. The UI answers with the manual instructions."""

    FAILED = "failed"
    """A route that should have worked did not."""


@dataclass(frozen=True)
class Result:
    outcome: Outcome
    detail: str = ""
    """Why, in English, for the log. Never shown to the user — the panel picks
    a translated sentence from the outcome."""


def available() -> bool:
    """Whether to offer the control at all.

    True on the two platforms that have a route. A Linux build would show
    nothing rather than a button that can only apologise.
    """
    return sys.platform in ("darwin", "win32")


def is_default() -> bool | None:
    """Are we the default handler? ``None`` means unknowable, not "no".

    Only macOS can answer. See the module docstring for why Windows 11 cannot,
    and do not be tempted to read ``UserChoice`` — it reports the wrong answer
    confidently.

    Trustworthy at startup, **not** after ``make_default`` in the same process:
    LaunchServices serves this read from a per-process cache that a write does
    not invalidate.
    """
    if sys.platform != "darwin":
        return None
    ls = _launch_services()
    if ls is None:
        return None
    return all(_current_handler(ls, uti) == APP_BUNDLE_ID for uti in CONTENT_TYPES)


def make_default() -> Result:
    """Make Mixed in P the default audio player, or get as close as the OS allows."""
    if sys.platform == "darwin":
        return _macos_make_default()
    if sys.platform == "win32":
        return _windows_open_settings()
    return Result(Outcome.UNSUPPORTED, f"no route on {sys.platform}")


# ── macOS ───────────────────────────────────────────────────────


_UTF8 = 0x08000100
_ROLES_ALL = 0xFFFFFFFF


@lru_cache(maxsize=1)
def _core_foundation() -> ctypes.CDLL | None:
    lib = ctypes.util.find_library("CoreFoundation")
    if lib is None:  # pragma: no cover — not reachable on a Mac
        return None
    cf = ctypes.CDLL(lib)
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]
    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFStringGetCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_long,
        ctypes.c_uint32,
    ]
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    cf.CFBundleGetMainBundle.restype = ctypes.c_void_p
    cf.CFBundleGetIdentifier.restype = ctypes.c_void_p
    cf.CFBundleGetIdentifier.argtypes = [ctypes.c_void_p]
    return cf


@lru_cache(maxsize=1)
def _launch_services() -> ctypes.CDLL | None:
    lib = ctypes.util.find_library("CoreServices")
    if lib is None:  # pragma: no cover
        return None
    ls = ctypes.CDLL(lib)
    ls.LSCopyDefaultRoleHandlerForContentType.restype = ctypes.c_void_p
    ls.LSCopyDefaultRoleHandlerForContentType.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    ls.LSSetDefaultRoleHandlerForContentType.restype = ctypes.c_int32
    ls.LSSetDefaultRoleHandlerForContentType.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    return ls


def _cfstr(cf: ctypes.CDLL, text: str) -> int | None:
    """A CFString the caller must release. None if CoreFoundation refused."""
    return cf.CFStringCreateWithCString(None, text.encode("utf-8"), _UTF8)


def _pystr(cf: ctypes.CDLL, ref: int | None) -> str | None:
    if not ref:
        return None
    buf = ctypes.create_string_buffer(512)
    if not cf.CFStringGetCString(ref, buf, len(buf), _UTF8):
        return None
    return buf.value.decode("utf-8")


def _bundle_id() -> str | None:
    """The identifier of the bundle this process is running as, if any.

    ``None`` from a source checkout — a bare ``python`` has no main bundle
    identifier — and that is exactly the guard that matters here. Setting a
    default handler names a *bundle*, so without this check a developer run
    would hand every audio file on the machine to Python.app.
    """
    cf = _core_foundation()
    if cf is None:  # pragma: no cover
        return None
    main = cf.CFBundleGetMainBundle()
    if not main:
        return None
    return _pystr(cf, cf.CFBundleGetIdentifier(main))


def _current_handler(ls: ctypes.CDLL, uti: str) -> str | None:
    cf = _core_foundation()
    if cf is None:  # pragma: no cover
        return None
    ref = _cfstr(cf, uti)
    if not ref:  # pragma: no cover
        return None
    try:
        handler = ls.LSCopyDefaultRoleHandlerForContentType(ref, _ROLES_ALL)
        try:
            return _pystr(cf, handler)
        finally:
            if handler:
                cf.CFRelease(handler)
    finally:
        cf.CFRelease(ref)


def _macos_make_default() -> Result:
    running_as = _bundle_id()
    if running_as != APP_BUNDLE_ID:
        # Not a failure: it is the ordinary state of a source checkout, and
        # the panel answers it with the Finder instructions.
        return Result(Outcome.UNSUPPORTED, f"not running as {APP_BUNDLE_ID}: {running_as}")

    cf = _core_foundation()
    ls = _launch_services()
    if cf is None or ls is None:  # pragma: no cover
        return Result(Outcome.FAILED, "LaunchServices unavailable")

    ours = _cfstr(cf, APP_BUNDLE_ID)
    if not ours:  # pragma: no cover
        return Result(Outcome.FAILED, "could not build a CFString")

    failed: list[str] = []
    try:
        for uti in CONTENT_TYPES:
            ref = _cfstr(cf, uti)
            if not ref:  # pragma: no cover
                failed.append(uti)
                continue
            try:
                status = ls.LSSetDefaultRoleHandlerForContentType(ref, _ROLES_ALL, ours)
            finally:
                cf.CFRelease(ref)
            if status != 0:
                failed.append(f"{uti} (OSStatus {status})")
    finally:
        cf.CFRelease(ours)

    # No read-back verification on purpose. The change lands asynchronously and
    # this process's copy of the answer is stale for seconds afterwards, so a
    # confirming read would report failure for a set that worked. Verified by
    # hand against the installed bundle (2026-08-07); see the module docstring.
    if len(failed) == len(CONTENT_TYPES):
        return Result(Outcome.FAILED, "; ".join(failed))
    if failed:
        # A type this system has never heard of is a partial result, not a
        # failure: the user's mp3s and wavs open here now, which is what they
        # asked for. Worth a log line and nothing more.
        logger.info("Default handler not set for: %s", "; ".join(failed))
    return Result(Outcome.DONE)


# ── Windows ─────────────────────────────────────────────────────


def _registered_scope() -> str | None:
    """``"Machine"`` or ``"User"``, from where our registration actually is.

    The deep link's parameter name depends on it: an admin install puts the
    ``RegisteredApplications`` entry in HKLM (Inno's ``HKA``) and wants
    ``registeredAppMachine``; a per-user install puts it in HKCU and wants
    ``registeredAppUser``. Hardcoding either one sends half the installs to a
    Settings page that shrugs, so it is read rather than assumed.

    ``None`` means we are not registered at all — running from source, or an
    install that did not complete.
    """
    import winreg  # Windows-only, so imported where it is used, not at the top

    for root, scope in (
        (winreg.HKEY_LOCAL_MACHINE, "Machine"),
        (winreg.HKEY_CURRENT_USER, "User"),
    ):
        try:
            with winreg.OpenKey(root, _REGISTERED_APPS) as key:
                winreg.QueryValueEx(key, WINDOWS_APP_NAME)
            return scope
        except OSError:
            continue
    return None


def settings_url(scope: str) -> str:
    """The Settings deep link for a registration in *scope*.

    Verified on Windows 11 (2026-08-06): this lands on our own grouped entry,
    from which every declared type can be set on one screen.
    """
    return f"ms-settings:defaultapps?registeredApp{scope}={quote(WINDOWS_APP_NAME)}"


def _windows_open_settings() -> Result:
    scope = _registered_scope()
    if scope is None:
        return Result(Outcome.UNSUPPORTED, "no RegisteredApplications entry")

    url = settings_url(scope)
    try:
        # A fixed ms-settings URL built from our own constants, never user input.
        os.startfile(url)
    except OSError as exc:
        return Result(Outcome.FAILED, f"{url}: {exc}")
    return Result(Outcome.HANDED_OFF, url)
