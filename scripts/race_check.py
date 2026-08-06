#!/usr/bin/env python3
"""Launch N copies of the real app at once and check exactly one survives.

    python scripts/race_check.py [trials] [processes]

This is the check that kept catching what reasoning missed while "Open with
Mixed in P" was being built. Three separate designs for the single-instance
claim looked correct, passed their unit tests, and produced *every* process
electing itself primary the moment five of them started together. Both
platforms, different mechanisms, same result. So: run this, do not reason
about it.

**What this tests that a synthetic harness does not.** It launches the real
``src.main``, which means the winner spends roughly half a second building its
MainWindow **with no event loop running**, while the losers connect, write and
exit. A harness that stands in for the primary with a QObject and a timer has
its event loop running throughout and never reproduces that window — which is
the window where connections must survive un-accepted, and where a handoff
arrives long before ``files_received`` has anything connected to it.

Isolated from the developer's real library: the app data directory is
redirected per run, so ``library.db`` and ``config.json`` here are throwaway.

Reads as PASS only when exactly one process became primary AND every file
landed in Scratch. Both halves matter: one primary with four lost files is the
transport failing, and five primaries is the claim failing.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROOT = Path(tempfile.gettempdir()) / "mixedinp-race-check"
DATA = ROOT / "appdata"
SETTLE_SECONDS = 14


def make_fixtures(n: int) -> list[str]:
    import numpy as np
    import soundfile as sf

    if ROOT.exists():
        shutil.rmtree(ROOT, ignore_errors=True)
    DATA.mkdir(parents=True)
    sr = 44100
    files = []
    for i in range(n):
        # A space in the name on purpose: quoting is the classic failure here.
        p = ROOT / f"race track {i}.wav"
        sf.write(p, np.zeros((sr // 2, 2), dtype="float32"), sr)
        files.append(str(p))
    return files


def child_env() -> dict:
    """Redirect app data so a run cannot touch the developer's own library."""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(REPO)
    if sys.platform == "win32":
        env["APPDATA"] = str(DATA)
    else:
        env["HOME"] = str(DATA)
    return env


def app_data_dir() -> Path:
    if sys.platform == "win32":
        return DATA / "MixedInP"
    if sys.platform == "darwin":
        return DATA / "Library" / "Application Support" / "MixedInP"
    return DATA / ".local" / "share" / "MixedInP"


def scratch_paths() -> list[str]:
    db = app_data_dir() / "library.db"
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return [
            r[0]
            for r in con.execute(
                "SELECT t.path FROM tracks t "
                "JOIN playlist_items i ON i.track_id = t.id "
                "WHERE i.node_id = 1 ORDER BY i.position"
            )
        ]
    finally:
        con.close()


def classify(log: str) -> str:
    """What a process decided it was, read from its own output."""
    if "Startup time" in log:
        return "primary"
    if "Handed" in log and "running instance" in log:
        return "secondary"
    if "already running" in log or "did not respond" in log:
        return "failed-handoff"
    return "unknown"


def trial(files: list[str], n: int) -> bool:
    for leftover in app_data_dir().glob("library.db*"):
        leftover.unlink()

    procs, logs = [], []
    for i, f in enumerate(files):
        handle = open(ROOT / f"proc{i}.log", "wb")
        logs.append(handle)
        procs.append(
            subprocess.Popen(
                [sys.executable, "-m", "src.main", f],
                cwd=REPO,
                env=child_env(),
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
        )
    time.sleep(SETTLE_SECONDS)

    collected = scratch_paths()
    for p in procs:
        if p.poll() is None:
            p.terminate()
    for p in procs:
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
    for handle in logs:
        handle.close()

    roles = [classify((ROOT / f"proc{i}.log").read_text(errors="replace")) for i in range(n)]
    primaries = roles.count("primary")
    ok = primaries == 1 and len(collected) == n
    print(
        f"  primaries={primaries}  secondaries={roles.count('secondary')}  "
        f"collected={len(collected)}/{n}  {'OK' if ok else '<-- FAIL'}"
    )
    if not ok:
        print(f"     roles: {roles}")
        print(f"     landed: {[Path(p).name for p in collected]}")
    return ok


def main() -> int:
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    files = make_fixtures(n)
    print(f"{trials} trials of {n} concurrent launches, data in {DATA}\n")
    results = []
    for i in range(trials):
        print(f"trial {i + 1}:")
        results.append(trial(files, n))

    clean = sum(results)
    print(f"\n{clean} of {len(results)} trials clean")
    return 0 if clean == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
