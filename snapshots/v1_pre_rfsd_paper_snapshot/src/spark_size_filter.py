"""Match offline SPARK extracted fields to active companies and apply size filter.

No Data Loss rule: rows are never deleted. They are routed to included,
excluded or review outputs with explicit reason codes.
"""
from __future__ import annotations

import argparse
import configparser
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from paths import read_config, resolve_path, load_paths


def setup_logger() -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger("spark_size_filter")


def normalize_inn_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(r"\D", "", regex=True).str.zfill(10).str[-12:]


def parse_float(value: object) -> Optional[float]:
    text = str(value or "").strip().replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def compute_size_status(row: pd.Series, *, min_employees: int, min_revenue_rub: float) -> tuple[str, str]:
    emp = parse_float(row.get("CompanyEmployees", ""))
    rev = parse_float(row.get("CompanyRevenueRawRUB", ""))
    spark_matched = str(row.get("SparkMatched", "")).strip() == "1"
    if not spark_matched:
        return "review", "spark_unmatched"
    if emp is not None and emp >= min_employees:
        return "include", "employees>=100"
    if rev is not None and rev >= min_revenue_rub:
        return "include", "revenue>=1000000"
    if emp is not None and rev is not None and emp < min_employees and rev < min_revenue_rub:
        return "exclude", "employees<100_and_revenue<1000000"
    if emp is None and rev is None:
        return "review", "missing_employees_and_revenue"
    if emp is not None and emp < min_employees and rev is None:
        return "review", "employees<100_and_missing_revenue"
    if emp is None and rev is not None and rev < min_revenue_rub:
        return "review", "missing_employees_and_revenue<1000000"
    return "review", "size_filter_unknown"


def match_and_filter(
    active_csv: Path,
    spark_extracted_csv: Path,
    output_all_csv: Path,
    included_csv: Path,
    excluded_csv: Path,
    review_csv: Path,
    reports_dir: Path,
    excluded_root: Path,
    review_root: Path | None = None,
    *,
    min_employees: int = 100,
    min_revenue_rub: float = 1_000_000,
    logger: Optional[logging.Logger] = None,
) -> dict[str, int]:
    log = logger or setup_logger()
    reports_dir.mkdir(parents=True, exist_ok=True)
    excluded_root.mkdir(parents=True, exist_ok=True)
    review_root = Path(review_root) if review_root else excluded_root.parent / "review"
    review_root.mkdir(parents=True, exist_ok=True)
    active = pd.read_csv(active_csv, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if "INN" not in active.columns:
        active["INN"] = ""
    active["_INN_key"] = normalize_inn_series(active["INN"])

    if spark_extracted_csv.exists():
        spark = pd.read_csv(spark_extracted_csv, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    else:
        spark = pd.DataFrame(columns=["INN"])
    if "INN" not in spark.columns:
        spark["INN"] = ""
    spark["_INN_key"] = normalize_inn_series(spark["INN"])
    spark = spark[spark["_INN_key"].astype(str).str.len() >= 10].copy()
    if not spark.empty:
        spark = spark.drop_duplicates(subset=["_INN_key"], keep="first")

    # Avoid overwriting active columns without a suffix. Spark wins only for dedicated Spark/Company numeric fields.
    active_cols = set(active.columns)
    rename_map = {}
    for col in spark.columns:
        if col in {"_INN_key", "INN"}:
            continue
        if col in active_cols and col not in {
            "CompanyEmployees", "CompanyEmployeesYear", "CompanyEmployeesSource",
            "CompanyRevenue", "CompanyRevenueRawRUB", "CompanyRevenueYear", "CompanyRevenueSource",
            "CompanyBudget", "CompanyBudgetYear", "CompanyBudgetSource", "CompanyFoundedYear",
        }:
            rename_map[col] = f"Spark_{col}"
    spark = spark.rename(columns=rename_map)

    merged = active.merge(spark.drop(columns=["INN"], errors="ignore"), on="_INN_key", how="left", indicator="_spark_merge")
    merged["SparkMatched"] = (merged["_spark_merge"] == "both").astype(int).astype(str)
    merged["SparkMatchStatus"] = merged["SparkMatched"].map({"1": "matched", "0": "unmatched"}).fillna("unmatched")
    merged["SparkMatchedAt"] = datetime.now(timezone.utc).isoformat()

    # Ensure numeric columns exist.
    for col in ["CompanyEmployees", "CompanyRevenueRawRUB", "CompanyRevenue", "CompanyEmployeesYear", "CompanyRevenueYear", "CompanyFoundedYear"]:
        if col not in merged.columns:
            merged[col] = ""

    statuses = merged.apply(lambda r: compute_size_status(r, min_employees=min_employees, min_revenue_rub=min_revenue_rub), axis=1)
    merged["SizeFilterStatus"] = [s[0] for s in statuses]
    merged["SizeFilterReason"] = [s[1] for s in statuses]
    merged["ExcludedFlag"] = (merged["SizeFilterStatus"] == "exclude").astype(int).astype(str)
    merged["ExclusionReasonCode"] = merged["SizeFilterReason"].where(merged["SizeFilterStatus"] == "exclude", "")
    merged["ExclusionReasonText"] = merged["ExclusionReasonCode"]
    merged["ExclusionSource"] = merged["ExclusionReasonCode"].apply(lambda x: "spark" if x else "")
    merged["ExcludedAt"] = merged["ExclusionReasonCode"].apply(lambda x: datetime.now(timezone.utc).isoformat() if x else "")
    merged["CanBeRestored"] = merged["ExclusionReasonCode"].apply(lambda x: "1" if x else "")
    merged["RestoreCondition"] = merged["ExclusionReasonCode"].apply(lambda x: "update employees or revenue from SPARK/manual source" if x else "")

    merged = merged.drop(columns=["_INN_key", "_spark_merge"], errors="ignore")

    output_all_csv.parent.mkdir(parents=True, exist_ok=True)
    included_csv.parent.mkdir(parents=True, exist_ok=True)
    excluded_csv.parent.mkdir(parents=True, exist_ok=True)
    review_csv.parent.mkdir(parents=True, exist_ok=True)

    included = merged[merged["SizeFilterStatus"] == "include"].copy()
    excluded = merged[merged["SizeFilterStatus"] == "exclude"].copy()
    review = merged[merged["SizeFilterStatus"] == "review"].copy()

    merged.to_csv(output_all_csv, index=False, encoding="utf-8-sig")
    included.to_csv(included_csv, index=False, encoding="utf-8-sig")
    excluded.to_csv(excluded_csv, index=False, encoding="utf-8-sig")
    review.to_csv(review_csv, index=False, encoding="utf-8-sig")

    # Dead-end/review nodes classified by source/reason.
    size_dir = excluded_root / "spark_size_filter"
    size_dir.mkdir(parents=True, exist_ok=True)
    excluded.to_csv(size_dir / "employees_lt100_and_revenue_lt1m.csv", index=False, encoding="utf-8-sig")

    review_dir = review_root / "size_filter_unknown"
    review_dir.mkdir(parents=True, exist_ok=True)
    review.to_csv(review_dir / "size_filter_unknown.csv", index=False, encoding="utf-8-sig")

    unmatched_dir = review_root / "spark_unmatched"
    unmatched_dir.mkdir(parents=True, exist_ok=True)
    review[review["SizeFilterReason"] == "spark_unmatched"].to_csv(unmatched_dir / "spark_unmatched.csv", index=False, encoding="utf-8-sig")

    missing_dir = review_root / "missing_spark_fields"
    missing_dir.mkdir(parents=True, exist_ok=True)
    review[review["SizeFilterReason"].astype(str).str.contains("missing", na=False)].to_csv(missing_dir / "missing_spark_fields.csv", index=False, encoding="utf-8-sig")

    summary = {
        "active_rows": len(active),
        "spark_records": len(spark),
        "matched_rows": int((merged["SparkMatched"] == "1").sum()),
        "included_rows": len(included),
        "excluded_rows": len(excluded),
        "review_rows": len(review),
    }
    pd.DataFrame([summary]).to_csv(reports_dir / "size_filter_summary.csv", index=False, encoding="utf-8-sig")
    merged[[c for c in ["record_id", "INN", "CompanyNameOfficial", "CompanyEmployees", "CompanyEmployeesYear", "CompanyRevenue", "CompanyRevenueRawRUB", "CompanyRevenueYear", "SparkMatched", "SizeFilterStatus", "SizeFilterReason"] if c in merged.columns]].to_csv(reports_dir / "size_filter_report.csv", index=False, encoding="utf-8-sig")
    merged.groupby(["SizeFilterStatus", "SizeFilterReason"], dropna=False).size().reset_index(name="rows").to_csv(reports_dir / "size_filter_by_reason.csv", index=False, encoding="utf-8-sig")
    log.info("SPARK match/filter complete: %s", summary)
    return summary


def copy_inactive_to_excluded(inactive_csv: Path, excluded_root: Path) -> None:
    if not inactive_csv.exists():
        return
    df = pd.read_csv(inactive_csv, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if df.empty:
        return
    now = datetime.now(timezone.utc).isoformat()
    df["ExcludedFlag"] = "1"
    df["ExclusionReasonCode"] = "inactive"
    df["ExclusionReasonText"] = "company status is not ACTIVE"
    df["ExclusionSource"] = "dadata_or_spark_status"
    df["ExcludedAt"] = now
    df["CanBeRestored"] = "1"
    df["RestoreCondition"] = "status becomes ACTIVE in future validation"
    target = excluded_root / "inactive" / "all_inactive.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(target, index=False, encoding="utf-8-sig")


def main() -> int:
    parser = argparse.ArgumentParser(description="Match SPARK extract to active file and apply no-data-loss size filter.")
    parser.add_argument("--config", default="config.ini")
    parser.add_argument("--active", default=None)
    parser.add_argument("--spark", default=None)
    args = parser.parse_args()
    cfg = read_config(args.config)
    load_paths(cfg, create=True)
    active = Path(args.active) if args.active else resolve_path(cfg, "spark", "active_input_csv", "final/all_sectors_final_active.csv")
    spark = Path(args.spark) if args.spark else resolve_path(cfg, "spark", "extracted_csv", "spark/extracted/spark_extracted.csv")
    output_all = resolve_path(cfg, "spark", "matched_csv", "final/all_sectors_final_active_spark.csv")
    included = resolve_path(cfg, "spark", "included_csv", "final/all_sectors_final_active_spark_included.csv")
    excluded = resolve_path(cfg, "spark", "excluded_csv", "final/all_sectors_final_active_spark_excluded.csv")
    review = resolve_path(cfg, "spark", "review_csv", "final/review/size_filter_unknown/size_filter_unknown.csv")
    reports = resolve_path(cfg, "spark", "reports_dir", "spark/reports")
    excluded_root = resolve_path(cfg, "spark", "excluded_root", "final/excluded")
    review_root = resolve_path(cfg, "spark", "review_root", "final/review")
    min_emp = cfg.getint("spark", "min_employees", fallback=100)
    min_rev = cfg.getfloat("spark", "min_revenue_rub", fallback=1_000_000)
    copy_inactive_to_excluded(resolve_path(cfg, "spark", "inactive_input_csv", "final/all_sectors_final_inactive.csv"), excluded_root)
    match_and_filter(active, spark, output_all, included, excluded, review, reports, excluded_root, review_root, min_employees=min_emp, min_revenue_rub=min_rev, logger=setup_logger())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
