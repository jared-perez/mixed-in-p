# Mixed in P — Diagrams

Two views of the app:

1. **Feature & workflow map** — for anyone learning what the app does and how
   files flow between its panels.
2. **Technical architecture** — for contributors: the code layers from entry
   point down to the audio libraries.

> This file supersedes the older diagram in
> `spitball/2026-05-29-app-structure.md`, which predates the embedded Player
> slicer and the Spectrum / Queue panels.

---

## 1. Feature & workflow map

How you move through the app. The **sidebar** is the hub: click a button to open
a panel, or drag selected rows onto a button to send files there. You can also
drop files straight from Finder/Explorer onto any panel.

```mermaid
flowchart TD
    files["🎵 Your audio files<br/>(drop from Finder / Explorer)"]

    files --> sidebar

    sidebar(["◧ Sidebar<br/>open a panel · or drag rows onto a button to route files"])

    subgraph organize["Organize"]
        queue["Queue<br/>staging area for analysis"]
        rename["Rename<br/>batch rename · live preview"]
        history["History<br/>undo past rename batches"]
    end

    subgraph understand["Understand"]
        analysis["Analysis<br/>BPM · key · energy · key codes"]
        spectrum["Spectrum<br/>frequency view"]
        keyboard["Keyboard<br/>piano + harmonic reference"]
    end

    subgraph transform["Transform"]
        convert["Convert<br/>WAV · FLAC · AIFF · MP3"]
        metadata["Metadata<br/>tags + artwork"]
        player["Player + Slicer<br/>audition · A–B loop · export samples"]
    end

    sidebar --> organize
    sidebar --> understand
    sidebar --> transform

    queue --> analysis
    rename -->|Send To| analysis
    rename -->|Send To| convert
    analysis -->|Send To| convert
    analysis -->|Send To| player
    convert -->|Send To| analysis
    convert -->|Send To| rename
    convert -->|Send To| player
    player <-->|drag via sidebar| transform

    rename -. Undo .- history
```

**Routing in plain terms**

- **Drop anywhere** — drag files from your file manager onto a panel to load
  them there.
- **Send To menus** — Rename can send to Analyze or Convert; Convert can send to
  Analyze, Rename, or Player; Analysis can send to Convert or Player.
- **Sidebar drag** — select rows in a panel and drop them on another panel's
  sidebar button to route them (some routes *move* the files, others *copy*).

---

## 2. Technical architecture

The code is layered: PySide6 panels at the top, background `QThread` workers
that keep the UI responsive, pure-Python backend domains, and the third-party
audio libraries underneath.

```mermaid
flowchart TD
    main["src/main.py<br/>entry point"]
    cli["src/cli.py<br/>--cli mode"]
    app["src/gui/app.py<br/>run_app() + QApplication"]
    mw["src/gui/main_window.py<br/>MainWindow — orchestrator"]

    main -->|GUI| app
    main -->|--cli| cli
    app --> mw

    mw --> header["header_bar.py<br/>logo + Add Files/Folder"]
    mw --> sidebar["sidebar.py<br/>nav + drag-drop routing"]
    mw --> panels

    subgraph panels["Panels — QStackedWidget (src/gui/widgets/)"]
        p1["queue · analysis · rename · convert"]
        p2["player (+ slice_section · slice_export ·<br/>loop_player · waveform_canvas)"]
        p3["metadata · spectrum · keyboard<br/>(linear_key_strip · hex_key_grid · key_info_box)"]
        p4["history · settings"]
    end

    panels --> workers
    panels --> backend
    cli --> backend

    subgraph workers["Background workers (QThread, src/gui/workers/)"]
        aw["analysis_worker"]
        cw["conversion_worker"]
        rw["rename_worker"]
        ww["waveform_worker"]
        adw["audio_decode_worker"]
        sw["spectrum_worker"]
    end

    subgraph backend["Backend domains (pure Python)"]
        analysis["analysis/<br/>analyzer · bpm · key · keycode · energy"]
        conversion["conversion/<br/>converter"]
        metadata["metadata/<br/>tags"]
        renamer["renamer/<br/>operations · preview · history"]
        utils["utils/<br/>config · app_dirs · i18n"]
    end

    aw --> analysis
    cw --> conversion
    rw --> renamer

    subgraph libs["External libraries"]
        librosa["librosa<br/>(BPM / key)"]
        soundfile["soundfile"]
        lameenc["lameenc<br/>(MP3)"]
        mutagen["mutagen<br/>(tags)"]
        sounddevice["sounddevice<br/>(keyboard + loop synth)"]
    end

    analysis --> librosa
    analysis --> soundfile
    conversion --> soundfile
    conversion --> lameenc
    metadata --> mutagen
    p2 --> sounddevice
    p3 --> sounddevice
```

**State & models** — `src/gui/models/`: a shared `TrackStore`
(`track_model.py`) backs the Queue/Analysis/Rename panels and emits
add/update/remove signals; `state.py` defines the track lifecycle
(QUEUED → PENDING → ANALYSING → ANALYSED / ERROR). The Convert panel keeps its
own independent file list.
