# Mixed in P

The full audio file preparation workflow for DJs.

![Mixed in P — Spectrum analyzer](docs/screenshots/spectrum.webp)

## Features

- Batch file renaming with undo
- Audio conversion (MP3/WAV/FLAC/AIFF) — quality is only ever kept or lowered, including same-format downgrades (96k/24-bit FLAC → 44.1k/16-bit FLAC), writing beside each source or into a folder of your choosing, toggled per batch
- Pipeline — mark any of Rename, Convert and Analyze with its step toggle and one press runs a batch through the marked steps in order, filing each track into a playlist as it lands; start it from whichever marked panel you like, and pick an existing playlist or type a name and one gets made
- Acoustic spectrum analyzer
- Audio Player + Slicer for sample lifting, with a metronome beside them — tap tempo, time-bend, 2-decimal BPM, a choice of click (silent, tick, or a sharper beep), and a Global Click that keeps it sounding while you work on other panels
- Playlist library — folders, saved playlists, a name filter for the tree, search across every playlist at once, export to `.m3u8`/`.m3u`/tracklist, and Shift+Tab to show or hide the tree from anywhere
- Playlist view you can shape — cover art in the list (top / middle / full sleeve), optional Album, Genre, Track #, Label, Bitrate, Energy, Date Added, Date Created, Format and Bit Depth columns, a per-column Fit to Longest, and Small/Medium/Large text
- Compatible Tracks — what else in your library mixes with the track in the player, ranked by key, tempo (half- and double-time count) and energy, with click-and-hold preview
- "Open with Mixed in P" from Finder or Explorer, and an option to become your default audio player
- Keyboard to play chords for key comparison
- BPM detection using beat tracking (librosa)
- Key detection using chroma analysis
- Energy level detection — written to the comment, to its own tag field, or both
- Live analysis queue with per-track status, and a Cancel that keeps the results already in
- Freeze toggle — analyze and read the results without writing anything to your files
- Auto-write metadata to file tags & Manual metadata editing, with the full path of the file you're editing and a jump to it in Finder/Explorer
- Online lookup (opt-in) — fill in title, artist, album, label, genre, year, track number and cover art from Discogs, one file or a whole selection, with every value reviewed before anything is written, and the right pressing and track picked when there is more than one. Off by default; BPM, key and energy always come from your own analysis
- Remembers which Discogs release a file was tagged from, so a second look opens on the one you approved — and keeps that release on its own tab, offline, to read or apply a field at a time; plus a cover-only search for when the tags are already right
- Player visualizations — seven of them behind the playlist or in their own window, including a nebula tunnel that turns on the beat of the track it is playing, and a stream of liquid metal that carries the kick down its length
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
