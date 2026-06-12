# Build Instructions

This project produces three distribution artifacts per release:

| Platform        | Artifact                          | How it's built                              |
|-----------------|-----------------------------------|---------------------------------------------|
| Windows         | `MixedInP-<ver>-setup.exe`        | PyInstaller + Inno Setup (`installer.iss`)  |
| macOS (Apple Silicon) | `MixedInP-<ver>-mac-arm.zip`      | PyInstaller in the normal `venv/`           |
| macOS (Intel)   | `MixedInP-<ver>-mac-intel.zip`    | PyInstaller in `venv-intel/` under Rosetta  |

All three are built from the same source — only the build environment differs.

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

### Package for distribution

```bash
ditto -c -k --sequesterRsrc --keepParent \
  dist-intel/MixedInP.app dist-intel/MixedInP-<version>-mac-intel.zip
```

Use `ditto` (not Finder's zip) — it preserves macOS metadata and extended attributes correctly, which matters for code signing and Gatekeeper.

### Test the build locally

Just double-click `dist-intel/MixedInP.app`. macOS automatically runs it through Rosetta on Apple Silicon. This catches most Intel-specific issues — what it can't catch is real-Intel-hardware-only behavior (rare for Python apps).
