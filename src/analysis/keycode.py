"""Harmonic key-code mapping for DJ mixing.

Key codes map musical keys to a grid (1A-12A for minor, 1B-12B for major)
to help DJs mix tracks harmonically. Compatible keys are:
- Same number (relative major/minor)
- ±1 on the same letter (adjacent key codes)
"""

# Map musical keys to key codes
# Minor keys map to 'A' codes, major keys to 'B' codes
KEY_TO_KEYCODE: dict[str, str] = {
    # Minor keys (A codes)
    "G#m": "1A", "Abm": "1A",
    "D#m": "2A", "Ebm": "2A",
    "A#m": "3A", "Bbm": "3A",
    "Fm": "4A",
    "Cm": "5A",
    "Gm": "6A",
    "Dm": "7A",
    "Am": "8A",
    "Em": "9A",
    "Bm": "10A",
    "F#m": "11A", "Gbm": "11A",
    "C#m": "12A", "Dbm": "12A",
    # Major keys (B codes)
    "B": "1B",
    "F#": "2B", "Gb": "2B",
    "C#": "3B", "Db": "3B",
    "G#": "4B", "Ab": "4B",
    "D#": "5B", "Eb": "5B",
    "A#": "6B", "Bb": "6B",
    "F": "7B",
    "C": "8B",
    "G": "9B",
    "D": "10B",
    "A": "11B",
    "E": "12B",
}

# Reverse mapping: key codes to canonical key names
KEYCODE_TO_KEY: dict[str, str] = {
    "1A": "Abm",
    "2A": "Ebm",
    "3A": "Bbm",
    "4A": "Fm",
    "5A": "Cm",
    "6A": "Gm",
    "7A": "Dm",
    "8A": "Am",
    "9A": "Em",
    "10A": "Bm",
    "11A": "F#m",
    "12A": "C#m",
    "1B": "B",
    "2B": "Gb",
    "3B": "Db",
    "4B": "Ab",
    "5B": "Eb",
    "6B": "Bb",
    "7B": "F",
    "8B": "C",
    "9B": "G",
    "10B": "D",
    "11B": "A",
    "12B": "E",
}


def normalize_key(key: str) -> str:
    """Normalize a musical key string for lookup.

    Handles variations like:
    - 'a minor' -> 'Am'
    - 'A Minor' -> 'Am'
    - 'A min' -> 'Am'
    - 'C major' -> 'C'
    - 'C maj' -> 'C'
    - 'f# minor' -> 'F#m'
    """
    key = key.strip()

    # Already in correct format
    if key in KEY_TO_KEYCODE:
        return key

    # Handle 'X minor' or 'X major' format
    key_lower = key.lower()

    # Check for minor
    for minor_suffix in [" minor", " min", "minor", "min"]:
        if key_lower.endswith(minor_suffix):
            root = key[: len(key) - len(minor_suffix)].strip()
            # Capitalize root note, preserve accidentals
            if len(root) >= 1:
                normalized = root[0].upper() + root[1:] + "m"
                if normalized in KEY_TO_KEYCODE:
                    return normalized

    # Check for major
    for major_suffix in [" major", " maj", "major", "maj"]:
        if key_lower.endswith(major_suffix):
            root = key[: len(key) - len(major_suffix)].strip()
            if len(root) >= 1:
                normalized = root[0].upper() + root[1:]
                if normalized in KEY_TO_KEYCODE:
                    return normalized

    # Try capitalizing first letter for simple keys like 'c' -> 'C' or 'am' -> 'Am'
    if len(key) >= 1:
        normalized = key[0].upper() + key[1:]
        if normalized in KEY_TO_KEYCODE:
            return normalized

    return key


def key_to_keycode(key: str) -> str:
    """Convert a musical key to its key code.

    Args:
        key: Musical key (e.g., 'Am', 'F#', 'Bbm', 'C major')

    Returns:
        key code (e.g., '8A', '2B', '3A', '8B')

    Raises:
        ValueError: If the key is not recognized
    """
    normalized = normalize_key(key)
    if normalized not in KEY_TO_KEYCODE:
        raise ValueError(f"Unknown key: {key}")
    return KEY_TO_KEYCODE[normalized]


def keycode_to_key(keycode: str) -> str:
    """Convert a key code to its musical key.

    Args:
        keycode: key code (e.g., '8A', '2B')

    Returns:
        Musical key (e.g., 'Am', 'Gb')

    Raises:
        ValueError: If the key code is not valid
    """
    keycode = keycode.upper().strip()
    if keycode not in KEYCODE_TO_KEY:
        raise ValueError(f"Invalid key code: {keycode}")
    return KEYCODE_TO_KEY[keycode]


def keycode_to_open_key(keycode: str) -> str:
    """Convert a harmonic key code to Traktor Open Key notation.

    Open Key uses 1-12 followed by 'd' (major) or 'm' (minor), anchored so that
    key code 8 maps to Open Key 1 (8B = C major = 1d, 8A = A minor = 1m).

    Args:
        keycode: key code (e.g., '8A', '2B')

    Returns:
        Open Key code (e.g., '1m', '9d')

    Raises:
        ValueError: If the key code is not valid
    """
    keycode = keycode.upper().strip()
    if keycode not in KEYCODE_TO_KEY:
        raise ValueError(f"Invalid key code: {keycode}")
    number = int(keycode[:-1])
    letter = keycode[-1]
    open_number = ((number - 8) % 12) + 1
    suffix = "d" if letter == "B" else "m"
    return f"{open_number}{suffix}"


def render_key(key: str, keycode: str, notation: str) -> str:
    """Render a key for display in the chosen notation.

    Single source of truth for turning a track's stored (key, keycode) pair into
    the string shown to the user / written to tags.

    Args:
        key: Traditional key name (e.g., 'Am')
        keycode: Harmonic key code (e.g., '8A')
        notation: One of 'traditional', 'open_key', or 'keycode'

    Returns:
        The key rendered in the requested notation, with graceful fallbacks.
    """
    if notation == "traditional":
        return key or keycode
    if notation == "open_key":
        if keycode:
            try:
                return keycode_to_open_key(keycode)
            except ValueError:
                pass
        return keycode or key
    return keycode or key


def get_compatible_keys(keycode: str) -> list[str]:
    """Get key codes that are harmonically compatible for mixing.

    Compatible keys are:
    - Same code (identical key)
    - Same number, different letter (relative major/minor)
    - ±1 with the same letter (adjacent key codes)

    Args:
        keycode: key code (e.g., '8A')

    Returns:
        List of compatible key codes, including the input

    Raises:
        ValueError: If the key code is not valid
    """
    keycode = keycode.upper().strip()
    if keycode not in KEYCODE_TO_KEY:
        raise ValueError(f"Invalid key code: {keycode}")

    # Parse the code
    number = int(keycode[:-1])
    letter = keycode[-1]
    other_letter = "B" if letter == "A" else "A"

    compatible = [keycode]

    # Same number, different letter (relative major/minor)
    compatible.append(f"{number}{other_letter}")

    # Adjacent key codes (±1, wrapping 12->1 and 1->12)
    prev_num = 12 if number == 1 else number - 1
    next_num = 1 if number == 12 else number + 1
    compatible.append(f"{prev_num}{letter}")
    compatible.append(f"{next_num}{letter}")

    return compatible
