"""Duplicate handling for tracks added to a playlist.

One resolver for every add path in the app — the Player's file drops, sidebar
drops, Send To, Add Files/Folder, and the playlist tree's drag-to-add. All of
them ask this module which of the incoming files should actually land, and it
either answers immediately or puts the question to the user.

Two rules are load-bearing enough to state here:

**The box is never opened from inside a drop event.** Several callers reach
this from a ``dropEvent`` handler, where a modal fights Qt's drag machinery for
the mouse grab (the same trap the Player's moved-file warning hit). So the
answer arrives through a callback: synchronously when nothing needs asking,
and via a zero-delay timer when it does. Callers must therefore treat the add
as *pending*, not done, when this returns.

**The filter is applied against the list as it stands when the user answers**,
not as it stood when the box opened. Two quick drops can queue two prompts, and
the second one's view of the playlist is stale by the time it is answered. The
count quoted in the message is from open time — it is prose — but what lands is
re-diffed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QDialog, QMessageBox, QWidget

logger = logging.getLogger(__name__)

# Strings here live in module functions, not on a QObject, so there is no
# self.tr() to key them to a class — QCoreApplication.translate carries the
# context explicitly. The context MUST be a literal at every call: lupdate
# reads the source statically and silently extracts nothing from a variable.

# The three policies. Plain "#" comments, not "#:" — lupdate harvests a "#:"
# comment as an extracomment and would staple it onto the next translatable
# string as guidance for translators.
ADD = "add"  # add every incoming file, duplicates included
SKIP = "skip"  # drop any incoming file the playlist already holds
ASK = "ask"  # put it to the user (the default)


def current_policy() -> str:
    """The configured policy.

    The one place the setting is read, so callers don't each bind their own
    ``load_config`` — and so tests can pin the policy in a single patch
    instead of faking a whole AppConfig per call site.
    """
    from src.utils.config import load_config

    return load_config().duplicate_policy


def filter_new(incoming: Iterable[str], existing: Iterable[str]) -> list[str]:
    """The incoming paths that aren't in *existing*, order preserved.

    Repeats *within* ``incoming`` collapse too: a batch holding the same file
    twice contributes one copy, which is what "skip duplicates" has to mean for
    a multi-select drag that happens to contain a file twice.
    """
    seen = set(existing)
    out: list[str] = []
    for path in incoming:
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def resolve_additions(
    parent: QWidget | None,
    incoming: list[str],
    existing_provider: Callable[[], list[str]],
    playlist_name: str,
    on_resolved: Callable[[list[str]], None],
    policy: str | None = None,
) -> None:
    """Decide which of *incoming* to add, then hand the result to *on_resolved*.

    ``existing_provider`` is a callable rather than a list so the final diff
    reads the playlist as it is when the user answers — see the module note.
    ``on_resolved`` receives the paths to add, which may be empty (everything
    skipped). It is *not* called at all when the user abandons the prompt by
    closing its window, or if the widget dies before the prompt is answered.

    ``policy`` overrides the setting for callers that must not ask (loading a
    saved playlist). Left ``None`` it is read here rather than by the caller,
    deliberately: a call site doing ``from … import current_policy`` binds the
    function into its own module, and patching it for a test would then have no
    effect on that binding.

    Runs ``on_resolved`` synchronously whenever no question needs asking, so
    the common case keeps the straight-line behaviour callers had before.
    """
    if not incoming:
        on_resolved([])
        return

    if policy is None:
        policy = current_policy()

    if policy == ADD:
        on_resolved(list(incoming))
        return

    existing = existing_provider()
    if policy == SKIP:
        on_resolved(filter_new(incoming, existing))
        return

    # ASK — but only when there is something to ask about.
    collisions = len(incoming) - len(filter_new(incoming, existing))
    if collisions == 0:
        on_resolved(list(incoming))
        return

    def ask() -> None:
        choice = _prompt(parent, collisions, len(incoming), playlist_name)
        if choice is None:
            return  # Closed: nothing added, and no undo entry pushed
        if choice:
            on_resolved(list(incoming))
        else:
            # Re-diff: the playlist may have moved on while the box was open.
            on_resolved(filter_new(incoming, existing_provider()))

    # Zero delay, but off the current event: see the module note.
    QTimer.singleShot(0, ask)


# Horizontal room a button needs beyond its text: the stylesheet's
# ``padding: 8px 16px`` on QPushButton, its 1px border, and a little slack.
_BUTTON_CHROME = 44

# ``QDialogButtonBox QPushButton`` in the stylesheet, so a short label still
# gets a button of the same size as everywhere else in the app.
_BUTTON_MIN = 80


def _fit_buttons(box: QMessageBox) -> None:
    """Widen a message box's buttons to fit their own labels.

    The app stylesheet gives every QPushButton ``padding: 8px 16px`` but the
    native style computes the button's width without knowing about it, so a
    label longer than the 80px ``QDialogButtonBox`` minimum gets drawn into a
    contents rect narrower than the text — and QMessageBox centres rather than
    elides, so it is clipped at *both* ends ("kip Duplicate"). Every other box
    in the app uses short standard buttons, which is why this only shows up
    here.

    Measured from the text rather than pinned to a constant on purpose: these
    labels are translated, and a width that fits "Skip Duplicates" would clip
    a longer rendering of it in another language.
    """
    for button in box.buttons():
        # '&' is a mnemonic marker on some platforms, not a drawn glyph.
        label = button.text().replace("&", "")
        needed = button.fontMetrics().horizontalAdvance(label) + _BUTTON_CHROME
        button.setMinimumWidth(max(_BUTTON_MIN, needed))


class DuplicatePrompt(QMessageBox):
    """The Add / Skip box.

    A class rather than a plain function purely so its strings can go through
    ``self.tr()``: pyside6-lupdate marks ``%n`` as a plural form (``numerus``)
    for ``tr()`` but *not* for ``QCoreApplication.translate()``, so the
    module-function version silently shipped a string no translator could give
    proper plural forms for.
    """

    def __init__(
        self,
        parent: QWidget | None,
        collisions: int,
        total: int,
        playlist_name: str,
    ) -> None:
        super().__init__(parent)
        self.setIcon(QMessageBox.Icon.Question)
        self.setWindowTitle(self.tr("Duplicate Tracks"))
        # %n + the count argument is Qt's plural form; the playlist name is a
        # separate {0} because Qt substitutes %n but not {0}.
        self.setText(
            self.tr('%n track(s) are already in "{0}".', "", collisions).format(
                playlist_name
            )
        )
        self.setInformativeText(
            self.tr("Add them again, or skip them and add only the rest?")
            if collisions < total
            else self.tr("Add them again, or skip them?")
        )
        self._add_btn = self.addButton(
            self.tr("Add Duplicates"), QMessageBox.ButtonRole.AcceptRole
        )
        self._skip_btn = self.addButton(
            self.tr("Skip Duplicates"), QMessageBox.ButtonRole.RejectRole
        )
        # Skip is the default: it is the conservative answer and matches what
        # the app did before the prompt existed. It is also the lone
        # RejectRole button, so QMessageBox routes Esc to it with no
        # setEscapeButton call — which is why there is no Cancel here. Cancel
        # cost ~90px of width for an outcome the window's close box still
        # gives: that abandons the add entirely (``ask()`` returns None).
        self.setDefaultButton(self._skip_btn)
        _fit_buttons(self)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Closing the window abandons the add — it does not answer Skip.

        Measured: with no Cancel button QMessageBox detects the lone
        RejectRole button as its escape button, and its own ``closeEvent``
        then reports that button as clicked. That is right for Esc (a key
        wants a safe landing) and wrong for the close box, which means "I did
        not want this at all". Going straight to ``QDialog`` leaves
        ``clickedButton()`` null, so ``ask()`` returns None and nothing is
        added.
        """
        QDialog.closeEvent(self, event)

    def ask(self) -> bool | None:
        """True = add duplicates, False = skip them, None = abandoned.

        None is the close-box route: no button was clicked, so the caller adds
        nothing at all. Esc lands on Skip, not here.
        """
        self.exec()
        clicked = self.clickedButton()
        if clicked is self._add_btn:
            return True
        if clicked is self._skip_btn:
            return False
        return None


def _prompt(
    parent: QWidget | None, collisions: int, total: int, playlist_name: str
) -> bool | None:
    """Show the box and return its verdict. The seam tests patch."""
    return DuplicatePrompt(parent, collisions, total, playlist_name).ask()
