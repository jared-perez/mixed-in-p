"""Unit tests for ConvertPipeline — no Qt, no I/O."""

from __future__ import annotations

import pytest

from src.conversion.result import ConversionResult
from src.gui.convert_pipeline import (
    STEP_ANALYZE,
    STEP_CONVERT,
    STEP_RENAME,
    ConvertPipeline,
)


def ok(source: str, output: str) -> ConversionResult:
    return ConversionResult(source_path=source, output_path=output, target_format="FLAC")


def failed(source: str, message: str = "boom") -> ConversionResult:
    # The converter returns an empty output_path on every failing return;
    # building it any other way tests a shape the code never receives.
    return ConversionResult(source_path=source, output_path="", target_format="FLAC", error=message)


def skipped(source: str) -> ConversionResult:
    return ConversionResult(source_path=source, output_path="", target_format="FLAC", skipped=True)


@pytest.fixture
def pipeline() -> ConvertPipeline:
    return ConvertPipeline()


def test_inactive_until_armed(pipeline):
    assert not pipeline.active
    assert not pipeline.finished()
    assert pipeline.summary() == (0, 0, 0)
    assert pipeline.conversion_done([ok("/a.wav", "/a.flac")]) == []
    assert pipeline.track_analysed("/a.flac", None) is None


def test_conversion_done_forwards_outputs_and_passthrough(pipeline):
    pipeline.arm(7, "Set", ["/a.wav", "/b.wav"], ["/c.flac"])
    paths = pipeline.conversion_done([ok("/a.wav", "/a.flac"), ok("/b.wav", "/b.flac")])
    assert paths == ["/c.flac", "/a.flac", "/b.flac"]
    assert pipeline.summary() == (0, 0, 0)


def test_errors_and_skips_are_counted_not_forwarded(pipeline):
    pipeline.arm(7, "Set", ["/a.wav", "/b.wav", "/c.wav"], [])
    paths = pipeline.conversion_done([ok("/a.wav", "/a.flac"), failed("/b.wav"), skipped("/c.wav")])
    assert paths == ["/a.flac"]
    assert pipeline.summary() == (0, 0, 2)


def test_a_source_that_never_came_back_is_an_error(pipeline):
    pipeline.arm(7, "Set", ["/a.wav", "/b.wav"], [])
    assert pipeline.conversion_done([ok("/a.wav", "/a.flac")]) == ["/a.flac"]
    assert pipeline.summary() == (0, 0, 1)


def test_foreign_results_are_ignored(pipeline):
    pipeline.arm(7, "Set", ["/a.wav"], [])
    paths = pipeline.conversion_done([ok("/a.wav", "/a.flac"), ok("/stranger.wav", "/stranger.flac")])
    assert paths == ["/a.flac"]
    assert pipeline.summary() == (0, 0, 0)


def test_take_passthrough_drains_once(pipeline):
    pipeline.arm(7, "Set", [], ["/c.flac"])
    assert pipeline.take_passthrough() == ["/c.flac"]
    assert pipeline.take_passthrough() == []


def test_track_analysed_maps_store_spelling_to_library_spelling(pipeline):
    pipeline.arm(7, "Set", [], ["/private/var/c.flac"])
    pipeline.take_passthrough()
    pipeline.await_analysis({"/private/var/c.flac": "/var/c.flac"})
    assert pipeline.analysis_batch_paths() == ["/private/var/c.flac"]
    assert pipeline.track_analysed("/private/var/c.flac", None) == "/var/c.flac"


def test_a_foreign_track_analysed_in_the_same_batch_is_refused(pipeline):
    pipeline.arm(7, "Set", [], ["/c.flac"])
    pipeline.take_passthrough()
    pipeline.await_analysis({"/c.flac": "/c.flac"})
    assert pipeline.track_analysed("/dropped-by-the-user.flac", None) is None
    assert pipeline.summary() == (0, 0, 0)
    assert pipeline.analysis_batch_paths() == ["/c.flac"]


def test_an_analysis_error_is_counted_and_not_added(pipeline):
    pipeline.arm(7, "Set", [], ["/c.flac"])
    pipeline.take_passthrough()
    pipeline.await_analysis({"/c.flac": "/c.flac"})
    assert pipeline.track_analysed("/c.flac", "unreadable") is None
    assert pipeline.summary() == (0, 0, 1)
    assert pipeline.finished()


def test_each_track_retires_exactly_once(pipeline):
    pipeline.arm(7, "Set", [], ["/c.flac"])
    pipeline.take_passthrough()
    pipeline.await_analysis({"/c.flac": "/c.flac"})
    assert pipeline.track_analysed("/c.flac", None) == "/c.flac"
    assert pipeline.track_analysed("/c.flac", None) is None


def test_passthrough_only_run_finishes_after_its_last_track(pipeline):
    pipeline.arm(7, "Set", [], ["/a.flac", "/b.flac"])
    assert pipeline.take_passthrough() == ["/a.flac", "/b.flac"]
    pipeline.await_analysis({"/a.flac": "/a.flac", "/b.flac": "/b.flac"})
    assert not pipeline.finished()
    pipeline.record_added(pipeline.track_analysed("/a.flac", None))
    assert not pipeline.finished()
    pipeline.record_added(pipeline.track_analysed("/b.flac", None))
    assert pipeline.finished()
    assert pipeline.summary() == (2, 0, 0)


def test_analysis_idle_while_files_remain(pipeline):
    pipeline.arm(7, "Set", [], ["/a.flac"])
    pipeline.take_passthrough()
    pipeline.await_analysis({"/a.flac": "/a.flac"})
    assert pipeline.analysis_idle()
    pipeline.track_analysed("/a.flac", None)
    assert not pipeline.analysis_idle()


def test_cancel_ends_the_run(pipeline):
    pipeline.arm(7, "Set", ["/a.wav"], ["/b.flac"])
    pipeline.conversion_cancelled()
    assert not pipeline.active
    assert pipeline.conversion_done([ok("/a.wav", "/a.flac")]) == []
    assert not pipeline.finished()


def test_skipped_duplicates_are_counted(pipeline):
    pipeline.arm(7, "Set", [], ["/a.flac"])
    pipeline.take_passthrough()
    pipeline.await_analysis({"/a.flac": "/a.flac"})
    pipeline.track_analysed("/a.flac", None)
    pipeline.record_skipped()
    assert pipeline.summary() == (0, 1, 0)


def test_end_clears_the_run(pipeline):
    pipeline.arm(7, "Set", [], ["/a.flac"])
    pipeline.end()
    assert not pipeline.active
    assert pipeline.summary() == (0, 0, 0)


# ---------------------------------------------------------------- step routing


def test_arming_without_steps_means_convert_then_analyze(pipeline):
    """Every caller predating the step toggles meant exactly this pair."""
    pipeline.arm(7, "Set", ["/a.wav"], [])
    assert pipeline.has_step(STEP_CONVERT)
    assert pipeline.has_step(STEP_ANALYZE)
    assert not pipeline.has_step(STEP_RENAME)
    assert pipeline.next_step() == STEP_CONVERT
    assert pipeline.next_step(STEP_CONVERT) == STEP_ANALYZE
    assert pipeline.next_step(STEP_ANALYZE) is None


def test_next_step_skips_the_disabled_ones(pipeline):
    pipeline.arm(7, "Set", steps={STEP_RENAME, STEP_ANALYZE})
    assert pipeline.next_step() == STEP_RENAME
    # Convert is off, so rename hands straight to analyze.
    assert pipeline.next_step(STEP_RENAME) == STEP_ANALYZE
    assert pipeline.next_step(STEP_ANALYZE) is None


def test_next_step_is_none_when_only_the_start_step_runs(pipeline):
    """Rename-only: nothing follows it but the playlist add."""
    pipeline.arm(7, "Set", steps={STEP_RENAME}, to_rename=["/a.wav"])
    assert pipeline.next_step(STEP_RENAME) is None


def test_an_inactive_pipeline_routes_nowhere(pipeline):
    assert pipeline.next_step() is None
    assert not pipeline.has_step(STEP_CONVERT)


# ------------------------------------------------------------------- rename leg


def test_a_run_awaiting_rename_is_not_finished(pipeline):
    pipeline.arm(7, "Set", steps={STEP_RENAME}, to_rename=["/a.wav"])
    assert not pipeline.finished()


def test_rename_done_carries_moved_and_untouched_rows_in_armed_order(pipeline):
    pipeline.arm(7, "Set", steps={STEP_RENAME}, to_rename=["/a.wav", "/b.wav", "/c.wav"])
    paths = pipeline.rename_done({"/b.wav": "/128 - b.wav"})
    assert paths == ["/a.wav", "/128 - b.wav", "/c.wav"]
    assert pipeline.finished()


def test_rename_done_drains_once(pipeline):
    pipeline.arm(7, "Set", steps={STEP_RENAME}, to_rename=["/a.wav"])
    assert pipeline.rename_done({}) == ["/a.wav"]
    assert pipeline.rename_done({}) == []


def test_rename_done_on_an_inactive_pipeline_forwards_nothing(pipeline):
    assert pipeline.rename_done({"/a.wav": "/b.wav"}) == []


def test_an_aborted_rename_forwards_nothing(pipeline):
    pipeline.arm(7, "Set", steps={STEP_RENAME}, to_rename=["/a.wav"])
    pipeline.abort()
    assert not pipeline.active
    assert pipeline.rename_done({}) == []


# --------------------------------------------------------------- direct add leg


def test_direct_add_retires_like_analysis_does(pipeline):
    pipeline.arm(7, "Set", steps={STEP_CONVERT})
    assert pipeline.await_direct_add(["/a.flac", "/b.flac"]) == ["/a.flac", "/b.flac"]
    assert not pipeline.finished()
    assert pipeline.direct_add_done("/a.flac")
    pipeline.record_added("/a.flac")
    assert not pipeline.finished()
    assert pipeline.direct_add_done("/b.flac")
    pipeline.record_skipped()
    assert pipeline.finished()
    assert pipeline.summary() == (1, 1, 0)


def test_a_direct_add_run_with_nothing_else_finishes(pipeline):
    """Rename off, convert off, analyze off — just files into a playlist."""
    pipeline.arm(7, "Set")
    pipeline.await_direct_add(["/a.flac"])
    pipeline.direct_add_done("/a.flac")
    pipeline.record_added("/a.flac")
    assert pipeline.finished()


def test_a_direct_add_path_retires_exactly_once(pipeline):
    pipeline.arm(7, "Set")
    pipeline.await_direct_add(["/a.flac"])
    assert pipeline.direct_add_done("/a.flac")
    assert not pipeline.direct_add_done("/a.flac")


def test_a_foreign_direct_add_is_refused(pipeline):
    pipeline.arm(7, "Set")
    pipeline.await_direct_add(["/a.flac"])
    assert not pipeline.direct_add_done("/somebody-elses.flac")
    assert not pipeline.finished()


def test_await_direct_add_registers_each_file_once(pipeline):
    """The caller adds what it is handed back, so a repeat must not come back."""
    pipeline.arm(7, "Set")
    assert pipeline.await_direct_add(["/a.flac", "/a.flac"]) == ["/a.flac"]
    assert pipeline.await_direct_add(["/a.flac"]) == []
    assert pipeline.direct_add_done("/a.flac")
    assert pipeline.finished()


def test_await_direct_add_on_an_inactive_pipeline_registers_nothing(pipeline):
    assert pipeline.await_direct_add(["/a.flac"]) == []
    assert not pipeline.direct_add_done("/a.flac")


def test_a_full_three_step_run_finishes_only_at_the_end(pipeline):
    """rename -> convert -> analyze -> playlist, one file, one step at a time."""
    pipeline.arm(
        7,
        "Set",
        steps={STEP_RENAME, STEP_CONVERT, STEP_ANALYZE},
        to_rename=["/a.wav"],
    )
    assert not pipeline.finished()
    renamed = pipeline.rename_done({"/a.wav": "/128 - a.wav"})

    # Between draining one step and arming the next the run holds nothing and
    # would read as finished — which is why the handoff is synchronous and
    # nothing asks in between.
    run = pipeline.run
    run.awaiting_convert = set(renamed)
    assert pipeline.conversion_done([ok("/128 - a.wav", "/128 - a.flac")]) == ["/128 - a.flac"]

    pipeline.await_analysis({"/private/128 - a.flac": "/128 - a.flac"})
    assert not pipeline.finished()
    assert pipeline.track_analysed("/private/128 - a.flac", None) == "/128 - a.flac"
    pipeline.record_added("/128 - a.flac")
    assert pipeline.finished()
    assert pipeline.summary() == (1, 0, 0)
