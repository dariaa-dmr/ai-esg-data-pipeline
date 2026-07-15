"""Create an offline SPARK request package from the active company dataset.

The project does not call SPARK API. This script prepares a clean list of INNs
and context columns that can be sent to a person with SPARK access. It keeps
both a unique-INN request file and a row-level file, because one INN may appear
in several sectors/subindustries.
"""
from __future__ import annotations

import argparse
import configparser
from pathlib import Path

import pandas as pd

from paths import read_config, resolve_path, load_paths


def normalize_inn(value: object) -> str:
    import re
    digits = re.sub(r"\D", "", str(value or ""))
    return digits


def export_spark_request(active_csv: Path, request_dir: Path) -> dict[str, int]:
    request_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(active_csv, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if "INN" not in df.columns:
        df["INN"] = ""
    df["INN_normalized"] = df["INN"].map(normalize_inn)

    context_cols = [
        "record_id", "INN", "INN_normalized", "CompanyNameOfficial", "CompanyName",
        "RegionRegistration", "RegionHeadOffice", "RegionOperation", "Sector", "Industry",
        "Subindustry", "status_dadata", "OKVED_dadata", "Address_dadata",
    ]
    row_cols = [c for c in context_cols if c in df.columns]
    row_level = df[row_cols].copy()
    row_level.to_csv(request_dir / "spark_request_rows.csv", index=False, encoding="utf-8-sig")

    agg_spec = {}
    for c in row_cols:
        if c not in {"INN", "INN_normalized"}:
            agg_spec[c] = lambda s: " | ".join(dict.fromkeys([str(x).strip() for x in s if str(x).strip()]))[:2000]
    unique = df[df["INN_normalized"].str.len().isin([10, 12])].groupby("INN_normalized", as_index=False).agg(agg_spec)
    unique = unique.rename(columns={"INN_normalized": "INN"})
    unique.insert(0, "request_no", range(1, len(unique) + 1))
    unique.to_csv(request_dir / "spark_request_unique_inn.csv", index=False, encoding="utf-8-sig")

    pd.DataFrame([{
        "active_rows": len(df),
        "row_request_rows": len(row_level),
        "unique_inn_request_rows": len(unique),
        "missing_inn_rows": int((df["INN_normalized"].str.len() == 0).sum()),
    }]).to_csv(request_dir / "spark_request_summary.csv", index=False, encoding="utf-8-sig")
    return {"active_rows": len(df), "unique_inn": len(unique), "missing_inn_rows": int((df["INN_normalized"].str.len() == 0).sum())}


def main() -> int:
    parser = argparse.ArgumentParser(description="Export INN request files for manual SPARK processing.")
    parser.add_argument("--config", default="config.ini")
    parser.add_argument("--active", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    cfg = read_config(args.config)
    load_paths(cfg, create=True)
    active = Path(args.active) if args.active else resolve_path(cfg, "spark", "active_input_csv", "final/all_sectors_final_active.csv")
    request_dir = Path(args.out) if args.out else resolve_path(cfg, "spark", "request_dir", "spark/request")
    summary = export_spark_request(active, request_dir)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
