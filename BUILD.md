# Build Instructions

This project produces three distribution artifacts per release:

| Platform        | Artifact                  | How it's built                              |
|-----------------|---------------------------|---------------------------------------------|
| Windows         | `MixedInP-Setup.exe`      | PyInstaller + Inno Setup (`installer.iss`)  |
| macOS (Apple Silicon) | `MixedInP-mac-arm64.dmg`  | PyInstaller (`venv/`) → signed + notarized DMG |
| macOS (Intel)   | `MixedInP-mac-intel.dmg`  | PyInstaller (`venv-intel/`, Rosetta) → signed + notarized DMG |

All three are built from the same source — only the build environment differs.

## Filenames are version-less on purpose

The artifact names carry **no version number** — the version lives in the
GitHub release _tag_ (`v1.3.1`), not the filename. This keeps the
`releases/latest/download/` URLs stable forever, so the download buttons on the
site (and anywhere else) never break across releases:

```
https://github.com/jared-perez/mixed-in-p/releases/latest/download/MixedInP-Setup.exe
https://github.com/jared-perez/mixed-in-p/releases/latest/download/MixedInP-mac-arm64.dmg
https://github.com/jared-perez/mixed-in-p/releases/latest/download/MixedInP-mac-intel.dmg
```

When you cut a release, the three uploaded assets **must** be named exactly as
above. The Windows installer name is set by `OutputBaseFilename` in
`installer.iss`; the two mac DMGs are named by the `create-dmg` step in the
signing checklist (see below).

## macOS Apple Silicon build (native)

```bash
# Build (outputs dist/MixedInP.app)
./venv/bin/pyinstaller --noconfirm mixedinp.spec

# Verify it's arm64
file dist/MixedInP.app/Contents/MacOS/MixedInP
# expected: Mach-O 64-bit executable arm64
```

Then **sign, package into a DMG, notarize, and staple** — the full flow
(commands, certificate setup, and the per-build loop) lives in
`SIGNING-AND-NOTARIZATION.md`. The output is the signed, notarized
`MixedInP-mac-arm64.dmg` you upload to the release.

## macOS Intel build (from Apple Silicon Mac)

### One-time setup

```bash
# 1. Install Rosetta 2
softwareupdate --install-rosetta --agree-to-license

# 2. Install a separate Intel Homebrew (lives at /usr/local, alongside ARM brew at /opt/homebrew)
arch -x86_64 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 3. Install x86_64 Python 3.11
arch -x86_64 /usr/local/bin/brew install python@3.11

# 4. Create the Intel venv and install pinned deps
arch -x86_64 /usr/local/opt/python@3.11/bin/python3.11 -m venv venv-intel
arch -x86_64 ./venv-intel/bin/pip install --upgrade pip wheel
arch -x86_64 ./venv-intel/bin/pip install "numba==0.60.0" "llvmlite==0.43.0"
arch -x86_64 ./venv-intel/bin/pip install -r requirements.txt
```

Why the `numba` / `llvmlite` pins: newer versions dropped cp311 x86_64 macOS wheels, which forces a from-source build that needs CMake + LLVM. The pinned versions ship prebuilt x86_64 wheels and Just Work.

### Per-release build

```bash
arch -x86_64 ./venv-intel/bin/pyinstaller --noconfirm \
  --distpath dist-intel --workpath build-intel mixedinp.spec
```

Output: `dist-intel/MixedInP.app`

### Verify it's actually x86_64

```bash
file dist-intel/MixedInP.app/Contents/MacOS/MixedInP
# expected: Mach-O 64-bit executable x86_64
```

### Sign, package, notarize

Same flow as Apple Silicon — sign the `.app`, build the DMG, notarize, and
staple, per `SIGNING-AND-NOTARIZATION.md`, pointing the commands at
`dist-intel/MixedInP.app`. The output is `MixedInP-mac-intel.dmg`.

### Test the build locally

Just double-click `dist-intel/MixedInP.app`. macOS automatically runs it through Rosetta on Apple Silicon. This catches most Intel-specific issues — what it can't catch is real-Intel-hardware-only behavior (rare for Python apps).
