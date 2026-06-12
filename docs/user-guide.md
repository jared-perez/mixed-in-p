# Mixed in P — User Guide

**DJ Audio Analysis Toolkit** · v1.3.0 · [jaredperez.com](https://jaredperez.com)

Mixed in P analyzes your tracks for BPM, musical key, and energy, then helps you
organize, convert, tag, and audition your library — all in one compact
desktop app built for DJs.

---

## Table of contents

1. [What is Mixed in P](#what-is-mixed-in-p)
2. [Harmonic mixing in 60 seconds](#harmonic-mixing-in-60-seconds)
3. [Install & first run](#install--first-run)
4. [The interface at a glance](#the-interface-at-a-glance)
5. [Core workflows](#core-workflows)
6. [Moving files between panels](#moving-files-between-panels)
7. [Settings reference](#settings-reference)
8. [Keyboard shortcuts](#keyboard-shortcuts)
9. [Supported formats](#supported-formats)
10. [Harmonic key-code reference](#harmonic-key-code-reference)
11. [FAQ & troubleshooting](#faq--troubleshooting)

---

## What is Mixed in P

Mixed in P is a desktop app for DJs and producers that turns a folder of tracks
into a well-understood, well-organized library. Drop your files in and it
detects:

- **BPM** (tempo) with a confidence score,
- **Musical key**, shown as a harmonic **key code** (e.g. `8A`),
- **Energy level** (1–10), a quick feel for a track's intensity.

From there you can batch-rename files with the tempo and key baked into the
name, convert between lossless formats, edit tags and artwork, and audition or
slice tracks in the built-in player.

It runs on **Windows** and **macOS** (Apple Silicon and Intel).

> ![Mixed in P main window](screenshots/overview.png)
> *Placeholder — replace with a screenshot of the main window.*

---

## Harmonic mixing in 60 seconds

Two tracks sound good together when their keys are compatible. Remembering raw
key names (F# minor, D♭ major…) is awkward, so Mixed in P uses **key codes** — a
clock-face system where every key gets a number (1–12) and a letter (**A** for
minor, **B** for major).

**The rule of thumb:** a track mixes smoothly with any track that shares its
**number**, or sits **±1** on the same letter.

- Same number, swap letter — e.g. `8A` ↔ `8B` (relative minor/major).
- One step around the wheel — e.g. `8A` ↔ `7A` or `8A` ↔ `9A`.

So if your current track is `8A`, good next picks are `8B`, `7A`, or `9A`.

Prefer traditional note names or Traktor's Open Key format instead? Switch
notation any time in **Settings → Notation**. The full mapping is in the
[key-code reference](#harmonic-key-code-reference) below.

---

## Install & first run

Mixed in P ships as a ready-to-run download for each platform:

| Platform | Download | Notes |
|----------|----------|-------|
| **Windows** | `.exe` installer | Run the installer and launch from the Start menu. |
| **macOS (Apple Silicon)** | `.zip` (arm64) | Unzip, then drag the app to Applications. |
| **macOS (Intel)** | `.zip` (x86_64) | Unzip, then drag the app to Applications. |

On first launch on macOS you may need to right-click the app and choose **Open**
the first time, to clear Gatekeeper.

**First run, in three steps:**

1. Click **Add Files** or **Add Folder** in the header (or just drag files in).
2. Open the **Analysis** panel — your tracks analyze automatically.
3. Read the BPM and key code for each track, and take it from there.

---

## The interface at a glance

The window has three parts:

- **Header** — *Add Files* / *Add Folder* buttons and the About dialog.
- **Sidebar** (left) — switches between panels. It's also a routing target: drag
  selected rows from one panel and drop them onto another panel's button to send
  the files there.
- **Panel area** (center) — the active tool.

The panels:

| Panel | What it's for |
|-------|---------------|
| **Queue** | Staging area for files waiting to be analyzed. |
| **Analysis** | Detect BPM, key, and energy. |
| **Convert** | Convert between WAV, FLAC, AIFF, and MP3. |
| **Rename** | Batch-rename with live preview. |
| **Player** | Play, audition, and slice tracks (with the Waveform Loop Slicer). |
| **Metadata** | Edit tags and cover artwork. |
| **Keyboard** | 3-octave piano + harmonic reference grid. |
| **Spectrum** | Spek-style frequency view of a track. |
| **History** | Undo past rename batches. |
| **Settings** | Tempo range, notation, auto-rename, language, and more. |

See the [feature & workflow map](diagrams.md#1-feature--workflow-map) for how
files flow between these panels.

---

## Core workflows

### Analyze tracks

Drop files onto the **Analysis** panel and they analyze automatically. Each row
shows **BPM**, **key**, **key code**, **energy**, and confidence percentages for
BPM and key, plus a color-coded status (analyzing → analyzed, or red on error).

- **Auto toggle** (top-right) controls whether dropped files analyze instantly.
  With it off, files wait as *pending* and you trigger analysis with the
  **Analyze** button.
- **Cancel** stops a run in progress.
- Detected BPM and key can be **written back to the file's tags** automatically
  (see [Settings](#settings-reference)).
- Right-click a row to **Open File Location** or **Remove** it. **Clear Results**
  empties the table.
- Use **Send To** to push selected tracks to **Convert** or the **Player**.

> ![Analysis panel](screenshots/analysis.png)
> *Placeholder — Analysis results table.*

### Organize & batch-rename

The **Rename** panel rewrites many filenames at once, with a live before/after
preview.

- **Trim** a number of characters from the start and/or end of every name.
- **Prepend** or **Append** custom text (one or the other).
- **Remove underscores** — replaces `_` with spaces across all names.
- The preview highlights changes in green and flags **conflicts** (two files
  that would end up with the same name) in red. **Apply Rename** stays disabled
  until conflicts are resolved.
- **Undo Last** reverts the most recent batch; older batches can be undone from
  the [History](#core-workflows) panel.

You can also let analysis rename files for you automatically — see the naming
formats in [Settings](#settings-reference).

> ![Rename panel](screenshots/rename.png)
> *Placeholder — Rename preview with green/red status.*

### Convert formats

The **Convert** panel changes audio formats while preserving quality.

- Pick a **target format**: AIFF, WAV, FLAC, or MP3.
- For lossless targets, choose **sample rate** (96 / 48 / 44.1 / 32 kHz) and
  **bit depth** (32 / 24 / 16 / 8-bit). For MP3, choose a **bitrate** (128 / 192
  / 256 / 320 kbps).
- Sources must be **lossless** (WAV, FLAC, AIFF). Lossy files (MP3, M4A, OGG)
  are rejected as sources — you can't recover quality that isn't there.
- **Send To** moves converted output to Analyze, Rename, or the Player.

> ![Convert panel](screenshots/convert.png)
> *Placeholder — Convert panel with format options.*

### Edit metadata & artwork

Drop a single file onto the **Metadata** panel to view and edit its tags:
**Title, Artist, Album, Label, Genre, BPM, Key, Year, Track #, Comment**.

- Changes **save automatically** when you leave a field — there's no Save button.
- Add a missing field with the **Add field…** dropdown.
- Drop an image (or click **Add Artwork…**) to embed cover art; **Remove** clears
  it. **Eject** unloads the file.
- **Reload** re-reads the file from disk — use it to pick up tag changes made
  elsewhere (for example, edits you made inline in the Player playlist).

> ![Metadata panel](screenshots/metadata.png)
> *Placeholder — Metadata editor with artwork.*

### Play, audition & lift samples

The **Player** panel is a full playlist player with a built-in slicer.

- Transport: **Previous / Play-Pause / Stop / Next**, a click-or-drag **seek
  bar**, and a **volume** slider.
- The playlist shows filename, artist, title, BPM, key, comment, duration, and
  year. Double-click to play, drag rows to reorder, and right-click to open the
  file location, reload a track's tags from disk, or remove tracks. Column layout
  is remembered between sessions.
- **Edit tags inline:** slow-double-click a cell — click an already-selected row
  again, the way you rename in Finder/Explorer — to edit **Artist, Title, BPM,
  Key, Comment, or Year** directly in the playlist; changes save straight to the
  file. The **Edit Lock** toggle at the top-right of the panel turns inline
  editing on or off — it starts unlocked and remembers your choice between
  sessions, so you can lock the list to avoid accidental edits.
- A panel keeps showing the tags it loaded until you refresh it. **Right-click →
  Reload Metadata from File** in the Player (or **Reload** in the Metadata panel)
  re-reads the file from disk — handy after editing the same track in the other
  panel.
- The next track is pre-loaded in the background, so **Next** is instant.
- **Waveform Loop Slicer** (expand the section below the playlist): set start/end
  markers on the waveform, fine-tune with nudge controls, toggle an **A–B loop**,
  pick a format, and **export** the slice — ideal for lifting loops and samples.
  The waveform's color is configurable in **Settings**.

> ![Player with slicer](screenshots/player.png)
> *Placeholder — Player + Waveform Loop Slicer.*

### Keyboard & harmonic reference

The **Keyboard** panel is a 3-octave piano plus a harmonic reference.

- Click keys (or use your QWERTY keyboard) to play chords; **Z / X** shift the
  octave.
- Switch between **Minor** and **Major** chord modes.
- The **linear key strip** and **hex grid** light up to show a key's harmonic
  neighbors — click any segment to hear that key. The current notation
  (Key Codes / Traditional / Traktor Open Key) is shown top-right.

> ![Keyboard panel](screenshots/keyboard.png)
> *Placeholder — piano + hex harmonic grid.*

### Spectrum view

Drop a file onto the **Spectrum** panel to see a Spek-style spectrogram — time
across, frequency up, loudness as color — with a dynamic-range slider to adjust
sensitivity. Useful for spotting low-quality transcodes and frequency content at
a glance.

> ![Spectrum panel](screenshots/spectrum.png)
> *Placeholder — frequency spectrogram.*

---

## Moving files between panels

Mixed in P is built around moving files between tools without re-importing them.

- **Send To menus** — most panels have a *Send To* button:
  - Rename → Analyze, Convert
  - Convert → Analyze, Rename, Player
  - Analysis → Convert, Player
- **Sidebar drag** — select rows in a panel and drop them onto another panel's
  sidebar button. Depending on the route, files are **moved** (removed from the
  source) or **copied** (left in place). The button highlights when it's a valid
  drop target.
- **From your file manager** — dragging files in from Finder/Explorer always
  *adds* them to the destination.

---

## Settings reference

Open the **Settings** panel to configure:

- **Language** — the UI is available in many languages; *restart to apply* a
  language change.
- **Tempo range** — lowest and highest BPM (defaults 99–199). Narrowing this
  helps avoid half/double-tempo errors on electronic music.
- **After analysis** — independently toggle:
  - *Auto-analyze* dropped/sent files (on by default),
  - *Write BPM to tags* and *Write key to tags*,
  - *Auto-rename* files using your chosen naming format,
  - *Write key to comment* (with an option to put energy first).
- **Naming format** — choose how the tempo/key prefix or suffix is applied, e.g.
  `128 8A - Original_Name`, `8A 128 - Original_Name`, `8A - Original_Name`, or
  the suffix variants. This controls auto-rename only; manual Rename operations
  are unaffected.
- **Notation** — **Key Codes** (default), **Traditional** note names, or
  **Traktor Open Key**. Applied live across the app.
- **Waveform color** — the color of the full-length waveform in the Player. Pick
  one of the presets or choose a custom color; the change applies live.

All settings save instantly — there's no Save button.

---

## Keyboard shortcuts

| Keys | Action | Where |
|------|--------|-------|
| **Space** | Play / Pause | Player (when focused) |
| **Delete / Backspace** | Remove selected rows | Player, Rename, Analysis |
| **Z / X** | Shift octave down / up | Keyboard |
| **A–L, ;** | Play notes | Keyboard |
| **W E T Y U O P** | Play black-key notes | Keyboard |
| **S / Q / E** | Slice section controls | Player (slicer expanded) |

---

## Supported formats

| Task | Formats |
|------|---------|
| **Analyze** | MP3, WAV, FLAC, AIFF/AIF, M4A, OGG |
| **Play / audition** | MP3, WAV, FLAC, AIFF/AIF, M4A, OGG |
| **Edit metadata** | MP3, WAV, FLAC, AIFF/AIF, M4A, OGG |
| **Convert — from** | WAV, FLAC, AIFF (lossless only) |
| **Convert — to** | WAV, FLAC, AIFF, MP3 |

Converting *from* a lossy source (MP3, M4A, OGG) into a lossless format is
intentionally blocked — it can't restore lost quality.

---

## Harmonic key-code reference

| Code | Open Key | Minor key | Code | Open Key | Major key |
|------|----------|-----------|------|----------|-----------|
| 1A   | 6m       | G#m / A♭m | 1B   | 6d       | B         |
| 2A   | 7m       | D#m / E♭m | 2B   | 7d       | F# / G♭   |
| 3A   | 8m       | A#m / B♭m | 3B   | 8d       | C# / D♭   |
| 4A   | 9m       | Fm        | 4B   | 9d       | G# / A♭   |
| 5A   | 10m      | Cm        | 5B   | 10d      | D# / E♭   |
| 6A   | 11m      | Gm        | 6B   | 11d      | A# / B♭   |
| 7A   | 12m      | Dm        | 7B   | 12d      | F         |
| 8A   | 1m       | Am        | 8B   | 1d       | C         |
| 9A   | 2m       | Em        | 9B   | 2d       | G         |
| 10A  | 3m       | Bm        | 10B  | 3d       | D         |
| 11A  | 4m       | F#m / G♭m | 11B  | 4d       | A         |
| 12A  | 5m       | C#m / D♭m | 12B  | 5d       | E         |

The **Code** columns are the app's default key codes; the **Open Key** columns
show the same keys in Traktor Open Key notation.

**Compatible for mixing:** the same number (relative major/minor), or ±1 on the
same letter.

---

## FAQ & troubleshooting

**A file says "Lossy not allowed" in Convert.**
The source is an MP3, M4A, or OGG. Lossless conversion needs a lossless source
(WAV/FLAC/AIFF). Convert *to* MP3 is fine; converting *from* lossy *to* lossless
is blocked on purpose.

**The BPM looks half or double what I expect.**
Electronic tracks can read as 64 vs. 128, etc. Set a tighter **tempo range** in
Settings (e.g. 90–180) so detection stays in DJ-typical territory.

**The detected key seems off.**
Key detection reports a **confidence** score — low confidence means it's a
harder call. You can correct the key in the **Metadata** panel.

**I renamed files by mistake.**
Use **Undo Last** in the Rename panel, or open **History** to undo any recent
batch.

**My language change didn't take effect.**
Language applies on the next launch — restart the app.

---

*Mixed in P · © Jared P · MIT License · [jaredperez.com](https://jaredperez.com)*
