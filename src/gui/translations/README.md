# Translations

Qt translation files for Mixed in P. The app loads `mixedinp_<code>.qm` at
startup based on the language chosen in Settings (see
`src/gui/app.py:install_translators`). English is the source language and needs
no file.

The list of selectable languages lives in `src/utils/i18n.py` (`LANGUAGES`).

## Workflow to add or update a language

The one-step way (refreshes every `.ts` and recompiles every `.qm`):

```bash
python scripts/build_translations.py
```

Then translate the new/empty `<translation>` entries in the relevant
`mixedinp_<code>.ts` (open in Qt Linguist via `pyside6-linguist`, or
machine-translate then review) and run the script again to recompile.

To add a brand-new language, first add its `(code, native_name)` entry to
`LANGUAGES` in `src/utils/i18n.py`, then run the script. No other code changes
are needed — `mixedinp.spec` already bundles this whole directory.

The manual equivalent of the two steps, for reference:

```bash
pyside6-lupdate $(find src -name '*.py') -ts src/gui/translations/mixedinp_<code>.ts
pyside6-lrelease src/gui/translations/mixedinp_<code>.ts
```

## Status

- **Shipping:** de, es, fr, it, pt_BR, ru, nl, pl, ja, zh_CN — `.ts`+`.qm`
  generated and bundled. **es** has a representative sample translated as a
  proof of concept; the rest are scaffolded with empty entries (they fall back
  to English until filled in).
- **Scaffolded for later:** da, nb, sv, tr, uk, vi, zh_TW, lt
- **Deferred (hard to source):** sc, eo

Empty/missing translations always fall back to the English source string, so a
partly-translated language is safe to ship.
