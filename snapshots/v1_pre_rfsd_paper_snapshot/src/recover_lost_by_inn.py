"""Recovery helper for companies lost because INN moved into the wrong column.

The script scans raw CSV files line by line, extracts likely INNs by regex,
compares them with the final dataset, and writes candidates for retry/manual fix.

Usage:
python recover_lost_by_inn.py --sources incoming archive raw_files --final final/all_sectors_final.csv --out recovery_candidates.csv --only-missing
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Iterable

import chardet
import pandas as pd

INN_RE = re.compile(r"(?<!\d)(\d{10}|\d{12})(?!\d)")
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


def detect_encoding(path: Path) -> str:
    raw = path.read_bytes()[:256_000]
    result = chardet.detect(raw) or {}
    return result.get("encoding") or "utf-8-sig"


def load_final_inns(final_csv: Path) -> set[str]:
    if not final_csv.exists():
        return set()
    df = pd.read_csv(final_csv, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if "INN" not in df.columns:
        return set()
    return {"".join(ch for ch in str(x) if ch.isdigit()) for x in df["INN"] if str(x).strip()}


def iter_csv_files(sources: Iterable[Path]) -> Iterable[Path]:
    for source in sources:
        if source.is_file() and source.suffix.lower() == ".csv":
            yield source
        elif source.is_dir():
            yield from sorted(source.rglob("*.csv"))


def scan_sources(source_paths: list[Path], final_inns: set[str], only_missing: bool) -> pd.DataFrame:
    rows = []
    for csv_path in iter_csv_files(source_paths):
        # Avoid scanning outputs to prevent noise unless user explicitly passed only that directory.
        if any(part.lower() in {"clean", "enriched", "geo", "final", "logs", "cache"} for part in csv_path.parts):
            continue
        enc = detect_encoding(csv_path)
        try:
            f = csv_path.open("r", encoding=enc, errors="replace", newline="")
        except Exception:
            continue
        with f:
            for line_no, raw_line in enumerate(f, start=1):
                inns = sorted(set(INN_RE.findall(raw_line)))
                for inn in inns:
                    already = inn in final_inns
                    if only_missing and already:
                        continue
                    rows.append(
                        {
                            "source_file": str(csv_path),
                            "line_number": line_no,
                            "INN_candidate": inn,
                            "already_in_final": "1" if already else "0",
                            "recovery_reason": "inn_found_in_raw_line_missing_in_final" if not already else "inn_already_in_final",
                            "raw_line": raw_line.rstrip("\r\n"),
                        }
                    )
    return pd.DataFrame(rows)


def write_retry_template(candidates: pd.DataFrame, output_csv: Path) -> None:
    """Create an Excel-friendly file for manual reconstruction.

    Operator can fill the 12 target columns and put the corrected file into retry/.
    """
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for _, row in candidates.iterrows():
        item = {col: "" for col in EXPECTED_COLUMNS}
        item["INN"] = row.get("INN_candidate", "")
        item["Source"] = row.get("source_file", "")
        item["raw_line"] = row.get("raw_line", "")
        item["recovery_reason"] = row.get("recovery_reason", "")
        rows.append(item)
    pd.DataFrame(rows, columns=EXPECTED_COLUMNS + ["raw_line", "recovery_reason"]).to_csv(output_csv, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)


def main() -> int:
    parser = argparse.ArgumentParser(description="Find raw rows with INNs missing from final dataset.")
    parser.add_argument("--sources", nargs="+", required=True, help="Raw source files/directories to scan")
    parser.add_argument("--final", required=True, help="Final CSV with INN column")
    parser.add_argument("--out", default="recovery_candidates.csv", help="Output candidate CSV")
    parser.add_argument("--retry-template", default="retry/recovered_by_inn_retry_template.csv", help="Manual retry template CSV")
    parser.add_argument("--only-missing", action="store_true", help="Output only INNs absent from final CSV")
    args = parser.parse_args()

    source_paths = [Path(x).expanduser().resolve() for x in args.sources]
    final_csv = Path(args.final).expanduser().resolve()
    out_csv = Path(args.out).expanduser().resolve()
    retry_template = Path(args.retry_template).expanduser().resolve()

    final_inns = load_final_inns(final_csv)
    candidates = scan_sources(source_paths, final_inns, args.only_missing)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(out_csv, index=False, encoding="utf-8-sig")
    write_retry_template(candidates, retry_template)

    missing_count = int((candidates.get("already_in_final", pd.Series(dtype=str)) == "0").sum()) if not candidates.empty else 0
    print(f"candidates={len(candidates)} missing_from_final={missing_count} out={out_csv} retry_template={retry_template}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
