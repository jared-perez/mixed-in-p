"""Application entry point for the GUI."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QFile, QLibraryInfo, QTextStream, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .styles.theme import DEFAULT_THEME, THEMES, Theme
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
    """
    base = _get_base_path()
    template_path = base / "src" / "gui" / "styles" / "app.qss.template"
    if not template_path.exists():
        return ""
    qss = template_path.read_text(encoding="utf-8")
    for token, color in Theme.tokens().items():
        qss = qss.replace(f"@{token}@", color)
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


def create_app(argv: list[str] | None = None) -> tuple[QApplication, MainWindow]:
    """Create and configure the application.

    Args:
        argv: Command line arguments. If None, uses sys.argv.

    Returns:
        Tuple of (QApplication, MainWindow).
    """
    if argv is None:
        argv = sys.argv

    app = QApplication(argv)
    app.setApplicationName("Mixed in P")
    app.setOrganizationName("Mixed in P")
    app.setApplicationVersion("1.3.2")

    config = load_config()

    # Install translators before building any widgets so their strings localize.
    install_translators(app, config.language)

    # Apply the colour palette before importing/constructing widgets so their
    # paint-time and class-level Theme reads pick up the active theme. Changing
    # the theme takes effect on the next restart (like the language setting).
    Theme.apply(THEMES.get(config.theme, THEMES[DEFAULT_THEME]))

    # Import widgets only now (see module-level note on import ordering).
    from .main_window import MainWindow

    # Set application icon
    base = _get_base_path()
    icon_path = base / "src" / "gui" / "assets" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Apply stylesheet
    stylesheet = load_stylesheet()
    if stylesheet:
        app.setStyleSheet(stylesheet)

    # Create main window
    window = MainWindow()

    return app, window


def run_app(argv: list[str] | None = None) -> int:
    """Create and run the application.

    Args:
        argv: Command line arguments. If None, uses sys.argv.

    Returns:
        Application exit code.
    """
    import time
    t0 = time.perf_counter()

    # Set up logging first
    setup_logging()

    app, window = create_app(argv)
    window.show()

    elapsed = time.perf_counter() - t0
    logger = logging.getLogger(__name__)
    logger.info(f"Startup time: {elapsed:.2f}s")

    return app.exec()


if __name__ == "__main__":
    sys.exit(run_app())
