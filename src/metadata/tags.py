"""Read and write audio file metadata tags using mutagen.

Provides a unified interface for reading and writing ID3/metadata tags
across different audio formats (MP3, FLAC, AIFF, M4A, etc.).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TrackMetadata:
    """Metadata extracted from an audio file."""

    artist: str | None = None
    title: str | None = None
    album: str | None = None
    bpm: float | None = None
    key: str | None = None
    genre: str | None = None
    year: int | None = None
    track_number: int | None = None
    label: str | None = None  # record label / publisher (ID3 TPUB, Vorbis LABEL)
    comment: str | None = None
    artwork: bytes | None = None
    artwork_mime: str | None = None
    duration: float | None = None  # seconds

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "artist": self.artist,
            "title": self.title,
            "album": self.album,
            "bpm": self.bpm,
            "key": self.key,
            "genre": self.genre,
            "year": self.year,
            "track_number": self.track_number,
            "label": self.label,
            "comment": self.comment,
            "artwork": self.artwork,
            "artwork_mime": self.artwork_mime,
        }


def _get_first(tags: Any, key: str, default: str | None = None) -> str | None:
    """Get first value from a tag list."""
    if tags is None:
        return default
    value = tags.get(key)
    if value is None:
        return default
    if isinstance(value, list):
        return str(value[0]) if value else default
    return str(value)


def _parse_bpm(value: str | None) -> float | None:
    """Parse BPM from string, handling various formats."""
    if not value:
        return None
    try:
        # Handle "128.00" format
        return float(value)
    except ValueError:
        return None


def _parse_year(value: str | None) -> int | None:
    """Parse year from string or date."""
    if not value:
        return None
    try:
        # Handle "2023" or "2023-01-15" formats
        return int(value[:4])
    except (ValueError, TypeError):
        return None


def _parse_track_number(value: str | None) -> int | None:
    """Parse track number from string."""
    if not value:
        return None
    try:
        # Handle "5" or "5/12" formats
        if "/" in value:
            value = value.split("/")[0]
        return int(value)
    except (ValueError, TypeError):
        return None


def read_metadata(file_path: str) -> TrackMetadata:
    """Read metadata tags from an audio file.

    Supports MP3, FLAC, AIFF, M4A, OGG, and WAV formats.

    Args:
        file_path: Path to the audio file

    Returns:
        TrackMetadata with extracted tag values

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file format is not supported
    """
    try:
        from mutagen import File
        from mutagen.id3 import ID3
        from mutagen.easyid3 import EasyID3
    except ImportError:
        raise ImportError("mutagen is required for metadata operations. Install with: pip install mutagen")

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = path.suffix.lower()

    try:
        audio = File(file_path, easy=True)
    except Exception as e:
        raise ValueError(f"Could not read metadata from {file_path}: {e}")

    if audio is None:
        raise ValueError(f"Unsupported file format: {suffix}")

    try:
        metadata = _read_metadata_from(audio, file_path, suffix)
        try:
            if audio.info is not None:
                metadata.duration = float(audio.info.length)
        except Exception:
            pass
        return metadata
    finally:
        del audio


def _read_metadata_from(audio, file_path: str, suffix: str) -> TrackMetadata:
    """Extract metadata from an already-opened mutagen file object."""
    from mutagen.id3 import ID3

    # AIFF: mutagen's easy=True doesn't wrap to EasyID3 — tags use raw ID3
    # frame names (TPE1, TIT2, etc.) instead of easy keys (artist, title, etc.)
    if suffix in (".aif", ".aiff") and audio.tags is not None:
        id3_to_easy = {
            "TPE1": "artist",
            "TIT2": "title",
            "TALB": "album",
            "TCON": "genre",
            "TDRC": "date",
            "TRCK": "tracknumber",
            "TBPM": "bpm",
            "TKEY": "key",
            "TPUB": "label",
        }
        metadata = TrackMetadata()
        for frame_id, field in id3_to_easy.items():
            frame = audio.tags.get(frame_id)
            if frame is None:
                continue
            value = str(frame)
            if field == "artist":
                metadata.artist = value
            elif field == "title":
                metadata.title = value
            elif field == "album":
                metadata.album = value
            elif field == "genre":
                metadata.genre = value
            elif field == "date":
                metadata.year = _parse_year(value)
            elif field == "tracknumber":
                metadata.track_number = _parse_track_number(value)
            elif field == "bpm":
                metadata.bpm = _parse_bpm(value)
            elif field == "key":
                metadata.key = value
            elif field == "label":
                metadata.label = value
        # Read COMM frame for comment and APIC frame for artwork via dedicated loader
        try:
            from mutagen.aiff import AIFF as AIFFFile
            aiff = AIFFFile(file_path)
            try:
                if aiff.tags:
                    comm = aiff.tags.get("COMM::\x00\x00\x00")
                    if comm is None:
                        for tag_key in aiff.tags:
                            if tag_key.startswith("COMM"):
                                comm = aiff.tags[tag_key]
                                break
                    if comm:
                        metadata.comment = str(comm)

                    apic = _first_apic(aiff.tags)
                    if apic is not None:
                        metadata.artwork = apic.data
                        metadata.artwork_mime = apic.mime or "image/jpeg"
            finally:
                del aiff
        except Exception:
            pass
        return metadata

    # Extract common tags (works for MP3 EasyID3, FLAC, etc.)
    metadata = TrackMetadata(
        artist=_get_first(audio, "artist"),
        title=_get_first(audio, "title"),
        album=_get_first(audio, "album"),
        genre=_get_first(audio, "genre"),
        year=_parse_year(_get_first(audio, "date")),
        track_number=_parse_track_number(_get_first(audio, "tracknumber")),
    )

    # BPM - try multiple tag names
    bpm_value = _get_first(audio, "bpm") or _get_first(audio, "TBPM")
    metadata.bpm = _parse_bpm(bpm_value)

    # Key - try multiple tag names
    metadata.key = _get_first(audio, "key") or _get_first(audio, "initialkey")

    # Comment — try common tag names
    metadata.comment = _get_first(audio, "comment") or _get_first(audio, "description")

    # Label — Vorbis "label" (FLAC/OGG). MP3 (EasyID3) has no "label" key, so the
    # raw ID3 TPUB frame is read in the MP3 block below.
    metadata.label = _get_first(audio, "label")

    # For MP3, try reading raw ID3 tags for BPM, key, and comment if not found
    if suffix == ".mp3":
        try:
            id3 = ID3(file_path)
            try:
                if metadata.bpm is None:
                    tbpm = id3.get("TBPM")
                    if tbpm:
                        metadata.bpm = _parse_bpm(str(tbpm))
                if metadata.key is None:
                    tkey = id3.get("TKEY")
                    if tkey:
                        metadata.key = str(tkey)
                if metadata.label is None:
                    tpub = id3.get("TPUB")
                    if tpub:
                        metadata.label = str(tpub)
                if metadata.comment is None:
                    comm = id3.get("COMM::\x00") or id3.get("COMM::eng")
                    if comm is None:
                        for key in id3:
                            if key.startswith("COMM"):
                                comm = id3[key]
                                break
                    if comm:
                        metadata.comment = str(comm)

                apic = _first_apic(id3)
                if apic is not None:
                    metadata.artwork = apic.data
                    metadata.artwork_mime = apic.mime or "image/jpeg"
            finally:
                del id3
        except Exception:
            pass

    # FLAC artwork lives in Picture blocks, not tags
    if suffix == ".flac":
        try:
            from mutagen.flac import FLAC as FLACFile
            flac = FLACFile(file_path)
            try:
                pic = _first_flac_picture(flac)
                if pic is not None:
                    metadata.artwork = pic.data
                    metadata.artwork_mime = pic.mime or "image/jpeg"
            finally:
                del flac
        except Exception:
            pass

    return metadata


def _first_apic(tags) -> Any:
    """Return the first APIC frame from an ID3 tag store, preferring COVER_FRONT (type 3)."""
    if tags is None:
        return None
    apic_keys = [k for k in tags.keys() if k.startswith("APIC")]
    if not apic_keys:
        return None
    # Prefer COVER_FRONT (type 3)
    for k in apic_keys:
        frame = tags[k]
        if getattr(frame, "type", None) == 3:
            return frame
    return tags[apic_keys[0]]


def _first_flac_picture(flac) -> Any:
    """Return first FLAC Picture, preferring COVER_FRONT (type 3)."""
    pictures = getattr(flac, "pictures", None) or []
    if not pictures:
        return None
    for pic in pictures:
        if getattr(pic, "type", None) == 3:
            return pic
    return pictures[0]


def write_metadata(
    file_path: str,
    metadata: TrackMetadata,
    fields: list[str] | None = None,
) -> bool:
    """Write metadata tags to an audio file.

    Args:
        file_path: Path to the audio file
        metadata: Metadata to write
        fields: Optional list of field names to update. If None, updates all non-None fields.

    Returns:
        True if successful

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file format is not supported
    """
    logger.debug(f"write_metadata called for: {file_path}")
    logger.debug(f"  Fields to write: {fields}")
    logger.debug(f"  Metadata: {metadata.to_dict()}")

    try:
        from mutagen import File
        from mutagen.id3 import ID3, TBPM, TKEY, TIT2, TPE1, TALB, TCON, TDRC, TRCK, TPUB, APIC, ID3NoHeaderError
        from mutagen.easyid3 import EasyID3
    except ImportError:
        raise ImportError("mutagen is required for metadata operations. Install with: pip install mutagen")

    path = Path(file_path)
    if not path.exists():
        logger.error(f"File not found: {file_path}")
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = path.suffix.lower()
    logger.debug(f"File suffix: {suffix}")

    # Determine which fields to update
    if fields is None:
        fields = [k for k, v in metadata.to_dict().items() if v is not None]
    logger.debug(f"Fields to update: {fields}")

    try:
        audio = File(file_path, easy=True)
        logger.debug(f"Successfully opened file with mutagen")
    except Exception as e:
        logger.error(f"Could not open file for writing: {e}")
        raise ValueError(f"Could not open file for writing: {e}")

    if audio is None:
        raise ValueError(f"Unsupported file format: {suffix}")

    # Map our field names to easy-tag (Vorbis-comment / EasyID3) keys, used for
    # the non-MP3/AIFF formats (FLAC, OGG, …). Comment and artwork are handled
    # by their own paths and aren't listed here.
    field_mapping = {
        "artist": "artist",
        "title": "title",
        "album": "album",
        "genre": "genre",
        "year": "date",
        "track_number": "tracknumber",
        "bpm": "bpm",
        "key": "key",
        "label": "label",
    }

    # ID3 frame constructors for MP3/AIFF
    id3_frame_map = {
        "artist": lambda v: TPE1(encoding=3, text=v),
        "title": lambda v: TIT2(encoding=3, text=v),
        "album": lambda v: TALB(encoding=3, text=v),
        "genre": lambda v: TCON(encoding=3, text=v),
        "year": lambda v: TDRC(encoding=3, text=str(v)),
        "track_number": lambda v: TRCK(encoding=3, text=str(v)),
        "bpm": lambda v: TBPM(encoding=3, text=str(int(round(v)))),
        "key": lambda v: TKEY(encoding=3, text=v),
        "label": lambda v: TPUB(encoding=3, text=v),
    }

    if suffix in (".aif", ".aiff"):
        # AIFF embeds ID3 inside an IFF chunk — must use mutagen.aiff.AIFF
        # so tags are written inside the container, not prepended as raw ID3.
        del audio  # Release the easy-mode handle before opening AIFF-specific one
        from mutagen.aiff import AIFF as AIFFFile

        logger.debug(f"Writing tags via AIFF container for {suffix}...")
        try:
            aiff = AIFFFile(file_path)
            if aiff.tags is None:
                aiff.add_tags()
                logger.debug("Created new ID3 tags in AIFF container")

            for field in fields:
                value = getattr(metadata, field, None)
                if value is not None and field in id3_frame_map:
                    aiff.tags.add(id3_frame_map[field](value))
                    logger.debug(f"Set ID3 frame for {field} = {value}")

            if "artwork" in fields and metadata.artwork is not None:
                _apply_apic(aiff.tags, metadata.artwork, metadata.artwork_mime, APIC)
                logger.debug("Set APIC frame (%d bytes)", len(metadata.artwork))

            aiff.save()
            logger.info(f"Successfully saved AIFF tags to {Path(file_path).name}")
        except Exception as e:
            logger.error(f"Failed to write AIFF tags: {e}")
            raise
        finally:
            del aiff

    elif suffix == ".mp3":
        # MP3: use raw ID3 frames for reliable BPM/key writing
        del audio  # Release the easy-mode handle before opening raw ID3
        logger.debug("Writing all tags via raw ID3 for MP3...")
        try:
            try:
                id3 = ID3(file_path)
                logger.debug("Loaded existing ID3 tags")
            except ID3NoHeaderError:
                logger.debug("No ID3 header, creating new")
                id3 = ID3()

            for field in fields:
                value = getattr(metadata, field, None)
                if value is not None and field in id3_frame_map:
                    id3.add(id3_frame_map[field](value))
                    logger.debug(f"Set ID3 frame for {field} = {value}")

            if "artwork" in fields and metadata.artwork is not None:
                _apply_apic(id3, metadata.artwork, metadata.artwork_mime, APIC)
                logger.debug("Set APIC frame (%d bytes)", len(metadata.artwork))

            logger.debug("Saving ID3 tags...")
            id3.save(file_path)
            logger.info(f"Successfully saved ID3 tags to {Path(file_path).name}")
        except Exception as e:
            logger.error(f"Failed to write ID3 tags: {e}")
            raise
        finally:
            del id3
    else:
        # For other formats (FLAC, OGG, …) write via easy tags. Each field is
        # written independently: a format that can't store one (e.g. WAV has no
        # slot for most of these) just warns and the rest still save.
        logger.debug(f"Writing metadata for non-MP3 format: {suffix}")

        try:
            for field in fields:
                easy_key = field_mapping.get(field)
                value = getattr(metadata, field, None)
                if easy_key is None or value is None:
                    continue
                # bpm rounds to a whole number to match the ID3 path; other
                # numeric fields (year, track_number) just stringify.
                text = str(int(round(value))) if field == "bpm" else str(value)
                try:
                    logger.debug(f"Setting {easy_key} = {text}")
                    audio[easy_key] = text
                except Exception as e:
                    logger.warning(f"Failed to set {easy_key} tag for this format: {e}")

            logger.debug("Saving audio file...")
            audio.save()
            logger.info(f"Successfully saved metadata to {Path(file_path).name}")
        finally:
            del audio

        # FLAC artwork lives in Picture blocks — handled after the easy-mode save
        if suffix == ".flac" and "artwork" in fields and metadata.artwork is not None:
            try:
                from mutagen.flac import FLAC as FLACFile, Picture
                flac = FLACFile(file_path)
                try:
                    pic = Picture()
                    pic.type = 3  # COVER_FRONT
                    pic.mime = metadata.artwork_mime or "image/jpeg"
                    pic.desc = "Cover"
                    pic.data = metadata.artwork
                    # Populate width/height/depth from the image header so strict
                    # FLAC readers accept the picture (defaults are 0 otherwise).
                    dims = _image_dimensions(metadata.artwork)
                    if dims is not None:
                        pic.width, pic.height, pic.depth = dims
                    flac.clear_pictures()
                    flac.add_picture(pic)
                    flac.save()
                    logger.info("Wrote FLAC picture (%d bytes) to %s", len(metadata.artwork), Path(file_path).name)
                finally:
                    del flac
            except Exception as e:
                logger.warning("Failed to write FLAC picture: %s", e)

    logger.debug("write_metadata completed successfully")
    return True


def _apply_apic(tags, data: bytes, mime: str | None, APIC_cls) -> None:
    """Replace any existing APIC frames with a single COVER_FRONT frame."""
    if hasattr(tags, "delall"):
        tags.delall("APIC")
    else:
        for k in [k for k in list(tags.keys()) if k.startswith("APIC")]:
            del tags[k]
    tags.add(APIC_cls(
        encoding=3,
        mime=mime or "image/jpeg",
        type=3,  # COVER_FRONT
        desc="Cover",
        data=data,
    ))


def _image_dimensions(data: bytes) -> tuple[int, int, int] | None:
    """Return (width, height, color_depth_bpp) for PNG/JPEG cover art.

    Parses just the image header (no decoding, no Pillow dependency). Cover
    art is realistically always PNG or JPEG; returns None for anything else
    so the caller leaves the FLAC Picture's dimension fields at 0.
    """
    if not data:
        return None
    # --- PNG: 8-byte signature, then IHDR (width/height/bit-depth/color-type) ---
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 26 and data[12:16] == b"IHDR":
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        bit_depth = data[24]
        color_type = data[25]
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type, 1)
        return width, height, bit_depth * channels
    # --- JPEG: scan segments for a Start-Of-Frame (SOFn) marker ---
    if data[:2] == b"\xff\xd8":
        i = 2
        n = len(data)
        while i + 9 < n:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            # SOF0..SOF15 carry frame geometry; skip the non-SOF C4/C8/CC markers.
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                precision = data[i + 4]
                height = int.from_bytes(data[i + 5:i + 7], "big")
                width = int.from_bytes(data[i + 7:i + 9], "big")
                components = data[i + 9]
                return width, height, precision * components
            seg_len = int.from_bytes(data[i + 2:i + 4], "big")
            if seg_len < 2:
                break
            i += 2 + seg_len
    return None


def update_comment_with_energy(
    file_path: str,
    energy: int | None = None,
    fmt: str = "number_only",
    mode: str = "prepend",
    key: str | None = None,
    key_secondary_to_energy: bool = False,
) -> bool:
    """Write energy level and/or key into the Comment tag of an audio file.

    Pieces are joined with " - " (space-dash-space). If both ``key`` and
    ``energy`` are given, the prefix is "<key> - <energy>". The prefix is
    then combined with any existing comment per ``mode``:

      prepend → "<prefix> - <existing>"  (default; e.g. "8A - 6 - visit my webpage")
      append  → "<existing> - <prefix>"
      replace → "<prefix>"               (existing comment dropped)

    Args:
        file_path: Path to the audio file.
        energy: Energy level 1-10, or None to skip.
        fmt: "number_only" → "7", "with_label" → "Energy 7".
        mode: "prepend", "append", or "replace".
        key: Key string (e.g. "8A" or "Am") to prepend before energy, or None.

    Returns:
        True if successful (including the no-op case where energy and key
        are both None).
    """
    if energy is None and key is None:
        return True

    try:
        from mutagen import File
        from mutagen.id3 import ID3, COMM, ID3NoHeaderError
    except ImportError:
        raise ImportError("mutagen is required for metadata operations.")

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = path.suffix.lower()

    # Build the prefix (key, energy, or both joined with " - ").
    # Default order is "<key> - <energy>". With key_secondary_to_energy
    # the order flips to "<energy> - <key>".
    energy_part = (
        (f"Energy {energy}" if fmt == "with_label" else str(energy))
        if energy is not None else None
    )
    key_part = str(key) if key else None
    if key_secondary_to_energy:
        parts = [p for p in (energy_part, key_part) if p]
    else:
        parts = [p for p in (key_part, energy_part) if p]
    prefix = " - ".join(parts)

    # --- Read existing comment ---
    existing_comment = ""

    if suffix in (".aif", ".aiff"):
        from mutagen.aiff import AIFF as AIFFFile
        aiff = AIFFFile(file_path)
        try:
            if aiff.tags:
                comm = aiff.tags.get("COMM::\x00")
                if comm is None:
                    for key in aiff.tags:
                        if key.startswith("COMM"):
                            comm = aiff.tags[key]
                            break
                if comm:
                    existing_comment = str(comm)
        finally:
            del aiff
    elif suffix == ".mp3":
        try:
            id3 = ID3(file_path)
            try:
                comm = id3.get("COMM::\x00") or id3.get("COMM::eng")
                if comm is None:
                    for key in id3:
                        if key.startswith("COMM"):
                            comm = id3[key]
                            break
                if comm:
                    existing_comment = str(comm)
            finally:
                del id3
        except ID3NoHeaderError:
            pass
    else:
        # FLAC, WAV, OGG — use easy tags
        audio = File(file_path, easy=True)
        try:
            if audio and audio.tags:
                val = audio.tags.get("comment")
                if val:
                    existing_comment = str(val[0]) if isinstance(val, list) else str(val)
        finally:
            del audio

    # --- Compose new comment ---
    if mode == "replace" or not existing_comment:
        new_comment = prefix
    elif mode == "append":
        new_comment = f"{existing_comment} - {prefix}"
    else:  # prepend
        new_comment = f"{prefix} - {existing_comment}"

    # --- Write comment back ---
    if suffix in (".aif", ".aiff"):
        from mutagen.aiff import AIFF as AIFFFile
        aiff = AIFFFile(file_path)
        try:
            if aiff.tags is None:
                aiff.add_tags()
            aiff.tags.add(COMM(encoding=3, lang="\x00\x00\x00", desc="", text=[new_comment]))
            aiff.save()
        finally:
            del aiff
    elif suffix == ".mp3":
        try:
            id3 = ID3(file_path)
        except ID3NoHeaderError:
            id3 = ID3()
        try:
            id3.add(COMM(encoding=3, lang="eng", desc="", text=[new_comment]))
            id3.save(file_path)
        finally:
            del id3
    else:
        audio = File(file_path, easy=True)
        try:
            if audio is not None:
                audio["comment"] = new_comment
                audio.save()
        finally:
            del audio

    logger.info("Wrote comment tag '%s' to %s", new_comment, path.name)
    return True


def update_bpm_key(
    file_path: str,
    bpm: float | None = None,
    key: str | None = None,
) -> bool:
    """Convenience function to update just BPM and/or key.

    Args:
        file_path: Path to the audio file
        bpm: BPM value to write (or None to skip)
        key: Key value to write (or None to skip)

    Returns:
        True if successful
    """
    fields = []
    if bpm is not None:
        fields.append("bpm")
    if key is not None:
        fields.append("key")

    if not fields:
        return True

    metadata = TrackMetadata(bpm=bpm, key=key)
    return write_metadata(file_path, metadata, fields)


def delete_metadata_fields(file_path: str, fields: list[str]) -> bool:
    """Delete specific metadata tags from an audio file.

    Args:
        file_path: Path to the audio file.
        fields: List of field names to delete (e.g. ["artist", "bpm", "comment"]).

    Returns:
        True if successful.
    """
    if not fields:
        return True

    from mutagen import File
    from mutagen.id3 import ID3, ID3NoHeaderError

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = path.suffix.lower()

    # Mapping from our field names to ID3 frame IDs
    field_to_id3 = {
        "artist": "TPE1",
        "title": "TIT2",
        "album": "TALB",
        "genre": "TCON",
        "year": "TDRC",
        "track_number": "TRCK",
        "bpm": "TBPM",
        "key": "TKEY",
        "label": "TPUB",
        "comment": "COMM",
    }

    # Mapping from our field names to easy-tag keys
    field_to_easy = {
        "artist": "artist",
        "title": "title",
        "album": "album",
        "genre": "genre",
        "year": "date",
        "track_number": "tracknumber",
        "bpm": "bpm",
        "key": "key",
        "label": "label",
        "comment": "comment",
    }

    if suffix in (".aif", ".aiff"):
        from mutagen.aiff import AIFF as AIFFFile
        aiff = AIFFFile(file_path)
        try:
            if aiff.tags is None:
                return True
            for field in fields:
                if field == "artwork":
                    for k in [k for k in list(aiff.tags.keys()) if k.startswith("APIC")]:
                        del aiff.tags[k]
                    continue
                frame_id = field_to_id3.get(field)
                if frame_id is None:
                    continue
                if frame_id == "COMM":
                    # Remove all COMM frames
                    to_remove = [k for k in aiff.tags if k.startswith("COMM")]
                    for k in to_remove:
                        del aiff.tags[k]
                elif frame_id in aiff.tags:
                    del aiff.tags[frame_id]
            aiff.save()
        finally:
            del aiff

    elif suffix == ".mp3":
        try:
            id3 = ID3(file_path)
        except ID3NoHeaderError:
            return True
        try:
            for field in fields:
                if field == "artwork":
                    id3.delall("APIC")
                    continue
                frame_id = field_to_id3.get(field)
                if frame_id is None:
                    continue
                if frame_id == "COMM":
                    to_remove = [k for k in id3 if k.startswith("COMM")]
                    for k in to_remove:
                        del id3[k]
                elif frame_id in id3:
                    del id3[frame_id]
            id3.save(file_path)
        finally:
            del id3

    else:
        # FLAC, WAV, OGG — easy tags
        audio = File(file_path, easy=True)
        try:
            if audio is None or audio.tags is None:
                return True
            for field in fields:
                if field == "artwork":
                    continue  # handled separately below for FLAC
                easy_key = field_to_easy.get(field)
                if easy_key and easy_key in audio:
                    del audio[easy_key]
            audio.save()
        finally:
            del audio

        if suffix == ".flac" and "artwork" in fields:
            try:
                from mutagen.flac import FLAC as FLACFile
                flac = FLACFile(file_path)
                try:
                    flac.clear_pictures()
                    flac.save()
                finally:
                    del flac
            except Exception as e:
                logger.warning("Failed to clear FLAC pictures: %s", e)

    logger.info("Deleted tags %s from %s", fields, path.name)
    return True


def write_comment(file_path: str, comment: str) -> bool:
    """Write *comment* verbatim to the file's Comment tag.

    Unlike update_comment_with_energy(), this is a literal write with no
    energy/key composition — used by the inline editors (Metadata panel and the
    Player playlist) where the user types the exact comment they want. Handles
    AIFF/MP3 via ID3 COMM frames and FLAC/OGG/WAV via easy tags, releasing the
    mutagen handle so a later rename isn't blocked on Windows.
    """
    from mutagen import File
    from mutagen.id3 import ID3, COMM, ID3NoHeaderError

    suffix = Path(file_path).suffix.lower()

    if suffix in (".aif", ".aiff"):
        from mutagen.aiff import AIFF as AIFFFile

        aiff = AIFFFile(file_path)
        try:
            if aiff.tags is None:
                aiff.add_tags()
            aiff.tags.add(COMM(encoding=3, lang="\x00\x00\x00", desc="", text=[comment]))
            aiff.save()
        finally:
            del aiff
    elif suffix == ".mp3":
        try:
            id3 = ID3(file_path)
        except ID3NoHeaderError:
            id3 = ID3()
        try:
            id3.add(COMM(encoding=3, lang="eng", desc="", text=[comment]))
            id3.save(file_path)
        finally:
            del id3
    else:
        audio = File(file_path, easy=True)
        try:
            if audio is not None:
                audio["comment"] = comment
                audio.save()
        finally:
            del audio
    return True
