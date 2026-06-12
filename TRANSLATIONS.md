# Translations

Status, workflow, and review guide for Mixed in P's localized UI.

The app's GUI is translatable via Qt's native translation system. Language is
chosen in **Settings → Language** and applied on restart. Untranslated strings
always fall back to the English source, so a partly-translated language is safe
to ship.

- Engineering rules for translators/devs: see the **Internationalization (i18n)**
  section of [`CLAUDE.md`](CLAUDE.md) (what to wrap, what to keep in English,
  the term glossary).
- How the files are generated/compiled: see
  [`src/gui/translations/README.md`](src/gui/translations/README.md).

## Status

All 10 shipping languages are **fully populated — 287/287 strings, zero
untranslated** (confirmed by `build_translations.py`, which now reports any
English-fallback strings; see [Updating translations](#updating-translations)).
**These are machine-translation drafts** — consistent and glossary-compliant,
but **not yet native-reviewed**. Each carries `<translatorcomment>` notes
documenting the non-obvious decisions.

The **Notes** column is every `<translatorcomment>` (most document a *settled*
call, e.g. "kept `BPM` per glossary"). **To verify** is the subset whose comment
explicitly asks a native speaker to confirm an uncertain choice — **that's the
column that tells you where review effort actually goes.**

| Language | Code | Strings | Notes | To verify | Native review |
|----------|------|---------|-------|-----------|---------------|
| German | `de` | 287/287 | 49 | 0 | — no flags raised |
| Spanish | `es` | 287/287 | 28 | 0 | — no flags raised |
| French | `fr` | 287/287 | 11 | 0 | — no flags raised |
| Italian | `it` | 287/287 | 56 | 0 | ◑ linguistic pass done⁴ |
| Japanese | `ja` | 287/287 | 58 | 4 | ◑ linguistic pass done² |
| Dutch | `nl` | 287/287 | 33 | 1 | ◑ linguistic pass done⁴ |
| Polish | `pl` | 287/287 | 74 | 3 | ◑ linguistic pass done¹ |
| Portuguese (Brazil) | `pt_BR` | 287/287 | 51 | 1 | ◑ linguistic pass done⁴ |
| Russian | `ru` | 287/287 | 11 | 0 | — no flags raised |
| Chinese (Simplified) | `zh_CN` | 287/287 | 57 | 3 | ◑ linguistic pass done³ |
| **Total** | | | **428** | **12** | |

¹ **Polish** had a linguistic review pass (not a certified-native sign-off).
Fixed: localized `track`→`utwór` (declined) where keeping it English was
ungrammatical; `Ready`→`Gotowe` (impersonal). Accepted: genitive-plural count
forms (off for 1–4; correct fix needs Qt `%n` numerus — a code change deferred
by decision). The 3 remaining flags are genuine term-preference calls left for
a native: `Widmo` vs `Spektrum` (Spectrum, ×2) and `Bitrate` vs `Przepływność`.
Each reviewed string's `<translatorcomment>` now starts "Reviewed (pl pass):".

² **Japanese** had a linguistic review pass (not a certified-native sign-off).
No corrections were needed — Japanese doesn't decline or pluralize, so all
flagged strings were defensible translator choices; they were confirmed
(counters: 個 for file objects, 件 for case/action counts). The 4 remaining
flags are brand/term-preference calls for a native: `Jared P presents` (English
vs プレゼンツ), `Energy`→エナジー vs エネルギー, and `Spectrum`→スペクトラム vs
スペクトル (×2). Reviewed comments start "Reviewed (ja pass):".

³ **Chinese (Simplified)** had a linguistic review pass (not a certified-native
sign-off). No corrections needed — confirmed the compact-key 调 convention,
measure words (个 items / 首 music tracks), and standard terms (频谱). The 3
remaining flags are term-preference calls for a native: `{0} sessions`→会话
(vs 批次/记录 for a rename batch), `Eject`→弹出 (vs Apple's 推出), and
`Notation`→记号 (vs 表示法/记谱法). Reviewed comments start "Reviewed (zh pass):".

⁴ **Italian, Portuguese (BR), Dutch** had a linguistic review pass. Fixed: it
`click for more` "tocca"→"fai clic" (desktop app, not touch). Confirmed gender
agreement (it/pt_BR `Secondary to energy`, `ignorati`/`Annullati`/`Próxima`)
and Apple terms (pt_BR `playhead`→"cursor de reprodução"). Kept for a native:
pt_BR `Tempo Range`→"Faixa de tempo" (tempo vs. time ambiguity; cf. "andamento")
and nl `Conf`→"Betr." (could be misread as "Betreft"). it has 0 remaining.

**Where review effort goes:** every flagged language has now had a linguistic
pass; **de, es, fr, ru raised no flags at all.** The 12 remaining are all
deliberate term/brand-preference calls left for a native eye (pl 3, ja 4, zh 3,
pt_BR 1, nl 1) — no known errors remain. Separately, count strings across all
languages use a single-form fallback (awkward for some numbers) because the app
uses `.format("{0}")` rather than Qt `%n` plurals — a code-level limitation, not
a per-string translation error.

Scaffolded but not yet started (fall back to English): `da`, `nb`, `sv`, `tr`,
`uk`, `vi`, `zh_TW`, `lt`. Deferred (hard to source): `sc`, `eo`. The selectable
list lives in [`src/utils/i18n.py`](src/utils/i18n.py) (`LANGUAGES`).

## Term glossary (summary)

Full rules are in `CLAUDE.md`. In short:

- **Always English (all languages):** `BPM`, `beat tracking`, `Chroma`,
  harmonic key codes (1A–12B) and note names, audio formats (`WAV`, `MP3`,
  `FLAC`, `AIFF`, `M4A`, `OGG`), the product name "Mixed in P", and units
  (`dB`, `kHz`, `Hz`).
- **`sample` / `slicer`:** English for Latin-script languages (es, fr, it, nl,
  pt_BR, de); native script for non-Latin (ru: слайсер/сэмпл; ja: サンプル/
  スライサー; zh_CN: 采样/切片器).
- **`Send To`:** localized in every language (e.g. "Enviar a", "Senden an",
  "发送到").
- **"Sample Rate"** is the DSP term and IS translated (e.g. "Samplerate",
  "采样率") — distinct from the producer "sample".
- Action buttons use each language's UI-standard command form (infinitive /
  imperative / dictionary form per Apple's convention for that locale); feature
  labels use noun phrases.

## Reviewer checklist

Open a language in Qt Linguist and work through the flagged strings:

```bash
venv/bin/pyside6-linguist src/gui/translations/mixedinp_<code>.ts
```

The `<translatorcomment>` on a string is the reviewer's to-do for it. General
things to verify, and the languages where they matter most:

- **Plurals / counts** — the app uses Python `.format("{0}")`, **not** Qt's `%n`
  numerus mechanism, so multi-form plurals can't be expressed without code
  changes. Count strings use a single best-fit form. **Polish** uses a
  genitive-plural fallback (awkward for 1–4) — every count string is flagged.
- **Grammatical case / gender agreement** — **Polish**, **Russian**, **Italian**
  (past participles, adjective endings).
- **Script & measure words** — **Japanese** (katakana vs kanji; counters 個/件/
  トラック; キー vs 調性) and **Chinese** (Simplified-only; measure words 个/首;
  调性 vs 调; 曲目 vs 音轨).
- **Regional variant** — **pt_BR** must avoid pt_PT vocabulary (Arquivos not
  ficheiros; gerund "Analisando..." not "a analisar").
- **Width-constrained labels** — column headers and compact buttons may
  overflow; see the dedicated table below.
- **de/het articles** — **Dutch**: 3 necessary articles are flagged for review.

After edits, recompile and restart the app to see them:

```bash
python scripts/build_translations.py   # refresh all .ts, recompile all .qm
```

The script ends with an **untranslated-strings report** — per-language counts
plus the deduplicated source strings (with how many languages each is missing
in). If you confirmed a string in Linguist but it still shows here, it wasn't
marked **finished**. Run `--strict` to make the script exit non-zero when
anything is untranslated (useful as a pre-release / CI check):

```bash
python scripts/build_translations.py --strict
```

## Width-constrained labels

These labels live in narrow columns or compact controls where a longer
translation can overflow. **10 labels are width-sensitive; 8 actually expand
beyond the English in at least one language.** Verify these in the running app
during native review — widen the column or shorten the string as needed.

> Char counts compare to the English source. **CJK note:** ja/zh_CN usually have
> *fewer* characters, but each glyph is ~double-width, so a 2-char CJK label ≈ 4
> Latin widths — treat CJK as moderate, not safe.

| Label (en) | Where | Risk | Longest renderings |
|------------|-------|------|--------------------|
| `Key` (3) | Analysis column header | **High** — 8 langs expand | ru `Тональность` (11), pt_BR `Tonalidade` (10), es `Tonalidad` / nl `Toonsoort` (9), fr/it `Tonalité`/`Tonalità` (8), pl `Tonacja` (7), de `Tonart` (6) |
| `Prepend Text` (12) | Rename button | **High** — 8 langs | nl `Tekst vooraan toevoegen` (23), es `Añadir texto al principio` (25), pl `Dodaj tekst na początku` (23), ru `Добавить в начало` (17) |
| `Append Text` (11) | Rename button | **High** — 8 langs | nl `Tekst achteraan toevoegen` (25), es `Añadir texto al final` (21), pl `Dodaj tekst na końcu` (20), ru `Добавить в конец` (16) |
| `History` (7) | Sidebar nav button | Medium — 6 langs | nl `Geschiedenis` (12), fr `Historique` / it `Cronologia` (10), es `Historial` / pt_BR `Histórico` (9), pl `Historia` (8) |
| ` chars` (5) | Spinbox suffix | Medium — 7 langs | es/fr/pt_BR `caracteres`/`caractères` (10), it `caratteri` (9), de `Zeichen` (7) |
| `Conf` (4) | "Confidence" column (very narrow) | Medium — 4 langs | pl `Pewność` (7), de `Konf.` / nl `Betr.` / ru `Дост.` (5); es/fr/it/pt_BR keep `Conf` |
| `To` (2) | Conversion column header | Medium — 5 langs | de `Nach` / fr `Vers` / nl `Naar` / pt_BR `Para` (4), ja `変換先` (3) |
| `Vol` (3) | Volume control | Low/Med — 3 langs | pl `Głośność` (8), de `Lautst.` (7), ru `Громк.` (6); most keep `Vol` |
| `From` (4) | Conversion column header | Low — flagged, no expansion | all ≤ English (de `Von`, es `De`, pl `Z`, zh_CN `源`) |
| `Auto` (4) | Auto-analyze toggle | Low — flagged, no expansion | all keep `Auto` (or shorter CJK 自动) |

The real overflow danger is concentrated in **`Key`** and the
**`Prepend Text` / `Append Text`** buttons, which balloon to 8–25 characters
across the Latin-script languages. The narrow abbreviation columns (`Conf`,
`Vol`) are mostly handled, but Polish (`Pewność`, `Głośność`) and German
(`Lautst.`) couldn't be shortened cleanly and want a UI check.

## Updating translations

1. If you added/changed UI strings in code, wrap them per `CLAUDE.md`, then run
   `python scripts/build_translations.py` — `lupdate` extracts the new strings
   into every `.ts` (preserving existing translations), `lrelease` recompiles
   the `.qm`.
2. Translate the new/empty entries in Qt Linguist (mark each **finished** with
   `Ctrl+Enter`, or they won't compile in).
3. Run `python scripts/build_translations.py` again, check the untranslated
   report is clean, and restart the app.

> **Editing an existing string re-translates it, not just new ones.** Qt keys a
> translation by its exact source text, so changing a `tr()` string (even one
> character) breaks the key: `lupdate` marks the old translation `vanished` and
> re-adds the changed source as `unfinished`, dropping that string to **English
> in every language** until re-authored. The build report catches this. The old
> text survives in the string's `vanished` entry in each `.ts`, so an edit can
> usually be recovered and spliced rather than re-translated from scratch. To
> avoid the churn: settle English copy *before* translating, and keep
> translatable text in small, granular `tr()` strings (not one big block per
> screen) so an edit orphans only the part that changed.

To add a new language, add its `(code, native_name)` to `LANGUAGES` in
`src/utils/i18n.py`, then run the build script — no other code changes needed.
The `.qm` files are committed and bundled by `mixedinp.spec`, so a plain
checkout runs translated with no extra build step.
