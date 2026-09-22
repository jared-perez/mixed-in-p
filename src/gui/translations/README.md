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

All eleven languages are shipping and fully translated: de, es, fr, it,
pt_BR, ru, nl, pl, ja, zh_CN, ko (see `LANGUAGES`). Missing translations fall
back to the English source string, so a partly-translated language is safe to
ship — but `python scripts/build_translations.py --strict` should stay clean.

## Why the glossary says what it says

The term rules themselves are in the repo's `CLAUDE.md` (Translation
glossary). These are the reasons, kept here so a translator doesn't undo them.

**`pipeline`** is the loanword in every Latin-script language, `пайплайн` in
ru, `potok` in pl and `流水线` in zh_CN. It shipped as "chain" in six languages
(es *cadena*, fr *chaîne*, it *catena*, pt_BR *cadeia*, ru *цепочка*, pl
*łańcuch*), which was wrong three ways: a chain is rigid links, losing the
liquid-through-a-pipe image the feature is named for; *cadena* and *catena*
read first as **assembly line**; and pt_BR *cadeia* colloquially means
**jail**. These languages' tech communities use "pipeline" untranslated
anyway, and the surf reading is decisive — Banzai Pipeline keeps its English
name everywhere, and the step toggle is the tsunami hazard sign, so
translating the word breaks the symbol. Two exceptions: pl `potok` is both the
established Polish CS term and literally a stream of water; zh_CN `流水线`
already reads "flowing-water line" (the surf pun cannot survive in Chinese, so
only *flow* is in play, and 管道 lacks it). ru's button is the noun
`Запуск пайплайна` rather than the infinitive because `Запустить пайплайн`
measures 164px against the button's 160px minimum.

**`stream`** is translated as an ordinary noun for a flowing ribbon of liquid
(de `Strom`, fr `flux`, ru `поток`, ja `流れ`, zh_CN `水流`), with its
"Backdrop" prefix done as its sibling menu entries do it (de `Hintergrund:`,
ru `Фон:`, ja `背景：`). The visual shipped as "Silly Scope", kept English as a
proper name and a pun on "oscilloscope". Renaming it retired the pun and with
it the only reason not to translate, so don't restore the English-everywhere
rule from the `vanished` entries or the old `<translatorcomment>`.

**The waveform colour modes** (Settings → Waveform / Visuals) are labelled
Solid · Loudness · Frequency bands · **Tone**, and the fourth is stored as
`centroid` — the id names the mechanism, so relabelling costs no migration.
"Tone" means *timbre*, dark to bright, never pitch (pitch is *key* in this
app). So it is `Ton` in de, `Тон` in ru and `音色` in ja/zh_CN/`음색` in ko,
but **`Timbre`/`Timbro` in es/fr/it/pt_BR**, where *tono/ton/tom* sit right
next to the words for key (*Tonalidad*, *Tonalité*, *Tonalità*,
*Tonalidade*); nl is `Klank` for the same reason (*Toonsoort*), and pl is
`Brzmienie` because *Barwa* also means colour, in a colour setting. The
normalisation pair is `This track` / `Fixed`; ru has `Единая` (one shared
scale) because a bare *фиксированный* reads as "stuck". "Use full-spectrum
colors" is a noun phrase in ru (`Цвета всего спектра`) to keep that row short;
it swaps the frequency modes' default (shades of the chosen colour) for the
whole hue range, so translate it as *all the colours*, never as a physics term.
