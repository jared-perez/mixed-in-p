"""Command-line interface for Mixed in P.

Provides commands to analyze audio files for BPM and key detection,
and rename files with configurable templates.
"""

import argparse
import json
import sys
from pathlib import Path

from tqdm import tqdm

from .analysis.analyzer import (
    analyze_file,
    analyze_files,
    find_audio_files,
    AnalysisResult,
    SUPPORTED_EXTENSIONS,
)
from .analysis.keycode import get_compatible_keys


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="mixed-in-p",
        description="Analyze audio files for BPM and musical key detection",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Analyze command
    analyze_parser = subparsers.add_parser(
        "analyze", help="Analyze audio file(s) for BPM and key"
    )
    analyze_parser.add_argument(
        "path", help="Audio file or directory to analyze"
    )
    analyze_parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Search directories recursively",
    )
    analyze_parser.add_argument(
        "-f", "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )
    analyze_parser.add_argument(
        "-w", "--workers",
        type=int,
        default=4,
        help="Number of parallel workers for batch analysis (default: 4)",
    )
    analyze_parser.add_argument(
        "--min-bpm",
        type=float,
        default=85.0,
        help="Minimum expected BPM (default: 85)",
    )
    analyze_parser.add_argument(
        "--max-bpm",
        type=float,
        default=175.0,
        help="Maximum expected BPM (default: 175)",
    )
    analyze_parser.add_argument(
        "--compatible",
        action="store_true",
        help="Show compatible keys for harmonic mixing",
    )

    # Rename command
    rename_parser = subparsers.add_parser(
        "rename", help="Rename audio files with templates"
    )
    rename_parser.add_argument(
        "path",
        nargs="?",
        help="Audio file or directory to rename",
    )
    rename_parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Search directories recursively",
    )
    rename_parser.add_argument(
        "--preview",
        action="store_true",
        help="Show changes without applying them (dry run)",
    )

    # Trim operations
    rename_parser.add_argument(
        "--trim-start",
        type=int,
        metavar="N",
        help="Remove N characters from start of filename",
    )
    rename_parser.add_argument(
        "--trim-end",
        type=int,
        metavar="N",
        help="Remove N characters from end of filename (before extension)",
    )

    # Add operations
    rename_parser.add_argument(
        "--add-prefix",
        type=str,
        metavar="TEXT",
        help="Add text to start of filename",
    )
    rename_parser.add_argument(
        "--add-suffix",
        type=str,
        metavar="TEXT",
        help="Add text to end of filename (before extension)",
    )

    # Replace operation
    rename_parser.add_argument(
        "--replace",
        nargs=2,
        metavar=("OLD", "NEW"),
        help="Replace OLD text with NEW text in filename",
    )

    # BPM/Key operations
    rename_parser.add_argument(
        "--add-bpm",
        action="store_true",
        help="Add BPM to filename (requires analysis)",
    )
    rename_parser.add_argument(
        "--add-key",
        action="store_true",
        help="Add key to filename (requires analysis)",
    )
    rename_parser.add_argument(
        "--key-format",
        choices=["keycode", "standard"],
        default="keycode",
        help="Key format: keycode (8A) or standard (Am) (default: keycode)",
    )
    rename_parser.add_argument(
        "--order",
        choices=["key-first", "bpm-first"],
        default="key-first",
        help="Order of BPM/Key in filename (default: key-first)",
    )
    rename_parser.add_argument(
        "--position",
        choices=["start", "end"],
        default="end",
        help="Position of BPM/Key: start or end of filename (default: end)",
    )
    rename_parser.add_argument(
        "--brackets",
        choices=["square", "round", "none"],
        default="square",
        help="Bracket style: square [128], round (128), or none (default: square)",
    )

    # Metadata options
    rename_parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Write BPM/Key to file tags without renaming",
    )
    rename_parser.add_argument(
        "--no-metadata",
        action="store_true",
        help="Rename only, don't update file tags",
    )

    # Undo options
    rename_parser.add_argument(
        "--undo",
        nargs="?",
        const="last",
        metavar="SESSION_ID",
        help="Undo last rename session or specific session by ID",
    )
    rename_parser.add_argument(
        "--history",
        action="store_true",
        help="List recent rename sessions",
    )

    # Analysis options for rename
    rename_parser.add_argument(
        "-w", "--workers",
        type=int,
        default=4,
        help="Number of parallel workers for analysis (default: 4)",
    )
    rename_parser.add_argument(
        "--min-bpm",
        type=float,
        default=85.0,
        help="Minimum expected BPM (default: 85)",
    )
    rename_parser.add_argument(
        "--max-bpm",
        type=float,
        default=175.0,
        help="Maximum expected BPM (default: 175)",
    )

    # Convert command
    convert_parser = subparsers.add_parser(
        "convert", help="Convert audio files between formats (WAV/FLAC/AIFF/MP3)"
    )
    convert_parser.add_argument(
        "path", help="Audio file or directory to convert"
    )
    convert_parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Search directories recursively",
    )
    convert_parser.add_argument(
        "-t", "--to",
        required=True,
        choices=["WAV", "FLAC", "AIFF", "MP3"],
        help="Target format",
    )
    convert_parser.add_argument(
        "-o", "--output-dir",
        metavar="DIR",
        help="Output directory (default: alongside each source file)",
    )
    convert_parser.add_argument(
        "--bitrate",
        type=int,
        default=320,
        choices=[128, 192, 256, 320],
        help="MP3 bitrate in kbps; ignored for lossless targets (default: 320)",
    )
    convert_parser.add_argument(
        "--sample-rate",
        type=int,
        metavar="HZ",
        help="Resample to this rate (e.g. 44100); lossless targets only",
    )
    convert_parser.add_argument(
        "--bit-depth",
        type=int,
        choices=[8, 16, 24, 32],
        help="Output bit depth; lossless targets only (FLAC clamps 32->24, 8->16)",
    )
    convert_parser.add_argument(
        "-f", "--format",
        choices=["table", "json"],
        default="table",
        help="Result report format (default: table)",
    )
    convert_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List planned conversions (and blocked/skipped files) without writing",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "analyze":
        run_analyze(args)
    elif args.command == "rename":
        run_rename(args)
    elif args.command == "convert":
        run_convert(args)


def run_analyze(args):
    """Execute the analyze command."""
    path = Path(args.path)

    if not path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    # Collect files to analyze
    if path.is_file():
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            print(
                f"Error: Unsupported file format: {path.suffix}",
                file=sys.stderr,
            )
            print(f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
            sys.exit(1)
        file_paths = [str(path.absolute())]
    else:
        file_paths = find_audio_files(str(path), recursive=args.recursive)
        if not file_paths:
            print(f"No audio files found in: {args.path}", file=sys.stderr)
            sys.exit(1)

    # Analyze files
    if len(file_paths) == 1:
        results = [analyze_file(file_paths[0], args.min_bpm, args.max_bpm)]
    else:
        # Use tqdm for progress bar
        pbar = tqdm(total=len(file_paths), desc="Analyzing", unit="file")

        def progress_callback(completed, total):
            pbar.n = completed
            pbar.refresh()

        results = analyze_files(
            file_paths,
            workers=args.workers,
            min_bpm=args.min_bpm,
            max_bpm=args.max_bpm,
            progress_callback=progress_callback,
        )
        pbar.close()

    # Output results
    if args.format == "json":
        output_json(results, args.compatible)
    else:
        output_table(results, args.compatible)


def run_rename(args):
    """Execute the rename command."""
    from .renamer import (
        TrimStart,
        TrimEnd,
        AddPrefix,
        AddSuffix,
        Replace,
        AddAnalysis,
        preview_rename,
        format_preview_table,
        has_conflicts,
        has_changes,
        create_session,
        save_session,
        load_session,
        list_sessions,
        undo_session,
        format_session_list,
        operations_to_dict,
    )
    from .metadata import update_bpm_key

    # Handle undo/history commands first
    if args.history:
        sessions = list_sessions(limit=10)
        print(format_session_list(sessions))
        return

    if args.undo is not None:
        run_undo(args.undo)
        return

    # Path is required for rename operations
    if args.path is None:
        print("Error: path is required for rename operations", file=sys.stderr)
        sys.exit(1)

    path = Path(args.path)
    if not path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    # Collect files
    if path.is_file():
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            print(f"Error: Unsupported file format: {path.suffix}", file=sys.stderr)
            sys.exit(1)
        file_paths = [str(path.absolute())]
    else:
        file_paths = find_audio_files(str(path), recursive=args.recursive)
        if not file_paths:
            print(f"No audio files found in: {args.path}", file=sys.stderr)
            sys.exit(1)

    # Build operations list
    operations = []

    if args.trim_start:
        operations.append(TrimStart(count=args.trim_start))

    if args.trim_end:
        operations.append(TrimEnd(count=args.trim_end))

    if args.add_prefix:
        operations.append(AddPrefix(prefix=args.add_prefix))

    if args.add_suffix:
        operations.append(AddSuffix(suffix=args.add_suffix))

    if args.replace:
        operations.append(Replace(find=args.replace[0], replace=args.replace[1]))

    # Check if we need analysis
    needs_analysis = args.add_bpm or args.add_key

    if needs_analysis:
        operations.append(AddAnalysis(
            include_bpm=args.add_bpm,
            include_key=args.add_key,
            key_format=args.key_format,
            order="bpm_first" if args.order == "bpm-first" else "key_first",
            position=args.position,
            bracket_style=args.brackets,
        ))

    # Validate we have something to do
    if not operations and not args.metadata_only:
        print("Error: No operations specified. Use --help to see available options.", file=sys.stderr)
        sys.exit(1)

    # Run analysis if needed
    analysis_results: dict[str, AnalysisResult] = {}
    if needs_analysis:
        print(f"Analyzing {len(file_paths)} file(s)...")

        if len(file_paths) == 1:
            results = [analyze_file(file_paths[0], args.min_bpm, args.max_bpm)]
        else:
            pbar = tqdm(total=len(file_paths), desc="Analyzing", unit="file")

            def progress_callback(completed, total):
                pbar.n = completed
                pbar.refresh()

            results = analyze_files(
                file_paths,
                workers=args.workers,
                min_bpm=args.min_bpm,
                max_bpm=args.max_bpm,
                progress_callback=progress_callback,
            )
            pbar.close()

        # Build lookup dict
        for result in results:
            if not result.error:
                analysis_results[result.file_path] = result

        # Report analysis errors
        errors = [r for r in results if r.error]
        if errors:
            print(f"\nWarning: {len(errors)} file(s) could not be analyzed:")
            for r in errors[:5]:
                print(f"  - {r.filename}: {r.error}")
            if len(errors) > 5:
                print(f"  ... and {len(errors) - 5} more")
            print()

    # Metadata-only mode
    if args.metadata_only:
        if not needs_analysis:
            print("Error: --metadata-only requires --add-bpm and/or --add-key", file=sys.stderr)
            sys.exit(1)

        print(f"Updating metadata for {len(analysis_results)} file(s)...")
        success_count = 0
        for file_path, result in analysis_results.items():
            key_value = result.keycode if args.key_format == "keycode" else result.key
            bpm_value = result.bpm if args.add_bpm else None
            key_to_write = key_value if args.add_key else None

            try:
                update_bpm_key(file_path, bpm=bpm_value, key=key_to_write)
                success_count += 1
            except Exception as e:
                print(f"  Warning: Could not update {Path(file_path).name}: {e}")

        print(f"Updated metadata for {success_count} file(s).")
        return

    # Generate preview
    previews = preview_rename(file_paths, operations, analysis_results)

    # Check for issues
    if not has_changes(previews):
        print("No files would be renamed (all names unchanged).")
        return

    # Show preview
    print(format_preview_table(previews))
    print()

    if has_conflicts(previews):
        print("Error: Cannot proceed due to conflicts. Resolve them first.", file=sys.stderr)
        sys.exit(1)

    # Preview mode - stop here
    if args.preview:
        changes = sum(1 for p in previews if p.original_name != p.new_name)
        print(f"\nPreview complete. {changes} file(s) would be renamed.")
        print("Run without --preview to apply changes.")
        return

    # Execute renames
    print("Renaming files...")
    renames = []
    errors = []

    for preview in previews:
        if preview.original_name == preview.new_name:
            continue

        try:
            Path(preview.original_path).rename(preview.new_path)
            renames.append((preview.original_path, preview.new_path))
        except OSError as e:
            errors.append((preview.original_name, str(e)))

    # Update metadata if not disabled
    if not args.no_metadata and needs_analysis:
        print("Updating metadata...")
        for original_path, new_path in renames:
            if original_path in analysis_results:
                result = analysis_results[original_path]
                key_value = result.keycode if args.key_format == "keycode" else result.key
                bpm_value = result.bpm if args.add_bpm else None
                key_to_write = key_value if args.add_key else None

                try:
                    update_bpm_key(new_path, bpm=bpm_value, key=key_to_write)
                except Exception:
                    pass  # Best effort

    # Save history for undo
    if renames:
        session = create_session(
            renames,
            operations=operations_to_dict(operations),
            description=f"Renamed {len(renames)} files",
        )
        session_path = save_session(session)
        print(f"\nRenamed {len(renames)} file(s). Session ID: {session.session_id}")
        print(f"To undo: mixed-in-p rename --undo {session.session_id}")

    if errors:
        print(f"\n{len(errors)} error(s) occurred:")
        for name, error in errors:
            print(f"  - {name}: {error}")


def run_undo(session_id: str):
    """Execute undo of a rename session."""
    from .renamer import (
        load_session,
        list_sessions,
        undo_session,
        delete_session,
    )

    # If "last", get the most recent session
    if session_id == "last":
        sessions = list_sessions(limit=1)
        if not sessions:
            print("No rename sessions found to undo.", file=sys.stderr)
            sys.exit(1)
        session = sessions[0]
    else:
        try:
            session = load_session(session_id)
        except FileNotFoundError:
            print(f"Error: Session not found: {session_id}", file=sys.stderr)
            sys.exit(1)

    print(f"Undoing session {session.session_id} ({session.file_count} files)...")

    results = undo_session(session)

    success_count = sum(1 for _, _, success, _ in results if success)
    error_count = len(results) - success_count

    if success_count > 0:
        print(f"Restored {success_count} file(s) to original names.")
        delete_session(session.session_id)

    if error_count > 0:
        print(f"\n{error_count} error(s) occurred:")
        for old, new, success, error in results:
            if not success:
                print(f"  - {Path(old).name}: {error}")


def run_convert(args):
    """Execute the convert command."""
    from .conversion.converter import convert_file
    from .conversion.result import (
        FORMAT_EXTENSION,
        LOSSLESS_EXTENSIONS,
        LOSSY_EXTENSIONS,
        resolve_output_path,
    )

    path = Path(args.path)
    if not path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    # Collect files. convert_file vets each source itself (blocking lossy
    # sources, skipping same-format), so we hand it everything find_audio_files
    # returns rather than pre-filtering — that way blocks/skips show up in the
    # report instead of silently vanishing.
    if path.is_file():
        file_paths = [str(path.absolute())]
    else:
        file_paths = find_audio_files(str(path), recursive=args.recursive)
        if not file_paths:
            print(f"No audio files found in: {args.path}", file=sys.stderr)
            sys.exit(1)

    target_ext = FORMAT_EXTENSION[args.to]

    # Dry run: classify each file without touching disk. Blocks (lossy/
    # unsupported source) and skips (same-format) are predicted exactly, and
    # planned output names go through the same resolve_output_path() the real
    # conversion uses, so the preview matches the names that will be written
    # (for output names already present on disk).
    if args.dry_run:
        planned = []
        skipped = []
        blocked = []
        for fp in file_paths:
            ext = Path(fp).suffix.lower()
            normalised = ".aiff" if ext == ".aif" else ext
            if ext in LOSSY_EXTENSIONS:
                blocked.append((fp, "lossy source — lossless-to-lossy only"))
            elif ext not in LOSSLESS_EXTENSIONS:
                blocked.append((fp, f"unsupported source format: {ext}"))
            elif normalised == target_ext:
                skipped.append(fp)
            else:
                out_path = resolve_output_path(fp, target_ext, args.output_dir)
                planned.append((fp, str(out_path)))

        if args.format == "json":
            report = (
                [{"source_path": s, "output_path": o, "status": "planned"} for s, o in planned]
                + [{"source_path": s, "output_path": None, "status": "skipped"} for s in skipped]
                + [{"source_path": s, "output_path": None, "status": "blocked", "error": why}
                   for s, why in blocked]
            )
            print(json.dumps(report, indent=2))
        else:
            _report_convert_plan(planned, skipped, blocked, args.to)
        return

    # Execute. convert_file never raises — every outcome rides on the
    # returned ConversionResult (ok / skipped / error / incomplete).
    iterator = file_paths
    if len(file_paths) > 1 and args.format == "table":
        iterator = tqdm(file_paths, desc="Converting", unit="file")

    results = []
    for fp in iterator:
        results.append(convert_file(
            fp,
            args.to,
            output_dir=args.output_dir,
            bitrate=args.bitrate,
            sample_rate=args.sample_rate,
            bit_depth=args.bit_depth,
        ))

    if args.format == "json":
        convert_output_json(results)
    else:
        convert_output_table(results)

    # Non-zero exit if any genuine failure occurred (skips/blocks don't count).
    if any(r.error for r in results):
        sys.exit(1)


def _report_convert_plan(planned, skipped, blocked, target_format):
    """Print the dry-run plan as a table."""
    for source, out_path in planned:
        print(f"  PLAN   {Path(source).name}  ->  {Path(out_path).name}")
    for source in skipped:
        print(f"  SKIP   {Path(source).name}  (already {target_format})")
    for source, why in blocked:
        print(f"  BLOCK  {Path(source).name}  ->  {why}")
    print(
        f"\nDry run: {len(planned)} to convert, "
        f"{len(skipped)} skipped, {len(blocked)} blocked. "
        "Run without --dry-run to apply."
    )


def convert_output_json(results):
    """Output conversion results as JSON.

    `status` disambiguates the three non-error outcomes an agent needs to tell
    apart: a skipped file has no error but also no output, and `incomplete`
    flags a source diagnosed as truncated.
    """
    output = []
    for r in results:
        output.append({
            "source_path": r.source_path,
            "output_path": r.output_path or None,
            "target_format": r.target_format,
            "status": "skipped" if r.skipped else "error" if r.error else "ok",
            "error": r.error,
            "incomplete": r.incomplete,
        })
    print(json.dumps(output, indent=2))


def convert_output_table(results):
    """Output conversion results as a formatted table."""
    ok = sum(1 for r in results if not r.error and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if r.error)

    for r in results:
        name = Path(r.source_path).name
        if r.skipped:
            print(f"  SKIP   {name}  (already {r.target_format})")
        elif r.error:
            tag = "INCOMP" if r.incomplete else "ERROR"
            print(f"  {tag:<6} {name}  ->  {r.error}")
        else:
            print(f"  OK     {name}  ->  {Path(r.output_path).name}")

    print(f"\n{ok} converted, {skipped} skipped, {failed} failed.")


def output_table(results: list[AnalysisResult], show_compatible: bool = False):
    """Output results as a formatted table."""
    if not results:
        print("No results.")
        return

    # Calculate column widths
    name_width = max(len(r.filename) for r in results)
    name_width = max(name_width, 8)  # Minimum width
    name_width = min(name_width, 50)  # Maximum width

    # Print header
    header = f"{'File':<{name_width}}  {'BPM':>6}  {'Key':<4}  {'Key Code':<7}  {'Conf':>5}"
    if show_compatible:
        header += "  Compatible"
    print(header)
    print("-" * len(header))

    # Print results
    for r in results:
        if r.error:
            print(f"{r.filename:<{name_width}}  ERROR: {r.error}")
            continue

        # Truncate long filenames
        name = r.filename[:name_width] if len(r.filename) > name_width else r.filename

        # Average confidence
        avg_conf = (r.bpm_confidence + r.key_confidence) / 2

        row = f"{name:<{name_width}}  {r.bpm:>6.1f}  {r.key:<4}  {r.keycode:<7}  {avg_conf:>5.0%}"

        if show_compatible and r.keycode:
            compatible = get_compatible_keys(r.keycode)
            # Remove self from compatible list for display
            compatible = [c for c in compatible if c != r.keycode]
            row += f"  {', '.join(compatible)}"

        print(row)


def output_json(results: list[AnalysisResult], show_compatible: bool = False):
    """Output results as JSON."""
    output = []
    for r in results:
        data = r.to_dict()
        if show_compatible and r.keycode:
            data["compatible_keys"] = get_compatible_keys(r.keycode)
        output.append(data)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
