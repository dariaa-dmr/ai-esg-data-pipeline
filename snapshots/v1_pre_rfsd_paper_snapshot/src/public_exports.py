"""
public_exports.py — strict comma map export.

Run from project root:
    python public_exports.py --config config.ini

Input:
    final/all_sectors_final_active_described.csv

Output for map:
    final/public/map/map_upload_ready_COMMA_STRICT_FLAT.csv

This script does NOT call YandexGPT.
It removes commas inside fields only in the map export, so the file can be split by comma safely.
"""

from __future__ import annotations

import argparse
import configparser
import csv
import re
from pathlib import Path


def clean(value: object, max_len: int | None = None) -> str:
    s = re.sub(r"[\r\n\t]+", " ", str(value or ""))
    s = s.replace(",", " ")
    s = s.replace('"', "'")
    s = s.replace(";", " ")
    s = s.replace("|", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if max_len and len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    return s


def choose(row: dict[str, str], *cols: str) -> str:
    for col in cols:
        value = str(row.get(col, "") or "").strip()
        if value:
            return value
    return ""


def coord(value: object) -> str:
    s = str(value or "").strip().replace(",", ".")
    try:
        x = float(s)
    except Exception:
        return ""
    return f"{x:.6f}".rstrip("0").rstrip(".")


def read_config(path: str | Path) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    read_files = cfg.read(path, encoding="utf-8")
    if not read_files:
        raise FileNotFoundError(f"Config not found: {path}")
    return cfg


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            delimiter=",",
            quoting=csv.QUOTE_NONE,
            escapechar="\\",
            lineterminator="\r\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def validate_physical(path: Path, expected_commas: int) -> tuple[int, int, int]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    bad = sum(1 for line in lines if line.count(",") != expected_commas)
    return len(lines), max(0, len(lines) - 1), bad


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.ini")
    parser.add_argument("--input", default="final/all_sectors_final_active_described.csv")
    args = parser.parse_args()

    _cfg = read_config(args.config)
    source = read_csv(Path(args.input))

    cols = [
        "id",
        "title",
        "lat",
        "lon",
        "address",
        "description",
        "inn",
        "region",
        "industry",
        "subindustry",
        "website",
        "description_status",
    ]

    out = []
    for i, row in enumerate(source, start=1):
        out.append({
            "id": clean(choose(row, "record_id") or str(i), 60),
            "title": clean(choose(row, "CompanyNameOfficial", "CompanyName"), 220),
            "lat": coord(row.get("lat_dadata", "")),
            "lon": coord(row.get("lon_dadata", "")),
            "address": clean(choose(row, "Address_dadata", "SparkAddress"), 320),
            "description": clean(row.get("CompanyDescription", ""), 1400),
            "inn": clean(row.get("INN", ""), 20),
            "region": clean(choose(row, "RegionName", "RegionRegistration"), 120),
            "industry": clean(row.get("Industry", ""), 180),
            "subindustry": clean(row.get("Subindustry", ""), 200),
            "website": clean(choose(row, "Website", "SparkWebsite"), 180),
            "description_status": clean(row.get("description_status", ""), 60),
        })

    map_path = Path("final/public/map/map_upload_ready_COMMA_STRICT_FLAT.csv")
    write_csv(map_path, cols, out)

    report_dir = Path("final/public/reports")
    report_dir.mkdir(parents=True, exist_ok=True)

    lines, data_rows, bad_lines = validate_physical(map_path, expected_commas=len(cols) - 1)
    rows_with_coordinates = sum(1 for row in out if row["lat"] and row["lon"])

    report = (
        "MAP STRICT VALIDATION\n"
        f"file={map_path}\n"
        f"lines={lines}\n"
        f"data_rows={data_rows}\n"
        f"rows_total={len(out)}\n"
        f"rows_with_coordinates={rows_with_coordinates}\n"
        f"expected_commas_per_line={len(cols)-1}\n"
        f"strict_bad_physical_lines={bad_lines}\n"
    )
    (report_dir / "map_strict_validation.txt").write_text(report, encoding="utf-8")

    status = "PUBLIC_EXPORTS=PASS" if len(out) == data_rows and bad_lines == 0 else "PUBLIC_EXPORTS=WARN"
    print(status)
    print(f"rows_total={len(out)}")
    print(f"rows_with_coordinates={rows_with_coordinates}")
    print(f"strict_csv={map_path}")
    print(f"strict_bad_physical_lines={bad_lines}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
