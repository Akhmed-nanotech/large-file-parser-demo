# Large File Parser Demo

A small Python proof of concept that filters a CSV file and writes selected columns without loading the file into memory.

## Project purpose

This project shows a straightforward way to process a large CSV extract: read it incrementally, keep the rows that match simple conditions, write those rows to another CSV, and report what happened.

It is a portfolio example for a freelance request that involves downloading and parsing a 72GB file. The demo starts from a local CSV and uses invented sample rows.

## What the demo demonstrates

- Incremental reading with `csv.DictReader`
- Incremental writing with `csv.DictWriter`
- Configurable column selection
- Simple field comparisons: text equality and a numeric minimum
- Row-level validation that skips a bad row and continues
- A non-zero exit when the file or header cannot be processed
- Counts for rows processed, rows kept, invalid rows, and reported problems
- Elapsed time measured by the program on that run

The processing loop is not tied to one business schema. It applies a list of field rules and writes a list of columns. The `--status` and `--min-amount` flags are a convenient way to build those rules for the included sample, whose columns are `id`, `email`, `name`, `status`, and `amount`. Another schema can call `process_csv` with a different `ExtractConfig`.

## Important limitation

This is a proof-of-concept using a small sample dataset. The client's actual 72GB file, format, schema, and extraction requirements have not been provided.

## Why streaming processing is used

A multi-gigabyte file cannot be assumed to fit in RAM, and a filter-and-extract job does not need the whole file at once. The program reads one record at a time and writes a match as soon as it is accepted. Memory stays tied to the current row and a few counters. The included sample is small so the behavior can be reviewed and tested. Its size is not a performance result.

## Project structure

```text
large-file-parser-demo/
├── parser.py
├── requirements.txt
├── README.md
├── .gitignore
├── sample/
│   └── input.csv
├── output/
│   └── .gitkeep
└── tests/
    └── test_parser.py
```

`output/extracted.csv` is created when you run the usage command. It is generated output, not source.

## Installation

Python 3.11 or newer is required. The parser uses the standard library. The only third-party package is pytest, used for the tests.

From this directory:

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
```

macOS or Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage example

```bash
python parser.py --input sample/input.csv --output output/extracted.csv --status active --min-amount 100
```

`--status` keeps rows whose `status` cell equals the given text. `--min-amount` keeps rows whose `amount` cell is greater than or equal to the threshold. Omit either flag to skip that comparison. `--fields` changes which columns are written and in what order. `--help` lists every option.

Comparisons ignore surrounding whitespace. Equality is case-sensitive, so `active` and `ACTIVE` are different. Written cells keep their original text, including surrounding spaces. Amounts are parsed with Python's floating-point conversion, so a value such as `100` or `99.99` works. Currency symbols and thousands separators are left as text and fail the numeric check.

A numeric rule is checked on every row. A bad number is reported even when another rule would have excluded that row. Amount text is validated only when `--min-amount` is set.

Problems in a single row are printed to stderr, counted, and skipped. The process exits 0 when the file can be streamed. A missing file, an unreadable encoding, or a header without the required columns exits 1.

The sample file contains 15 invented rows. Two of them are deliberately bad, so a normal run prints two error lines and still writes the valid matches.

An unclosed quote can make Python's CSV reader treat the rest of the file as one broken record. The program reports that record and stops at the end of the consumed input. Check quoting on a real sample before a long run.

## Example output format

The command above writes `output/extracted.csv`:

```csv
id,email,name,status,amount
1,ada@example.com,Ada Lovelace,active,250.00
2,grace@example.com,Grace Hopper,active,100
5,margaret@example.com,Margaret Hamilton,active,1000.50
9,katherine@example.com,Katherine Johnson,active,150.25
11,empty-name@example.com,,active,400
14,extra@example.com,"Extra, Person",active,180
15,space@example.com,Spacey, active ,125
```

It then prints a summary like this. `elapsed_seconds` is measured when you run the command:

```text
Processing complete
total_rows: 15
matched_rows: 7
invalid_rows: 2
errors: 3
output_path: <path passed to --output>
elapsed_seconds: <seconds measured for this run>
```

`invalid_rows` counts skipped data rows. `errors` counts reported problems. One short row can be missing more than one column, so these numbers can differ.

The sample also prints:

```text
error: line 8: column 'amount' is not a number: 'not-a-number'
error: line 14: missing value for column 'status'; missing value for column 'amount'
```

## Testing

From this directory, after installing requirements:

```bash
python -m pytest
```

The tests cover matching rows, excluded rows, invalid and malformed rows, output creation, fatal input problems, and the command-line options.

## Before processing the real dataset

1. Inspect the actual file format and schema. Confirm that it is CSV, including the delimiter, quoting, and encoding, or change the reader if it is another format.
2. Test against a representative sample, including messy rows.
3. Confirm the required fields, filter conditions, and output columns.
4. Benchmark processing time on a large enough sample, then estimate runtime for the full file from that measurement.
5. Verify available disk space for the download and the extracted output.
6. Verify output requirements: column order, encoding, headers, and how the result should be delivered.
7. Add checkpoint/resume support if a long run needs to restart without reading the whole file again.

Download the real file separately, with a checksum and enough free disk, and pass the local path to `--input`. This demo does not download anything.

## Security and privacy

Do not include real client data in this repository. The rows in `sample/input.csv` are fabricated. Keep real extracts, downloads, and credentials out of version control.
