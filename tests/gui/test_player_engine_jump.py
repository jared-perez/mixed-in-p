"""PlayerEngine's scheduled jump: the retrigger and loop start Mark on beat
times to a click happen inside the audio callback, at an exact frame.

The track is a ramp (sample value = frame index), so every output block says
exactly which frames were played and in what order.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from src.gui.widgets.player_engine import PlayerEngine

SR = 1000  # 1 frame per ms keeps the arithmetic readable
BLOCK = 100
NO_TIME = SimpleNamespace(currentTime=0.0, outputBufferDacTime=0.0)


@pytest.fixture
def engine(qtbot):
    eng = PlayerEngine()
    ramp = np.arange(10_000, dtype=np.float32)
    eng.load(np.stack([ramp, ramp], axis=1), SR)
    eng.set_volume(1.0)
    with eng._lock:
        eng._playing = True  # play() would open a real device
    yield eng
    with eng._lock:
        eng._playing = False


def block(engine):
    out = np.zeros((BLOCK, 2), dtype=np.float32)
    engine._callback(out, BLOCK, NO_TIME, None)
    return out[:, 0].astype(int).tolist()


def test_the_jump_happens_at_its_exact_frame(engine):
    engine.seek_ms(1_000)
    engine.schedule_jump_ms(1_030, 200)

    frames = block(engine)

    assert frames[:30] == list(range(1_000, 1_030))
    assert frames[30:] == list(range(200, 270))
    assert not engine.has_pending_jump()


def test_a_later_jump_waits_for_its_block(engine):
    engine.seek_ms(1_000)
    engine.schedule_jump_ms(1_250, 200)

    assert block(engine) == list(range(1_000, 1_100))
    assert engine.has_pending_jump()


def test_a_loop_start_turns_looping_on_at_the_jump(engine):
    engine.seek_ms(1_000)
    engine.set_loop_bounds(200, 250)
    engine.schedule_jump_ms(1_030, 200, enable_loop=True)

    frames = block(engine)

    assert frames[:30] == list(range(1_000, 1_030))
    assert frames[30:80] == list(range(200, 250))
    assert frames[80:] == list(range(200, 220)), "wrapped at the end marker"
    assert engine.loop_enabled


def test_a_jump_inside_a_loop_fires_after_the_wrap(engine):
    engine.set_loop_bounds(200, 300)
    engine.set_loop_enabled(True)
    engine.seek_ms(280)
    engine.schedule_jump_ms(210, 200)  # reached only after wrapping

    frames = block(engine)

    assert frames[:20] == list(range(280, 300))
    assert frames[20:30] == list(range(200, 210))
    assert frames[30:40] == list(range(200, 210)), "retriggered at 210"


def test_a_seek_cancels_it(engine):
    engine.schedule_jump_ms(1_030, 200)
    engine.seek_ms(5_000)
    assert not engine.has_pending_jump()


def test_a_retrigger_keeps_a_waiting_loop_start(engine):
    engine.set_loop_bounds(200, 250)
    engine.schedule_jump_ms(1_030, 200, enable_loop=True)
    engine.schedule_jump_ms(1_040, 200)
    assert engine._jump[2] is True


def test_cancelling_a_loop_start_only_spares_a_retrigger(engine):
    engine.schedule_jump_ms(1_030, 200)
    engine.cancel_jump(loop_start_only=True)
    assert engine.has_pending_jump()


def test_a_fired_jump_is_reported_as_a_seek(engine, qtbot):
    engine.seek_ms(1_000)
    engine.schedule_jump_ms(1_030, 200)
    block(engine)
    with qtbot.waitSignal(engine.seeked, timeout=500):
        engine._tick()


def test_the_render_lead_is_the_block_not_yet_heard(engine, monkeypatch):
    from src.gui.widgets import stream_clock

    monkeypatch.setattr(stream_clock.time, "perf_counter", lambda: 10.0)
    engine._clock.set_latency(0.05)
    block(engine)
    # Heard 50 ms after rendering began, 100 frames rendered: at t=10.0 the
    # ear is 50 ms before the block and the device holds 150 ms of audio.
    assert engine.render_lead_ms(10.0) == pytest.approx(150.0)
