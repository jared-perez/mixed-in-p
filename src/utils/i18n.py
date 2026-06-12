"""Internationalization (i18n) support.

Single source of truth for the languages the app can be switched to. The
Settings language picker and the config validation both read from here, and the
startup translator loader (``src/gui/app.py``) uses the codes to find the
matching ``mixedinp_<code>.qm`` file.

Adding a language later is a drop-in: translate ``mixedinp_<code>.ts``, compile
it to ``.qm`` under ``src/gui/translations/``, and add one entry to
``LANGUAGES`` below. No other source changes are required.
"""

from __future__ import annotations

# (code, native display name). Order here is the order shown in the picker.
# "en" is the built-in source language and always available (no .qm needed).
#
# Shipping now (translations being authored): de es fr it pt_BR ru nl pl ja zh_CN ko
# Scaffolded for later (empty .ts/.qm to drop in): da nb sv tr uk vi zh_TW lt
LANGUAGES: list[tuple[str, str]] = [
    ("en", "English"),
    ("de", "Deutsch"),
    ("es", "Español"),
    ("fr", "Français"),
    ("it", "Italiano"),
    ("pt_BR", "Português (Brasil)"),
    ("ru", "Русский"),
    ("nl", "Nederlands"),
    ("pl", "Polski"),
    ("ja", "日本語"),
    ("zh_CN", "简体中文"),
    ("ko", "한국어"),
]

# Valid config values: every code above. "en" means "no translator installed".
LANGUAGE_CODES: set[str] = {code for code, _ in LANGUAGES}

DEFAULT_LANGUAGE = "en"


def native_name(code: str) -> str:
    """Return the native display name for a language code, or the code itself."""
    for c, name in LANGUAGES:
        if c == code:
            return name
    return code
