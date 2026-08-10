# Mixed in P

The full audio file preparation workflow for DJs.

![Mixed in P — Spectrum analyzer](docs/screenshots/spectrum.webp)

## Features

- Batch file renaming with undo
- Audio conversion (MP3/WAV/FLAC/AIFF) — quality is only ever kept or lowered, including same-format downgrades (96k/24-bit FLAC → 44.1k/16-bit FLAC)
- Acoustic spectrum analyzer
- Audio Player + Slicer for sample lifting
- Playlist library — folders, saved playlists, search across all of them, and export to `.m3u8`/`.m3u`/tracklist
- "Open with Mixed in P" from Finder or Explorer, and an option to become your default audio player
- Keyboard to play chords for key comparison
- BPM detection using beat tracking (librosa)
- Key detection using chroma analysis
- Energy level detection
- Auto-write metadata to file tags & Manual metadata editing
- Dark/Light modes and waveform color customization

## Install

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

## Run

```bash
python -m src.main
```

Or use the launcher scripts:
- Windows: `run_app.bat`
- macOS/Linux: `./run_app.sh`

## CLI

```bash
mixed-in-p analyze path/to/music/
mixed-in-p rename path/to/music/ --add-bpm --add-key
```

## Build

```bash
pip install pyinstaller
pyinstaller mixedinp.spec
```

Output: `dist/MixedInP/`

## Supported Formats

MP3, WAV, FLAC, AIFF, M4A, OGG

## License

MIT
