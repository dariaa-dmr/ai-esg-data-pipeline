"""Manual/offline SPARK loop orchestrator.

Expected workflow:
1. Put ZIP/XML/XLSX/CSV/TXT files received from the person with SPARK access into spark/incoming/.
2. Run: python spark_pipeline.py --config config.ini
3. The script extracts SPARK fields, matches them to active companies, applies the size filter,
   and writes included/excluded/review outputs without deleting any row.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from paths import read_config, resolve_path, load_paths
from spark_structured_parser import setup_logger, unpack_archives, extract_spark_files
from spark_size_filter import match_and_filter, copy_inactive_to_excluded


def main() -> int:
    parser = argparse.ArgumentParser(description="Run offline SPARK extraction + match + size filter.")
    parser.add_argument("--config", default="config.ini")
    parser.add_argument("--clear-unpacked", action="store_true")
    args = parser.parse_args()
    cfg = read_config(args.config)
    load_paths(cfg, create=True)
    log = setup_logger()

    incoming = resolve_path(cfg, "spark", "incoming_dir", "spark/incoming")
    unpacked = resolve_path(cfg, "spark", "unpacked_dir", "spark/unpacked")
    extracted = resolve_path(cfg, "spark", "extracted_csv", "spark/extracted/spark_extracted.csv")
    reports = resolve_path(cfg, "spark", "reports_dir", "spark/reports")

    unpack_archives(incoming, unpacked, clear=args.clear_unpacked, logger=log)
    extract_spark_files(unpacked, extracted, reports, logger=log)

    active = resolve_path(cfg, "spark", "active_input_csv", "final/all_sectors_final_active.csv")
    output_all = resolve_path(cfg, "spark", "matched_csv", "final/all_sectors_final_active_spark.csv")
    included = resolve_path(cfg, "spark", "included_csv", "final/all_sectors_final_active_spark_included.csv")
    excluded = resolve_path(cfg, "spark", "excluded_csv", "final/all_sectors_final_active_spark_excluded.csv")
    review = resolve_path(cfg, "spark", "review_csv", "final/review/size_filter_unknown/size_filter_unknown.csv")
    excluded_root = resolve_path(cfg, "spark", "excluded_root", "final/excluded")
    review_root = resolve_path(cfg, "spark", "review_root", "final/review")
    min_emp = cfg.getint("spark", "min_employees", fallback=100)
    min_rev = cfg.getfloat("spark", "min_revenue_rub", fallback=1_000_000)
    copy_inactive_to_excluded(resolve_path(cfg, "spark", "inactive_input_csv", "final/all_sectors_final_inactive.csv"), excluded_root)
    match_and_filter(active, extracted, output_all, included, excluded, review, reports, excluded_root, review_root, min_employees=min_emp, min_revenue_rub=min_rev, logger=log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
