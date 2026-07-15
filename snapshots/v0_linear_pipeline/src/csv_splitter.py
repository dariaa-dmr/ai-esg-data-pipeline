"""Robust CSV splitter: separates clean rows from dirty rows without dropping data.

Expected schema:
Sector, Industry, Subindustry, CompanyName, CompanyNameOfficial, INN,
RegionRegistration, RegionHeadOffice, RegionOperation, Description, URL, Source
"""
from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional

import chardet
import pandas as pd

try:
    import clevercsv  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    clevercsv = None

EXPECTED_COLUMNS = [
    "Sector",
    "Industry",
    "Subindustry",
    "CompanyName",
    "CompanyNameOfficial",
    "INN",
    "RegionRegistration",
    "RegionHeadOffice",
    "RegionOperation",
    "Description",
    "URL",
    "Source",
]
EXPECTED_NCOLS = len(EXPECTED_COLUMNS)
INN_RE = re.compile(r"(?<!\d)(\d{10}|\d{12})(?!\d)")
URL_RE = re.compile(r"(?:https?://|www\.|[a-zA-Z0-9-]+\.(?:ru|рф|com|org|net|su|by|kz|io))(?:[^\s,;]*)", re.I)


@dataclass
class SplitResult:
    source_path: Path
    clean_path: Path
    dirty_path: Path
    clean_rows: int
    dirty_rows: int
    total_records: int
    encoding: str
    delimiter: str


def detect_encoding(path: str | Path, sample_size: int = 256_000) -> str:
    """Detect file encoding using chardet. Falls back to utf-8-sig."""
    path = Path(path)
    raw = path.read_bytes()[:sample_size]
    result = chardet.detect(raw) or {}
    enc = result.get("encoding") or "utf-8-sig"
    # Windows CSV from Excel is often CP1251; chardet may return MacCyrillic on small samples.
    if enc.lower().replace("_", "-") in {"ascii", "utf-8"}:
        return "utf-8-sig"
    return enc


def _read_text_sample(path: Path, encoding: str, sample_size: int = 128_000) -> str:
    with path.open("r", encoding=encoding, errors="replace", newline="") as f:
        return f.read(sample_size)


def detect_delimiter(path: str | Path, encoding: Optional[str] = None) -> str:
    """Detect delimiter via clevercsv, csv.Sniffer, then simple heuristics."""
    path = Path(path)
    encoding = encoding or detect_encoding(path)
    sample = _read_text_sample(path, encoding)

    if clevercsv is not None:
        try:
            dialect = clevercsv.Sniffer().sniff(sample)
            if dialect and dialect.delimiter:
                return dialect.delimiter
        except Exception:
            pass

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t", "|"])
        if dialect.delimiter:
            return dialect.delimiter
    except Exception:
        pass

    candidates = [",", ";", "\t", "|"]
    lines = [ln for ln in sample.splitlines()[:50] if ln.strip()]
    scores: dict[str, float] = {}
    for delim in candidates:
        counts = [len(split_quoted_aware(ln, delim)) for ln in lines]
        if not counts:
            scores[delim] = 0
            continue
        # Prefer delimiters producing around the expected width with low variance.
        near_expected = sum(1 for c in counts if 2 <= c <= EXPECTED_NCOLS + 10)
        variance_penalty = max(counts) - min(counts) if len(counts) > 1 else 0
        scores[delim] = near_expected * 10 - variance_penalty + sum(counts) / max(len(counts), 1)
    return max(scores, key=scores.get) if scores else ","


def strip_bom(value: str) -> str:
    return value.lstrip("\ufeff")


def sanitize_raw_record(text: str) -> str:
    """Low-risk cleanup before parsing. Does not remove field content."""
    text = text.replace("\x00", "")
    text = text.replace("[https://", "https://").replace("[http://", "http://")
    # Keep closing bracket if it may be part of text, but remove obvious URL wrappers.
    text = re.sub(r"(https?://[^\s\]]+)\]", r"\1", text)
    return text


def count_unescaped_quotes(text: str) -> int:
    count = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            i += 2
            continue
        if ch == '"':
            # CSV escaped double quote inside a quoted field: "".
            if i + 1 < len(text) and text[i + 1] == '"':
                i += 2
                continue
            count += 1
        i += 1
    return count


def split_quoted_aware(text: str, delimiter: str = ",") -> list[str]:
    """Split by delimiter while ignoring delimiters inside double quotes.

    This is intentionally forgiving and works even if quotes are not fully valid.
    """
    fields: list[str] = []
    buf: list[str] = []
    in_quotes = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            if in_quotes and i + 1 < len(text) and text[i + 1] == '"':
                buf.append('"')
                i += 2
                continue
            in_quotes = not in_quotes
            buf.append(ch)
        elif ch == delimiter and not in_quotes:
            fields.append("".join(buf).strip().strip("\r\n"))
            buf = []
        else:
            buf.append(ch)
        i += 1
    fields.append("".join(buf).strip().strip("\r\n"))
    return fields


def _clean_field(value: object) -> str:
    text = "" if value is None else str(value)
    text = strip_bom(text).strip()
    # Remove one layer of symmetrical quotes only; csv.reader already unquotes correctly.
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    return text.strip()


def _parse_with_csv_reader(text: str, delimiter: str, escapechar: Optional[str] = None) -> Optional[list[str]]:
    try:
        reader = csv.reader(
            [text],
            delimiter=delimiter,
            quotechar='"',
            doublequote=True,
            escapechar=escapechar,
            strict=False,
        )
        row = next(reader)
        return [_clean_field(x) for x in row]
    except Exception:
        return None


def _reconstruct_tail_after_inn(before_inn: list[str], inn: str, after_inn: list[str], delimiter: str) -> list[str]:
    """Reconstruct the 12-column schema after an INN was identified.

    before_inn -> expected first five columns.
    after_inn  -> expected six columns after INN.
    Extra commas are most often in CompanyNameOfficial, Description, Source.
    """
    # First five columns before INN.
    if len(before_inn) == 5:
        prefix = before_inn
    elif len(before_inn) > 5:
        # Preserve sector/industry/subindustry/company short name and merge the rest into official name.
        prefix = before_inn[:4] + [delimiter.join(before_inn[4:])]
    else:
        prefix = before_inn + [""] * (5 - len(before_inn))

    # Six columns after INN: RegionRegistration, RegionHeadOffice, RegionOperation, Description, URL, Source.
    if len(after_inn) == 6:
        suffix = after_inn
    elif len(after_inn) > 6:
        fixed = after_inn[:3]
        tail = after_inn[3:]
        url_idx = next((i for i, v in enumerate(tail) if URL_RE.search(v or "")), None)
        if url_idx is not None:
            description = delimiter.join(tail[:url_idx]).strip()
            url = tail[url_idx].strip()
            source = delimiter.join(tail[url_idx + 1 :]).strip()
            suffix = fixed + [description, url, source]
        else:
            # No obvious URL; assume extra commas are inside Description.
            description = delimiter.join(tail[:-2]).strip() if len(tail) >= 2 else delimiter.join(tail).strip()
            url = tail[-2].strip() if len(tail) >= 2 else ""
            source = tail[-1].strip() if len(tail) >= 1 else ""
            suffix = fixed + [description, url, source]
    else:
        suffix = after_inn + [""] * (6 - len(after_inn))

    return [_clean_field(x) for x in (prefix + [inn] + suffix)]


def repair_fields(fields: list[str], delimiter: str = ",") -> tuple[Optional[list[str]], str]:
    """Try to coerce parsed fields into exactly EXPECTED_NCOLS fields.

    Returns (fields_or_none, reason).
    """
    fields = [_clean_field(f) for f in fields]

    if len(fields) == EXPECTED_NCOLS:
        return fields, "parsed_exactly"

    # Use INN as an anchor if possible.
    inn_idx = None
    inn_value = ""
    for i, field in enumerate(fields):
        m = INN_RE.search(field or "")
        if m:
            inn_idx = i
            inn_value = m.group(1)
            break
    if inn_idx is not None:
        repaired = _reconstruct_tail_after_inn(fields[:inn_idx], inn_value, fields[inn_idx + 1 :], delimiter)
        if len(repaired) == EXPECTED_NCOLS:
            return repaired, f"repaired_by_inn_anchor_original_cols={len(fields)}"

    if len(fields) > EXPECTED_NCOLS:
        # If no INN anchor, apply a conservative fallback: keep first 11 fields and merge the rest into Source.
        repaired = fields[: EXPECTED_NCOLS - 1] + [delimiter.join(fields[EXPECTED_NCOLS - 1 :])]
        return [_clean_field(x) for x in repaired], f"merged_excess_into_source_original_cols={len(fields)}"

    if len(fields) < EXPECTED_NCOLS:
        repaired = fields + [""] * (EXPECTED_NCOLS - len(fields))
        return [_clean_field(x) for x in repaired], f"padded_missing_fields_original_cols={len(fields)}"

    return None, f"unrepairable_original_cols={len(fields)}"


def parse_record(text: str, delimiter: str = ",") -> tuple[Optional[list[str]], str]:
    """Parse one logical record into exactly EXPECTED_NCOLS fields, if possible."""
    raw = sanitize_raw_record(text)
    attempts: list[tuple[str, Optional[list[str]]]] = [
        ("csv_reader", _parse_with_csv_reader(raw, delimiter, escapechar=None)),
        ("csv_reader_escape", _parse_with_csv_reader(raw, delimiter, escapechar="\\")),
        ("quoted_aware_split", split_quoted_aware(raw, delimiter)),
    ]
    seen: set[tuple[str, ...]] = set()
    reasons: list[str] = []
    for method, fields in attempts:
        if fields is None:
            reasons.append(f"{method}:failed")
            continue
        key = tuple(fields)
        if key in seen:
            continue
        seen.add(key)
        repaired, reason = repair_fields(fields, delimiter)
        reasons.append(f"{method}:{reason}")
        if repaired is not None and len(repaired) == EXPECTED_NCOLS:
            return repaired, f"{method}:{reason}"
    return None, ";".join(reasons) or "no_parser_succeeded"


def iter_logical_records(
    path: str | Path,
    encoding: str,
    delimiter: str = ",",
    expected_cols: int = EXPECTED_NCOLS,
    max_record_lines: int = 10,
) -> Iterator[tuple[int, int, str]]:
    """Yield (record_no, first_physical_line_no, record_text).

    Records with multiline quoted fields are accumulated. If a record remains
    broken for too long, it is yielded as dirty candidate rather than swallowing
    the rest of the file.
    """
    path = Path(path)
    record_no = 0
    buffer: list[str] = []
    first_line_no = 1

    with path.open("r", encoding=encoding, errors="replace", newline="") as f:
        for line_no, line in enumerate(f, start=1):
            if not buffer:
                first_line_no = line_no
            buffer.append(line)
            text = "".join(buffer)
            delim_count = text.count(delimiter)
            quotes_even = (count_unescaped_quotes(text) % 2 == 0)
            physical_lines = len(buffer)

            # Yield when the record looks complete. A malformed single physical
            # line with enough delimiters should be yielded immediately instead
            # of being merged with the next company.
            enough_separators = delim_count >= expected_cols - 1
            if quotes_even or enough_separators or physical_lines >= max_record_lines:
                if text.strip():
                    record_no += 1
                    yield record_no, first_line_no, text
                buffer = []

    if buffer and "".join(buffer).strip():
        record_no += 1
        yield record_no, first_line_no, "".join(buffer)


def _looks_like_header(row: list[str]) -> bool:
    normalized = [re.sub(r"\s+", "", x).lower() for x in row]
    expected = [x.lower() for x in EXPECTED_COLUMNS]
    hits = sum(1 for x, y in zip(normalized, expected) if x == y.lower())
    return hits >= max(5, EXPECTED_NCOLS // 2)


def split_clean_dirty(
    input_csv: str | Path,
    clean_output: str | Path,
    dirty_output: str | Path,
    delimiter: Optional[str] = None,
    encoding: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
    write_audit: bool = True,
) -> SplitResult:
    """Split a CSV into clean and dirty files.

    Clean file receives exactly EXPECTED_COLUMNS.
    Dirty file receives EXPECTED_COLUMNS + raw_line + dirty_reason + source_file + physical_line.
    """
    log = logger or logging.getLogger(__name__)
    input_path = Path(input_csv)
    clean_path = Path(clean_output)
    dirty_path = Path(dirty_output)
    clean_path.parent.mkdir(parents=True, exist_ok=True)
    dirty_path.parent.mkdir(parents=True, exist_ok=True)

    encoding = encoding or detect_encoding(input_path)
    delimiter = delimiter or detect_delimiter(input_path, encoding)

    clean_rows: list[list[str]] = []
    dirty_rows: list[dict[str, str]] = []
    audit_rows: list[dict[str, str]] = []
    header_seen = False
    total_records = 0

    for record_no, physical_line, raw_record in iter_logical_records(input_path, encoding, delimiter):
        total_records += 1
        parsed, reason = parse_record(raw_record, delimiter)
        if parsed is not None and not header_seen and _looks_like_header(parsed):
            header_seen = True
            audit_rows.append({
                "record_no": str(record_no),
                "physical_line": str(physical_line),
                "status": "header",
                "reason": reason,
            })
            continue

        if parsed is not None:
            clean_rows.append(parsed)
            audit_rows.append({
                "record_no": str(record_no),
                "physical_line": str(physical_line),
                "status": "clean",
                "reason": reason,
            })
        else:
            partial = split_quoted_aware(sanitize_raw_record(raw_record), delimiter)
            partial = (partial + [""] * EXPECTED_NCOLS)[:EXPECTED_NCOLS]
            row = {col: _clean_field(partial[i]) for i, col in enumerate(EXPECTED_COLUMNS)}
            row.update({
                "raw_line": raw_record.rstrip("\r\n"),
                "dirty_reason": reason,
                "source_file": input_path.name,
                "physical_line": str(physical_line),
            })
            dirty_rows.append(row)
            audit_rows.append({
                "record_no": str(record_no),
                "physical_line": str(physical_line),
                "status": "dirty",
                "reason": reason,
            })

    clean_df = pd.DataFrame(clean_rows, columns=EXPECTED_COLUMNS)
    dirty_df = pd.DataFrame(dirty_rows, columns=EXPECTED_COLUMNS + ["raw_line", "dirty_reason", "source_file", "physical_line"])

    clean_df.to_csv(clean_path, index=False, encoding="utf-8-sig")
    dirty_df.to_csv(dirty_path, index=False, encoding="utf-8-sig")

    if write_audit:
        audit_path = clean_path.with_name(clean_path.stem + "_audit.csv")
        pd.DataFrame(audit_rows).to_csv(audit_path, index=False, encoding="utf-8-sig")

    log.info(
        "split file=%s encoding=%s delimiter=%r total_records=%s clean=%s dirty=%s",
        input_path.name,
        encoding,
        delimiter,
        total_records,
        len(clean_rows),
        len(dirty_rows),
    )

    return SplitResult(
        source_path=input_path,
        clean_path=clean_path,
        dirty_path=dirty_path,
        clean_rows=len(clean_rows),
        dirty_rows=len(dirty_rows),
        total_records=total_records,
        encoding=encoding,
        delimiter=delimiter,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Split CSV into clean and dirty rows.")
    parser.add_argument("input_csv")
    parser.add_argument("clean_output")
    parser.add_argument("dirty_output")
    parser.add_argument("--delimiter", default=None)
    parser.add_argument("--encoding", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = split_clean_dirty(
        args.input_csv,
        args.clean_output,
        args.dirty_output,
        delimiter=args.delimiter,
        encoding=args.encoding,
    )
    print(result)
