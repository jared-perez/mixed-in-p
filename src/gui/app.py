"""Application entry point for the GUI."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QFile,
    QLibraryInfo,
    QTextStream,
    QTranslator,
)
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .file_open_relay import FileOpenRelay
from .single_instance import SingleInstance
from .styles.theme import DEFAULT_THEME, THEMES, Theme
from ..utils.args import parse_audio_args
from ..utils.config import load_config

# NOTE: widget modules (via .main_window) are imported lazily inside
# create_app(), *after* Theme.apply(), because some widgets capture palette
# colours into module/class-level constants at import time. Importing them
# before the palette is applied would freeze them to the wrong theme.

logger = logging.getLogger(__name__)


def _get_base_path() -> Path:
    """Return the base path for bundled resources.

    When frozen by PyInstaller, resources are extracted to sys._MEIPASS.
    In development, use the project root (two levels up from this file).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent


def setup_logging():
    """Configure logging for the application."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    # Set debug level for our modules
    logging.getLogger('src.gui').setLevel(logging.DEBUG)
    logging.getLogger('src.metadata').setLevel(logging.DEBUG)
    logging.getLogger('src.renamer').setLevel(logging.DEBUG)


def load_stylesheet() -> str:
    """Render the QSS template against the active palette.

    The template (``app.qss.template``) holds at-sign-delimited palette token
    names instead of hex literals; each is substituted with the corresponding
    colour from :class:`Theme` (whichever palette is currently applied). A plain
    token replacement is used rather than ``str.format`` so Qt's own ``{ }``
    rule braces in the QSS pass through untouched.

    The spin-box arrows are the one token here that is not a colour: they are
    PNGs drawn in the active palette (see ``styles/spin_arrows.py``) and their
    paths are substituted the same way. If they cannot be written, the rules
    between the markers are dropped rather than left pointing at files that do
    not exist — a styled sub-control with a missing image draws nothing at all,
    where no rule at all gets the platform's own stepper back.
    """
    base = _get_base_path()
    template_path = base / "src" / "gui" / "styles" / "app.qss.template"
    if not template_path.exists():
        return ""
    qss = template_path.read_text(encoding="utf-8")
    qss = _apply_spin_arrows(qss)
    for token, color in Theme.tokens().items():
        qss = qss.replace(f"@{token}@", color)
    return qss


_SPIN_BEGIN = "/* @SPIN_ARROWS_BEGIN@ */"
_SPIN_END = "/* @SPIN_ARROWS_END@ */"


def _apply_spin_arrows(qss: str) -> str:
    """Fill in the generated arrow paths, or drop the rules that need them."""
    from .styles.spin_arrows import arrow_urls

    urls = arrow_urls(Theme.TEXT_PRIMARY, Theme.TEXT_DISABLED)
    if urls is None:
        start = qss.find(_SPIN_BEGIN)
        end = qss.find(_SPIN_END)
        if start == -1 or end == -1:
            return qss
        return qss[:start] + qss[end + len(_SPIN_END):]
    for token, key in (
        ("SPIN_ARROW_UP", "up"),
        ("SPIN_ARROW_DOWN", "down"),
        ("SPIN_ARROW_UP_OFF", "up_off"),
        ("SPIN_ARROW_DOWN_OFF", "down_off"),
    ):
        qss = qss.replace(f"@{token}@", urls[key])
    return qss


def install_translators(app: QApplication, language: str) -> None:
    """Install the app (and matching Qt base) translator for *language*.

    English ("en") is the source language and needs no translator. Missing or
    failed-to-load ``.qm`` files are non-fatal: Qt simply falls back to the
    English source strings. Translators are parented to *app* so they live for
    the application's lifetime.

    Switching language requires a restart — translators are only installed here
    at startup, before any widgets are built.
    """
    if not language or language == "en":
        return

    base = _get_base_path()
    translations_dir = base / "src" / "gui" / "translations"

    app_translator = QTranslator(app)
    if app_translator.load(f"mixedinp_{language}", str(translations_dir)):
        app.installTranslator(app_translator)
    else:
        logger.info("No translation file for language '%s'; using English.", language)

    # Localize Qt's own standard strings (dialog buttons, etc.) when available.
    qt_translator = QTranslator(app)
    qt_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if qt_translator.load(f"qtbase_{language}", qt_dir):
        app.installTranslator(qt_translator)


def create_qapplication(argv: list[str] | None = None) -> QApplication:
    """Build the QApplication and everything a widget needs to exist correctly.

    Split out from :func:`create_app` because the single-instance handshake in
    :func:`run_app` has to run *between* the two: a secondary process needs a
    QApplication (Qt's socket calls want an event dispatcher) but must exit
    before a ``MainWindow`` — and before ``library.db`` is opened.

    Args:
        argv: Command line arguments. If None, uses sys.argv.
    """
    if argv is None:
        argv = sys.argv

    app = QApplication(argv)
    app.setApplicationName("Mixed in P")
    app.setOrganizationName("Mixed in P")
    app.setApplicationVersion("1.5.0")

    config = load_config()

    # Install translators before building any widgets so their strings localize.
    install_translators(app, config.language)

    # Apply the colour palette before importing/constructing widgets so their
    # paint-time and class-level Theme reads pick up the active theme. Changing
    # the theme takes effect on the next restart (like the language setting).
    Theme.apply(THEMES.get(config.theme, THEMES[DEFAULT_THEME]))

    # Set application icon
    base = _get_base_path()
    icon_path = base / "src" / "gui" / "assets" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Apply stylesheet
    stylesheet = load_stylesheet()
    if stylesheet:
        app.setStyleSheet(stylesheet)

    return app


def create_app(argv: list[str] | None = None) -> tuple[QApplication, MainWindow]:
    """Create and configure the application.

    Args:
        argv: Command line arguments. If None, uses sys.argv.

    Returns:
        Tuple of (QApplication, MainWindow).
    """
    app = create_qapplication(argv)

    # Import widgets only now (see module-level note on import ordering).
    from .main_window import MainWindow

    window = MainWindow()

    return app, window


def _warn_handoff_failed(paths: list[str]) -> None:
    """Tell the user their files went nowhere, having refused to open twice.

    Reached only when another instance holds the single-instance server but
    cannot be reached through it. The tempting response — open a window
    anyway — is the one thing that must not happen: two processes with two
    connections to one ``library.db``, both auto-saving Scratch over each
    other, is a worse outcome than the files not opening. So this fails
    visibly instead, and the app exits non-zero.
    """
    from PySide6.QtWidgets import QMessageBox

    logger.error("Handoff to the running instance failed; %d file(s) not opened.",
                 len(paths))
    QMessageBox.warning(
        None,
        QCoreApplication.translate("run_app", "Mixed in P is already running"),
        QCoreApplication.translate(
            "run_app",
            "The running copy didn't respond, so those files weren't opened. "
            "Bring it to the front and add them there.",
        ),
    )


def run_app(argv: list[str] | None = None) -> int:
    """Create and run the application.

    Also the gate for "Open with Mixed in P": files named on the command line
    are parsed here, and this is where a launch decides whether it is the app
    or merely a courier for one that already exists.

    Args:
        argv: Command line arguments. If None, uses sys.argv.

    Returns:
        Application exit code.
    """
    import time
    t0 = time.perf_counter()

    # Set up logging first
    setup_logging()

    if argv is None:
        argv = sys.argv

    # Parsed before anything expensive: a secondary process does this, hands
    # the result over and exits without ever building a window.
    paths = parse_audio_args(argv)

    app = create_qapplication(argv)

    # Installed before MainWindow is built, because on macOS a QFileOpenEvent
    # can be delivered during startup and would otherwise be dropped.
    relay = FileOpenRelay(app)

    # Claim the instance server before MainWindow, whose constructor opens
    # library.db — a secondary must never make a second connection to it.
    instance = SingleInstance()
    if not instance.try_claim():
        if instance.send(paths):
            logger.info("Handed %d file(s) to the running instance.", len(paths))
            return 0
        _warn_handoff_failed(paths)
        return 1

    # Import widgets only now (see module-level note on import ordering).
    from .main_window import MainWindow

    window = MainWindow()
    instance.files_received.connect(window.open_files)
    relay.files_opened.connect(window.open_files)
    window.show()

    # Cold start: whatever the command line named. On macOS this is normally
    # empty and the files arrive through the relay instead.
    if paths:
        window.open_files(paths)
    # Both of these replay what arrived before there was a window to answer
    # it: the relay for a macOS QFileOpenEvent, the instance server for a
    # secondary that handed off during the claim — which, in a multi-select
    # race, is most of them.
    relay.go_live()
    instance.start_delivering()

    elapsed = time.perf_counter() - t0
    logger.info(f"Startup time: {elapsed:.2f}s")

    exit_code = app.exec()
    instance.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(run_app())
