"""Tests for incremental CSV filtering and extraction."""

from __future__ import annotations

import csv
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parser import (  # noqa: E402
    ExtractConfig,
    FatalParseError,
    FieldRule,
    build_config,
    process_csv,
)

PARSER = ROOT / "parser.py"
SAMPLE = ROOT / "sample" / "input.csv"

SAMPLE_ROWS = [
    {
        "id": "1",
        "email": "ada@example.com",
        "name": "Ada Lovelace",
        "status": "active",
        "amount": "250.00",
    },
    {
        "id": "2",
        "email": "grace@example.com",
        "name": "Grace Hopper",
        "status": "active",
        "amount": "100",
    },
    {
        "id": "5",
        "email": "margaret@example.com",
        "name": "Margaret Hamilton",
        "status": "active",
        "amount": "1000.50",
    },
    {
        "id": "9",
        "email": "katherine@example.com",
        "name": "Katherine Johnson",
        "status": "active",
        "amount": "150.25",
    },
    {
        "id": "11",
        "email": "empty-name@example.com",
        "name": "",
        "status": "active",
        "amount": "400",
    },
    {
        "id": "14",
        "email": "extra@example.com",
        "name": "Extra, Person",
        "status": "active",
        "amount": "180",
    },
    {
        "id": "15",
        "email": "space@example.com",
        "name": "Spacey",
        "status": " active ",
        "amount": "125",
    },
]


def write_csv(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def read_output(path: Path) -> tuple[list[str], list[dict[str, str | None]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        assert reader.fieldnames is not None
        return list(reader.fieldnames), rows


def run_parser(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(PARSER), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


def test_matching_and_non_matching_rows(tmp_path: Path) -> None:
    source = tmp_path / "input.csv"
    target = tmp_path / "output.csv"
    write_csv(
        source,
        "\n".join(
            [
                "id,email,name,status,amount",
                "1,a@example.com,Ada,active,250",
                "2,b@example.com,Grace, active ,100",
                "3,c@example.com,Alan,active,99.99",
                "4,d@example.com,Lin,inactive,500",
                "5,e@example.com,Upper,ACTIVE,400",
                "",
            ]
        ),
    )

    stats = process_csv(source, target, build_config(status="active", min_amount=100))

    header, rows = read_output(target)
    assert header == ["id", "email", "name", "status", "amount"]
    assert [row["id"] for row in rows] == ["1", "2"]
    assert rows[1]["status"] == " active "
    assert stats.total_rows == 5
    assert stats.matched_rows == 2
    assert stats.invalid_rows == 0
    assert stats.errors == 0


def test_filters_can_be_used_separately(tmp_path: Path) -> None:
    source = tmp_path / "input.csv"
    target = tmp_path / "output.csv"
    write_csv(
        source,
        "\n".join(
            [
                "id,email,name,status,amount",
                "1,a@example.com,High Inactive,inactive,500",
                "2,b@example.com,Low Active,active,40",
                "3,c@example.com,Zero,active,0",
                "4,d@example.com,Negative,active,-5",
                "",
            ]
        ),
    )

    amount_only = process_csv(source, target, build_config(min_amount=0))
    _, amount_rows = read_output(target)
    assert [row["id"] for row in amount_rows] == ["1", "2", "3"]
    assert amount_only.matched_rows == 3

    status_only = process_csv(source, target, build_config(status="active"))
    _, status_rows = read_output(target)
    assert [row["id"] for row in status_rows] == ["2", "3", "4"]
    assert status_rows[1]["amount"] == "0"
    assert status_only.invalid_rows == 0


def test_invalid_values_are_reported_without_stopping(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "input.csv"
    target = tmp_path / "output.csv"
    write_csv(
        source,
        "\n".join(
            [
                "id,email,name,status,amount",
                "1,a@example.com,Ok,active,150",
                "2,b@example.com,Low,active,10",
                "3,c@example.com,Bad,active,not-a-number",
                "4,d@example.com,Empty,active,",
                "5,e@example.com,Nan,active,nan",
                "6,f@example.com,Inf,active,inf",
                "7,g@example.com,Short",
                "8,h@example.com,Later,active,200",
                "",
            ]
        ),
    )

    stats = process_csv(source, target, build_config(status="active", min_amount=100))
    captured = capsys.readouterr()
    _, rows = read_output(target)

    assert [row["id"] for row in rows] == ["1", "8"]
    assert stats.total_rows == 8
    assert stats.matched_rows == 2
    assert stats.invalid_rows == 5
    assert stats.errors == 6
    assert "column 'amount' is not a number: 'not-a-number'" in captured.err
    assert "column 'amount' is empty" in captured.err
    assert "column 'amount' is not a finite number: 'nan'" in captured.err
    assert "column 'amount' is not a finite number: 'inf'" in captured.err
    assert "missing value for column 'status'" in captured.err
    assert "missing value for column 'amount'" in captured.err
    assert "line 8:" in captured.err


def test_amount_text_is_copied_when_no_numeric_rule_is_set(tmp_path: Path) -> None:
    source = tmp_path / "input.csv"
    target = tmp_path / "output.csv"
    write_csv(
        source,
        "\n".join(
            [
                "id,email,name,status,amount",
                "1,a@example.com,Bad,active,not-a-number",
                "2,b@example.com,Other,inactive,20",
                "",
            ]
        ),
    )

    stats = process_csv(source, target, build_config(status="active"))
    _, rows = read_output(target)

    assert stats.matched_rows == 1
    assert stats.invalid_rows == 0
    assert rows[0]["amount"] == "not-a-number"


def test_selected_fields_and_created_directories(tmp_path: Path) -> None:
    source = tmp_path / "input.csv"
    target = tmp_path / "nested" / "extracted.csv"
    write_csv(
        source,
        "\n".join(
            [
                "id,email,name,status,amount",
                "1,a@example.com,Ada,active,250",
                "2,b@example.com,Lin,inactive,500",
                "",
            ]
        ),
    )

    stats = process_csv(
        source,
        target,
        build_config(output_fields=("id", "amount"), status="active", min_amount=100),
    )
    header, rows = read_output(target)

    assert target.is_file()
    assert header == ["id", "amount"]
    assert rows == [{"id": "1", "amount": "250"}]
    assert stats.matched_rows == 1
    assert Path(stats.output_path) == target.resolve()


def test_rules_work_for_another_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "orders.csv"
    target = tmp_path / "eu.csv"
    write_csv(
        source,
        "\n".join(
            [
                "sku,region,qty",
                "A1,EU,5",
                "A2,US,nope",
                "A3,EU,4",
                "A4, EU ,8",
                "",
            ]
        ),
    )
    config = ExtractConfig(
        output_fields=("sku", "qty"),
        rules=(FieldRule("region", "eq", "EU"), FieldRule("qty", "gte", 5)),
    )

    stats = process_csv(source, target, config)
    captured = capsys.readouterr()
    header, rows = read_output(target)

    assert header == ["sku", "qty"]
    assert [row["sku"] for row in rows] == ["A1", "A4"]
    assert stats.total_rows == 4
    assert stats.matched_rows == 2
    assert stats.invalid_rows == 1
    assert stats.errors == 1
    assert "column 'qty' is not a number: 'nope'" in captured.err


def test_header_is_written_when_nothing_matches(tmp_path: Path) -> None:
    source = tmp_path / "input.csv"
    target = tmp_path / "output.csv"
    write_csv(
        source,
        "id,email,name,status,amount\n1,a@example.com,Lin,inactive,500\n",
    )

    stats = process_csv(source, target, build_config(status="active", min_amount=100))
    header, rows = read_output(target)

    assert header == ["id", "email", "name", "status", "amount"]
    assert rows == []
    assert stats.total_rows == 1
    assert stats.matched_rows == 0
    assert stats.invalid_rows == 0


def test_sample_input_extracts_expected_rows(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "extracted.csv"
    stats = process_csv(SAMPLE, target, build_config(status="active", min_amount=100))
    captured = capsys.readouterr()
    header, rows = read_output(target)

    assert header == ["id", "email", "name", "status", "amount"]
    assert rows == SAMPLE_ROWS
    assert stats.total_rows == 15
    assert stats.matched_rows == 7
    assert stats.invalid_rows == 2
    assert stats.errors == 3
    assert "line 8: column 'amount' is not a number: 'not-a-number'" in captured.err
    assert (
        "line 14: missing value for column 'status'; missing value for column 'amount'"
        in captured.err
    )


def test_missing_input_file(tmp_path: Path) -> None:
    target = tmp_path / "output.csv"
    with pytest.raises(FatalParseError, match="input file not found"):
        process_csv(tmp_path / "missing.csv", target, build_config())
    assert not target.exists()


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("", "no header"),
        (
            "id,email,name,status,amount,status\n1,a@example.com,A,active,10,extra\n",
            "duplicate column",
        ),
        ("foo,bar\n1,2\n", "missing required column"),
        ("id,email,,status,amount\n1,a@example.com,A,active,10\n", "empty column name"),
    ],
)
def test_invalid_csv_structure_writes_nothing(tmp_path: Path, contents: str, message: str) -> None:
    source = tmp_path / "input.csv"
    target = tmp_path / "nested" / "output.csv"
    write_csv(source, contents)

    with pytest.raises(FatalParseError, match=message):
        process_csv(source, target, build_config(status="active", min_amount=100))

    assert not target.exists()
    assert not target.parent.exists()


def test_input_directory_is_fatal(tmp_path: Path) -> None:
    folder = tmp_path / "data"
    folder.mkdir()
    with pytest.raises(FatalParseError, match="not a file"):
        process_csv(folder, tmp_path / "output.csv", build_config())


def test_invalid_utf8_is_fatal(tmp_path: Path) -> None:
    source = tmp_path / "input.csv"
    target = tmp_path / "output.csv"
    source.write_bytes(b"\xffid,email,name,status,amount\n1,a@example.com,A,active,10\n")

    with pytest.raises(FatalParseError, match="not valid UTF-8"):
        process_csv(source, target, build_config())

    assert not target.exists()


def test_same_input_and_output_is_fatal(tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    write_csv(source, "id,email,name,status,amount\n1,a@example.com,A,active,10\n")

    with pytest.raises(FatalParseError, match="must be different"):
        process_csv(source, source, build_config())


def test_utf8_bom_header_is_accepted(tmp_path: Path) -> None:
    source = tmp_path / "input.csv"
    target = tmp_path / "output.csv"
    source.write_bytes(
        b"\xef\xbb\xbfid,email,name,status,amount\n1,a@example.com,Ada,active,150\n"
    )

    stats = process_csv(source, target, build_config(status="active", min_amount=100))
    header, rows = read_output(target)

    assert header == ["id", "email", "name", "status", "amount"]
    assert rows[0]["id"] == "1"
    assert stats.matched_rows == 1
    assert stats.invalid_rows == 0


def test_malformed_quote_skips_that_row_and_continues(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "input.csv"
    target = tmp_path / "output.csv"
    write_csv(
        source,
        "\n".join(
            [
                "id,email,name,status,amount",
                "1,a@example.com,Ada,active,150",
                '2,b@example.com,"Broken"quote,active,300',
                "3,c@example.com,Grace,active,120",
                "",
            ]
        ),
    )

    stats = process_csv(source, target, build_config(status="active", min_amount=100))
    captured = capsys.readouterr()
    _, rows = read_output(target)

    assert [row["id"] for row in rows] == ["1", "3"]
    assert stats.total_rows == 3
    assert stats.matched_rows == 2
    assert stats.invalid_rows == 1
    assert stats.errors == 1
    assert "malformed CSV row" in captured.err


def test_unclosed_quote_is_reported_without_hanging(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "input.csv"
    target = tmp_path / "output.csv"
    write_csv(
        source,
        "\n".join(
            [
                "id,email,name,status,amount",
                "1,a@example.com,Ada,active,150",
                '2,b@example.com,"unclosed,active,300',
                "3,c@example.com,Grace,active,120",
                "",
            ]
        ),
    )

    stats = process_csv(source, target, build_config(status="active", min_amount=100))
    captured = capsys.readouterr()
    _, rows = read_output(target)

    assert [row["id"] for row in rows] == ["1"]
    assert stats.matched_rows == 1
    assert stats.invalid_rows == 1
    assert stats.errors == 1
    assert "malformed CSV row" in captured.err


def test_cli_extracts_sample_and_prints_stats(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "extracted.csv"
    result = run_parser(
        [
            "--input",
            str(SAMPLE),
            "--output",
            str(target),
            "--status",
            "active",
            "--min-amount",
            "100",
            "--fields",
            "id,email,status,amount",
        ]
    )

    assert result.returncode == 0
    assert "not-a-number" in result.stderr
    values = _stats(result.stdout)
    assert values["total_rows"] == "15"
    assert values["matched_rows"] == "7"
    assert values["invalid_rows"] == "2"
    assert values["errors"] == "3"
    assert Path(values["output_path"]) == target.resolve()
    elapsed = float(values["elapsed_seconds"])
    assert math.isfinite(elapsed)
    assert elapsed >= 0

    header, rows = read_output(target)
    assert header == ["id", "email", "status", "amount"]
    assert [row["id"] for row in rows] == [row["id"] for row in SAMPLE_ROWS]
    assert rows[0]["amount"] == "250.00"


def test_cli_help_and_usage_errors(tmp_path: Path) -> None:
    help_result = run_parser(["--help"])
    assert help_result.returncode == 0
    assert "--input" in help_result.stdout
    assert "--output" in help_result.stdout
    assert "--status" in help_result.stdout
    assert "--min-amount" in help_result.stdout
    assert "--fields" in help_result.stdout
    assert "not loaded into memory" in help_result.stdout

    missing = run_parser(
        ["--input", str(tmp_path / "missing.csv"), "--output", str(tmp_path / "out.csv")]
    )
    assert missing.returncode == 1
    assert "input file not found" in missing.stderr
    assert "Processing complete" not in missing.stdout
    assert not (tmp_path / "out.csv").exists()

    unknown = run_parser(["--input", "a.csv", "--output", "b.csv", "--nope"])
    assert unknown.returncode == 2

    bad_amount = run_parser(
        ["--input", "a.csv", "--output", "b.csv", "--min-amount", "abc"]
    )
    assert bad_amount.returncode == 2

    blank_status = run_parser(["--input", "a.csv", "--output", "b.csv", "--status", " "])
    assert blank_status.returncode == 2

    duplicate_fields = run_parser(
        ["--input", "a.csv", "--output", "b.csv", "--fields", "id,id"]
    )
    assert duplicate_fields.returncode == 2


def test_source_streams_instead_of_reading_the_whole_file() -> None:
    source = PARSER.read_text(encoding="utf-8")
    for pattern in ("list(reader)", ".readlines(", ".read(", "read_text(", "read_bytes("):
        assert pattern not in source


def _stats(stdout: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in stdout.splitlines():
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        values[key] = value
    return values
