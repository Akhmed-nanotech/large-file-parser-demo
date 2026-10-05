"""Stream a CSV file, filter rows, and write selected columns.

The reader yields one record at a time and matches are written immediately.
Nothing in this module collects the input into a list.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Sample-schema defaults. process_csv itself accepts any column names.
DEFAULT_OUTPUT_FIELDS: tuple[str, ...] = (
    "id",
    "email",
    "name",
    "status",
    "amount",
)

__all__ = [
    "DEFAULT_OUTPUT_FIELDS",
    "ExtractConfig",
    "FatalParseError",
    "FieldRule",
    "ProcessingStats",
    "build_config",
    "format_stats",
    "main",
    "process_csv",
]


class FatalParseError(Exception):
    """The file or configuration cannot be processed."""


CsvRow = dict[str, str | None]


@dataclass(frozen=True)
class FieldRule:
    """One comparison against a single column.

    ``op`` is ``eq`` for case-sensitive text equality, or ``gte`` for
    "greater than or equal" on a finite number. Surrounding whitespace
    is ignored during the comparison. The written cell keeps its original text.
    """

    field: str
    op: str
    value: str | float


@dataclass(frozen=True)
class ExtractConfig:
    """Columns to write, and the rules that decide which rows are kept.

    Build this directly for a schema other than the sample file.
    """

    output_fields: tuple[str, ...]
    rules: tuple[FieldRule, ...] = ()


@dataclass
class ProcessingStats:
    """Counts and timing for one completed streaming run."""

    total_rows: int = 0
    matched_rows: int = 0
    invalid_rows: int = 0
    errors: int = 0
    output_path: str = ""
    elapsed_seconds: float = 0.0


def build_config(
    output_fields: tuple[str, ...] = DEFAULT_OUTPUT_FIELDS,
    status: str | None = None,
    min_amount: float | None = None,
) -> ExtractConfig:
    """Build rules for the sample ``status`` and ``amount`` columns.

    Pass ``status=None`` or ``min_amount=None`` to skip that comparison.
    """

    rules: list[FieldRule] = []
    if status is not None:
        rules.append(FieldRule("status", "eq", status.strip()))
    if min_amount is not None:
        rules.append(FieldRule("amount", "gte", float(min_amount)))
    return ExtractConfig(output_fields=tuple(output_fields), rules=tuple(rules))


def process_csv(
    input_path: Path | str,
    output_path: Path | str,
    config: ExtractConfig,
) -> ProcessingStats:
    """Filter ``input_path`` and write matches to ``output_path``.

    Each input row is handled on its own. A bad row is reported and skipped.
    A missing file, an encoding failure, or a header without the required
    columns raises ``FatalParseError`` before a successful summary is returned.
    """

    _validate_config(config)
    source = Path(input_path)
    destination = Path(output_path)
    if not source.exists():
        raise FatalParseError(f"input file not found: {source}")
    if not source.is_file():
        raise FatalParseError(f"input path is not a file: {source}")
    if _same_path(source, destination):
        raise FatalParseError("input and output paths must be different")

    stats = ProcessingStats(output_path=str(destination.resolve()))
    started = time.perf_counter()
    try:
        with source.open("r", encoding="utf-8-sig", newline="", errors="strict") as infile:
            reader = csv.DictReader(infile, strict=True)
            header = _prepare_header(reader)
            _require_columns(header, config)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("w", encoding="utf-8", newline="") as outfile:
                writer = csv.DictWriter(
                    outfile,
                    fieldnames=list(config.output_fields),
                    extrasaction="ignore",
                )
                writer.writeheader()
                _stream_rows(reader, writer, config, stats)
    except FatalParseError:
        raise
    except UnicodeError as exc:
        raise FatalParseError(f"input file is not valid UTF-8: {exc}") from exc
    except OSError as exc:
        raise FatalParseError(f"could not read or write CSV files: {exc}") from exc

    stats.elapsed_seconds = time.perf_counter() - started
    return stats


def format_stats(stats: ProcessingStats) -> str:
    """Format the summary printed after a successful run."""

    lines = [
        "Processing complete",
        f"total_rows: {stats.total_rows}",
        f"matched_rows: {stats.matched_rows}",
        f"invalid_rows: {stats.invalid_rows}",
        f"errors: {stats.errors}",
        f"output_path: {stats.output_path}",
        f"elapsed_seconds: {stats.elapsed_seconds:.6f}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the command-line parser. Returns a process exit code."""

    args = _build_parser().parse_args(argv)
    config = build_config(
        output_fields=args.fields,
        status=args.status,
        min_amount=args.min_amount,
    )
    try:
        stats = process_csv(args.input, args.output, config)
    except FatalParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(format_stats(stats))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parser.py",
        description=(
            "Stream a CSV file one row at a time, keep rows that match simple "
            "field comparisons, and write the selected columns to another CSV. "
            "The input is not loaded into memory."
        ),
        epilog=(
            "examples:\n"
            "  python parser.py --input sample/input.csv "
            "--output output/extracted.csv --status active --min-amount 100\n"
            "  python parser.py --input sample/input.csv "
            "--output output/extracted.csv --fields id,email,status\n"
            "\n"
            "Recoverable row problems are printed to stderr and counted. "
            "The process exits 0 when the file can be streamed. "
            "A missing input file or a header without the required columns exits 1."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", required=True, help="Path to the source CSV file.")
    parser.add_argument("--output", required=True, help="Path to the CSV file to write.")
    parser.add_argument(
        "--status",
        type=_required_text,
        default=None,
        help=(
            "Keep rows whose status column equals this text. "
            "The comparison ignores surrounding whitespace and is case-sensitive."
        ),
    )
    parser.add_argument(
        "--min-amount",
        type=_finite_float,
        default=None,
        help=(
            "Keep rows whose amount column is greater than or equal to this number. "
            "Non-numeric amounts are reported as row errors when this option is set."
        ),
    )
    parser.add_argument(
        "--fields",
        type=_field_list,
        default=DEFAULT_OUTPUT_FIELDS,
        help=(
            "Comma-separated output columns, in order. "
            "Default: id,email,name,status,amount"
        ),
    )
    return parser


def _field_list(raw: str) -> tuple[str, ...]:
    parts = [part.strip() for part in raw.split(",")]
    if not parts or any(part == "" for part in parts):
        raise argparse.ArgumentTypeError("provide a comma-separated list of column names")
    if len(parts) != len(set(parts)):
        raise argparse.ArgumentTypeError("column names must be unique")
    return tuple(parts)


def _required_text(raw: str) -> str:
    text = raw.strip()
    if not text:
        raise argparse.ArgumentTypeError("value cannot be empty")
    return text


def _finite_float(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("minimum amount must be a number") from exc
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError("minimum amount must be a finite number")
    return value


def _validate_config(config: ExtractConfig) -> None:
    if not config.output_fields:
        raise FatalParseError("at least one output field is required")

    seen: set[str] = set()
    for field in config.output_fields:
        if not isinstance(field, str) or field.strip() == "":
            raise FatalParseError("output field names must be non-empty strings")
        if field != field.strip():
            raise FatalParseError(f"output field {field!r} has surrounding whitespace")
        if field in seen:
            raise FatalParseError(f"duplicate output field {field!r}")
        seen.add(field)

    for rule in config.rules:
        if not isinstance(rule.field, str) or rule.field == "" or rule.field != rule.field.strip():
            raise FatalParseError("each comparison needs a column name without surrounding whitespace")
        if rule.op == "eq":
            if not isinstance(rule.value, str):
                raise FatalParseError(f"equality comparison for {rule.field!r} needs text")
            continue
        if rule.op == "gte":
            if isinstance(rule.value, bool) or not isinstance(rule.value, (int, float)):
                raise FatalParseError(f"minimum comparison for {rule.field!r} needs a number")
            if not math.isfinite(float(rule.value)):
                raise FatalParseError(f"minimum comparison for {rule.field!r} must be finite")
            continue
        raise FatalParseError(f"unsupported comparison {rule.op!r} for column {rule.field!r}")


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def _prepare_header(reader: csv.DictReader) -> list[str]:
    raw_header = reader.fieldnames
    if not raw_header:
        raise FatalParseError("input CSV has no header row")

    header = [name.strip() if isinstance(name, str) else "" for name in raw_header]
    if any(name == "" for name in header):
        raise FatalParseError("input CSV header contains an empty column name")
    if len(header) != len(set(header)):
        raise FatalParseError("input CSV header contains duplicate column names")

    reader.fieldnames = header
    return header


def _require_columns(header: list[str], config: ExtractConfig) -> None:
    available = set(header)
    required: list[str] = []
    for name in (*config.output_fields, *(rule.field for rule in config.rules)):
        if name not in required:
            required.append(name)

    missing = [name for name in required if name not in available]
    if missing:
        raise FatalParseError(
            "input CSV is missing required column(s): "
            f"{', '.join(missing)}. Found columns: {', '.join(header)}"
        )


def _stream_rows(
    reader: csv.DictReader,
    writer: csv.DictWriter,
    config: ExtractConfig,
    stats: ProcessingStats,
) -> None:
    """Handle one record at a time.

    ``next`` stays inside this loop so a malformed record can be counted
    and the following records can still be processed.
    """

    previous_error_line = 0
    while True:
        try:
            row = next(reader)
        except StopIteration:
            return
        except csv.Error as exc:
            line = _current_line(reader)
            stats.total_rows += 1
            stats.invalid_rows += 1
            stats.errors += 1
            print(f"error: line {line}: malformed CSV row: {exc}", file=sys.stderr)
            if line <= previous_error_line:
                raise FatalParseError(
                    f"could not continue after a malformed CSV row at line {line}: {exc}"
                ) from exc
            previous_error_line = line
            continue

        stats.total_rows += 1
        problems = _row_problems(row, config)
        if problems:
            stats.invalid_rows += 1
            stats.errors += len(problems)
            detail = "; ".join(problems)
            print(f"error: line {_current_line(reader)}: {detail}", file=sys.stderr)
            continue
        if _row_matches(row, config):
            writer.writerow({field: row[field] for field in config.output_fields})
            stats.matched_rows += 1


def _current_line(reader: csv.DictReader) -> int:
    """Return the source line for the row currently being handled.

    DictReader records its own line number only after a row is built.
    On ``csv.Error``, the wrapped reader already has the failing line.
    """

    raw_reader = reader.reader
    if raw_reader.line_num:
        return int(raw_reader.line_num)
    return int(reader.line_num)


def _row_problems(row: CsvRow, config: ExtractConfig) -> list[str]:
    """Return validation problems for one row.

    Numeric columns are checked only when a numeric rule uses them.
    Missing output columns are always reported.
    """

    problems: list[str] = []
    reported_missing: set[str] = set()

    def mark_missing(field: str) -> None:
        if field in reported_missing:
            return
        reported_missing.add(field)
        problems.append(f"missing value for column {field!r}")

    for field in config.output_fields:
        if row.get(field) is None:
            mark_missing(field)

    for rule in config.rules:
        if rule.op != "gte":
            raw = row.get(rule.field)
            if raw is None:
                mark_missing(rule.field)
            continue

        raw = row.get(rule.field)
        if raw is None:
            mark_missing(rule.field)
            continue
        text = raw.strip()
        if text == "":
            problems.append(f"column {rule.field!r} is empty")
            continue
        try:
            number = float(text)
        except ValueError:
            problems.append(f"column {rule.field!r} is not a number: {raw!r}")
            continue
        if not math.isfinite(number):
            problems.append(f"column {rule.field!r} is not a finite number: {raw!r}")

    return problems


def _row_matches(row: CsvRow, config: ExtractConfig) -> bool:
    for rule in config.rules:
        raw = row.get(rule.field)
        if not isinstance(raw, str):
            raise FatalParseError(f"column {rule.field!r} could not be read as text")
        if rule.op == "eq":
            if raw.strip() != str(rule.value).strip():
                return False
            continue
        if float(raw.strip()) < float(rule.value):
            return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
