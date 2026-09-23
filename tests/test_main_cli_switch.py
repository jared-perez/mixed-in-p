"""`python -m src.main --cli …` runs the CLI with the rest of the arguments.

--cli picks the mode in src.main and is not an argument the CLI knows. It
used to be passed through, and argparse refused every command with
"unrecognized arguments: --cli" — only --help got past, because argparse
exits on it first. So these run a real command, never --help.
"""

import json
import sys

import pytest

from src import main as entry


@pytest.fixture
def wav(tmp_path):
    sf = pytest.importorskip("soundfile")
    import numpy as np

    t = np.linspace(0, 1.0, 44100, endpoint=False)
    path = tmp_path / "tone.wav"
    sf.write(str(path), (0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32"), 44100)
    return str(path)


@pytest.mark.parametrize("where", ["first", "after the command"])
def test_the_cli_switch_is_not_passed_to_the_cli(monkeypatch, capsys, wav, where):
    args = ["--cli", "analyze", wav, "-f", "json"]
    if where != "first":
        args = ["analyze", "--cli", wav, "-f", "json"]
    monkeypatch.setattr(sys, "argv", ["src.main", *args])

    with pytest.raises(SystemExit) as exit_info:
        entry.main()

    out, err = capsys.readouterr()
    assert "unrecognized arguments" not in err
    assert exit_info.value.code in (None, 0)  # sys.exit(None) is success
    assert "tone.wav" in json.dumps(json.loads(out))
