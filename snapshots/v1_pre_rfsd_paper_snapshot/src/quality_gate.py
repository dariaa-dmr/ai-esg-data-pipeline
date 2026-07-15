"""Quality gate for final pipeline outputs.

The script does not modify data. It writes a PASS/FAIL report and highlights
where rows are waiting in review/excluded nodes. It can be run before export or
before presentation/reporting.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from paths import read_config, resolve_path, load_paths


def read_csv_safe(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()


def parse_float(v: object):
    t = str(v or "").strip().replace(" ", "").replace(",", ".")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def count_export_rows(export_dir: Path) -> int:
    total = 0
    if not export_dir.exists():
        return 0
    for p in export_dir.rglob("*.csv"):
        try:
            total += len(pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8-sig"))
        except Exception:
            pass
    return total


def add_check(rows: list[dict[str, Any]], name: str, status: str, details: str = "") -> None:
    rows.append({"check": name, "status": status, "details": details})




def choose_expected_export_source(cfg) -> tuple[Path, str]:
    """Use the same [export] input_mode logic as export_by_category.py.

    v5 bugfix: quality_gate used to prefer described whenever that file existed,
    even when [export] input_mode=spark_included. That made checks compare
    export rows against an outdated described file.
    """
    mode = cfg.get("export", "input_mode", fallback="auto").strip().lower()
    candidates = {
        "described": resolve_path(cfg, "descriptions", "output_csv", "final/all_sectors_final_active_described.csv"),
        "spark_included": resolve_path(cfg, "spark", "included_csv", "final/all_sectors_final_active_spark_included.csv"),
        "active": resolve_path(cfg, "spark", "active_input_csv", "final/all_sectors_final_active.csv"),
        "custom": resolve_path(cfg, "export", "input_csv", "final/all_sectors_final_active_described.csv"),
    }
    if mode in {"described", "spark_included", "active", "custom"}:
        return candidates[mode], mode
    # auto mode: described -> spark_included -> active, first existing non-empty file
    for key in ("described", "spark_included", "active"):
        p = candidates[key]
        if p.exists() and p.stat().st_size > 0:
            return p, f"auto:{key}"
    return candidates["active"], "auto:active"


def run_quality_gate(cfg_path: str = "config.ini") -> tuple[str, pd.DataFrame]:
    cfg = read_config(cfg_path)
    paths = load_paths(cfg, create=True)
    reports_dir = paths.reports
    reports_dir.mkdir(parents=True, exist_ok=True)

    active = read_csv_safe(resolve_path(cfg, "spark", "active_input_csv", "final/all_sectors_final_active.csv"))
    spark_all = read_csv_safe(resolve_path(cfg, "spark", "matched_csv", "final/all_sectors_final_active_spark.csv"))
    included = read_csv_safe(resolve_path(cfg, "spark", "included_csv", "final/all_sectors_final_active_spark_included.csv"))
    excluded = read_csv_safe(resolve_path(cfg, "spark", "excluded_csv", "final/all_sectors_final_active_spark_excluded.csv"))
    review = read_csv_safe(resolve_path(cfg, "spark", "review_csv", "final/review/size_filter_unknown/size_filter_unknown.csv"))
    expected_export_path, expected_export_source = choose_expected_export_source(cfg)
    expected_export_df = read_csv_safe(expected_export_path)
    export_dir = paths.export_by_category

    rows: list[dict[str, Any]] = []
    add_check(rows, "active_file_exists", "PASS" if not active.empty else "FAIL", f"rows={len(active)}")

    if not spark_all.empty:
        expected = len(included) + len(excluded) + len(review)
        add_check(rows, "spark_partition_sum", "PASS" if len(spark_all) == expected else "FAIL", f"spark_all={len(spark_all)} included={len(included)} excluded={len(excluded)} review={len(review)}")
    else:
        add_check(rows, "spark_outputs_exist", "WARN", "SPARK outputs not found or empty")

    for name, df in [("active", active), ("spark_all", spark_all), ("included", included)]:
        if df.empty:
            continue
        if "record_id" in df.columns:
            missing = int((df["record_id"].astype(str).str.strip() == "").sum())
            add_check(rows, f"{name}_record_id_present", "PASS" if missing == 0 else "FAIL", f"missing={missing}")
        else:
            add_check(rows, f"{name}_record_id_present", "FAIL", "record_id column missing")
        if "INN" in df.columns:
            missing = int((df["INN"].astype(str).str.replace(r"\D", "", regex=True).str.len() == 0).sum())
            add_check(rows, f"{name}_inn_present", "PASS" if missing == 0 else "FAIL", f"missing={missing}")

    bad_included = 0
    if not included.empty and {"CompanyEmployees", "CompanyRevenueRawRUB"}.issubset(set(included.columns)):
        for _, r in included.iterrows():
            emp = parse_float(r.get("CompanyEmployees", ""))
            rev = parse_float(r.get("CompanyRevenueRawRUB", ""))
            if emp is not None and rev is not None and emp < 100 and rev < 1_000_000:
                bad_included += 1
        add_check(rows, "included_size_filter", "PASS" if bad_included == 0 else "FAIL", f"bad_rows={bad_included}")

    export_rows = count_export_rows(export_dir)
    if export_rows:
        expected = len(expected_export_df)
        source = expected_export_source
        source_path = str(expected_export_path)
        add_check(
            rows,
            "export_row_count",
            "PASS" if expected == export_rows else "FAIL",
            f"export_rows={export_rows} expected={expected} source={source} path={source_path}",
        )
    else:
        add_check(rows, "export_exists", "WARN", "export_by_category has no csv rows")

    # Routing issue report should be empty for a clean final export; warn rather than fail.
    routing_issues = read_csv_safe(reports_dir / "export_issues.csv")
    if not routing_issues.empty:
        add_check(rows, "routing_issues", "WARN", f"rows={len(routing_issues)}; see final/review/routing_issues")

    report = pd.DataFrame(rows)
    overall = "PASS" if not (report["status"] == "FAIL").any() else "FAIL"
    report.to_csv(reports_dir / "quality_gate_report.csv", index=False, encoding="utf-8-sig")
    (reports_dir / "quality_gate_status.txt").write_text(overall, encoding="utf-8")
    return overall, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run quality checks for pipeline outputs.")
    parser.add_argument("--config", default="config.ini")
    args = parser.parse_args()
    overall, report = run_quality_gate(args.config)
    print(f"QUALITY_GATE={overall}")
    print(report.to_string(index=False))
    return 0 if overall == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
