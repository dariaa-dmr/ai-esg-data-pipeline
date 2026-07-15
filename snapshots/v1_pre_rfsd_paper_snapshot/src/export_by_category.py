"""Export active companies into Region/Industry/Subindustry folders.

The script reads the final active/described CSV and never silently drops rows.
Rows with missing routing fields are exported into technical __MISSING__ folders
and listed in final/reports/export_issues.csv.
"""
from __future__ import annotations

import argparse
import configparser
import logging
import shutil
import re
from pathlib import Path

import pandas as pd

from paths import read_config, load_paths, resolve_path
from regions_reference import federal_district_for_region, normalize_region_name, region_from_inn, configure_region_reference
from row_identity import dedup_key, normalize_inn
from safe_filename import safe_filename
from manual_overrides import apply_routing_overrides

ROUTING_COLS = ["RegionRegistration", "Industry", "Subindustry"]
SUPPLEMENT_COLS = [
    "RegionRegistration", "RegionHeadOffice", "RegionOperation", "Sector", "Industry", "Subindustry",
    "Description", "URL", "Source", "source_file", "source_row_no", "raw_line", "parse_status", "parse_reason",
]


def setup_logger() -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger("export_by_category")


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def sanitize_for_csv(df: pd.DataFrame) -> pd.DataFrame:
    """Remove invalid surrogate characters that may come from legacy ZIP names."""
    def clean_value(v):
        if not isinstance(v, str):
            return v
        return re.sub(r"[\ud800-\udfff]", "_", v)
    return df.map(clean_value) if hasattr(df, "map") else df.applymap(clean_value)


def load_clean_reference(clean_dir: Path) -> pd.DataFrame:
    frames = []
    for f in sorted(clean_dir.glob("*_clean.csv")):
        if f.name.endswith("_audit.csv"):
            continue
        try:
            df = read_csv(f)
            if "source_file" not in df.columns:
                df["source_file"] = f.name.replace("_clean.csv", ".csv")
            frames.append(df)
        except Exception:
            continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def supplement_from_clean(df: pd.DataFrame, clean_df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if clean_df.empty:
        return df, 0
    df = df.copy()
    for col in SUPPLEMENT_COLS + ["record_id", "INN"]:
        if col not in df.columns:
            df[col] = ""
        if col not in clean_df.columns:
            clean_df[col] = ""
    restored = 0

    # record_id lookup for new files
    by_id = clean_df.drop_duplicates("record_id", keep="first").set_index("record_id") if "record_id" in clean_df.columns else pd.DataFrame()
    for idx, row in df.iterrows():
        rid = str(row.get("record_id", "")).strip()
        ref = None
        if rid and not by_id.empty and rid in by_id.index:
            ref = by_id.loc[rid]
        if ref is None:
            continue
        for col in SUPPLEMENT_COLS:
            if str(df.at[idx, col]).strip() == "" and str(ref.get(col, "")).strip():
                df.at[idx, col] = str(ref.get(col, ""))
                restored += 1

    # composite fallback for old final files without record_id
    clean_df["_ckey"] = clean_df.apply(lambda r: "|".join(dedup_key(r.to_dict())), axis=1)
    by_key = clean_df.drop_duplicates("_ckey", keep="first").set_index("_ckey")
    for idx, row in df.iterrows():
        key = "|".join(dedup_key(row.to_dict()))
        if not key or key not in by_key.index:
            continue
        ref = by_key.loc[key]
        for col in SUPPLEMENT_COLS:
            if str(df.at[idx, col]).strip() == "" and str(ref.get(col, "")).strip():
                df.at[idx, col] = str(ref.get(col, ""))
                restored += 1
    return df.drop(columns=["_ckey"], errors="ignore"), restored


def route_values(row: pd.Series) -> tuple[str, str, str, str]:
    inn = normalize_inn(row.get("INN") or row.get("INN_dadata"))
    _code, region_by_inn, fd_by_inn = region_from_inn(inn)
    region = normalize_region_name(row.get("RegionRegistration")) or normalize_region_name(row.get("RegionName")) or region_by_inn
    industry = str(row.get("Industry") or "").strip()
    subindustry = str(row.get("Subindustry") or "").strip()
    fd = federal_district_for_region(region) or fd_by_inn
    return region, industry, subindustry, fd


def export_by_category(
    input_csv: Path,
    out_dir: Path,
    reports_dir: Path,
    *,
    clean_dir: Path | None = None,
    review_root: Path | None = None,
    include_federal_district: bool = False,
    clear_output: bool = True,
    active_only: bool = False,
    logger: logging.Logger | None = None,
) -> dict[str, int]:
    log = logger or setup_logger()
    out_dir = Path(out_dir)
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    review_root = Path(review_root) if review_root else reports_dir.parent / "review"
    review_root.mkdir(parents=True, exist_ok=True)
    if clear_output and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = read_csv(input_csv)
    source_rows = len(df)
    if active_only and "is_active" in df.columns:
        # Optional safety filter only. By default export stage must not remove rows,
        # because active/spark_included inputs are already filtered upstream.
        # Accept several common representations to avoid accidental loss.
        active_values = {"1", "true", "True", "TRUE", "active", "ACTIVE", "yes", "YES", "Действующее", "действующее"}
        before_filter = len(df)
        df = df[df["is_active"].astype(str).str.strip().isin(active_values)].copy()
        dropped = before_filter - len(df)
        if dropped:
            log.warning("Export active_only filter dropped %s rows. Set [export] active_only=false to disable.", dropped)
    active_rows = len(df)

    restored = 0
    if clean_dir:
        clean_df = load_clean_reference(clean_dir)
        df, restored = supplement_from_clean(df, clean_df)

    overrides_applied = 0
    # Manual routing overrides are applied after supplementing from clean, so
    # they can intentionally fix or replace missing route fields. This keeps
    # manual fixes reproducible and avoids editing final CSV files by hand.
    cfg_for_overrides = None
    # The function receives only paths, so override paths are passed from main
    # via attributes on reports_dir if not configured. See main() below.
    overrides_csv = getattr(export_by_category, "_overrides_csv", None)
    overrides_report_csv = getattr(export_by_category, "_overrides_report_csv", None)
    if overrides_csv:
        df, overrides_report = apply_routing_overrides(df, overrides_csv, report_csv=overrides_report_csv)
        if not overrides_report.empty:
            overrides_applied = int((overrides_report["status"].astype(str) == "applied").sum())
            if overrides_applied:
                log.info("Applied routing override rows: %s", overrides_applied)

    issues: list[dict[str, str]] = []
    manifest: list[dict[str, str]] = []
    exported_total = 0

    # Make routing columns explicit and stable before grouping.
    routing_records = []
    for idx, row in df.iterrows():
        region, industry, subindustry, fd = route_values(row)
        issue_parts = []
        if not region:
            region = "__REGION_NOT_MAPPED__"
            issue_parts.append("missing_region")
        if not industry:
            industry = "__INDUSTRY_MISSING__"
            issue_parts.append("missing_industry")
        if not subindustry:
            subindustry = "__SUBINDUSTRY_MISSING__"
            issue_parts.append("missing_subindustry")
        if include_federal_district and not fd:
            fd = "__FEDERAL_DISTRICT_NOT_MAPPED__"
            issue_parts.append("missing_federal_district")
        if issue_parts:
            issues.append({
                "row_index": str(idx),
                "record_id": str(row.get("record_id", "")),
                "INN": str(row.get("INN") or row.get("INN_dadata") or ""),
                "CompanyNameOfficial": str(row.get("CompanyNameOfficial", "")),
                "issues": ";".join(issue_parts),
                "RegionRegistration": str(row.get("RegionRegistration", "")),
                "Industry": str(row.get("Industry", "")),
                "Subindustry": str(row.get("Subindustry", "")),
            })
        new_row = row.to_dict()
        new_row["ExportRegion"] = region
        new_row["ExportIndustry"] = industry
        new_row["ExportSubindustry"] = subindustry
        new_row["ExportFederalDistrict"] = fd
        routing_records.append(new_row)

    export_df = pd.DataFrame(routing_records)
    if export_df.empty:
        pd.DataFrame().to_csv(reports_dir / "export_summary.csv", index=False, encoding="utf-8-sig")
        return {"source_rows": source_rows, "active_rows": active_rows, "exported_rows": 0, "issues": 0}

    # Build output paths first and then group by the *sanitized file path*.
    # v5.3 hotfix: different original route values can sanitize to the same
    # folder/file name on Windows. Previous versions wrote each route group
    # separately and a later group could overwrite an earlier CSV. That caused
    # No Data Loss failures such as expected=1890 but export_rows=1883.
    def output_rel_path(row: pd.Series) -> str:
        region = row.get("ExportRegion", "")
        industry = row.get("ExportIndustry", "")
        subindustry = row.get("ExportSubindustry", "")
        if include_federal_district:
            fd = row.get("ExportFederalDistrict", "")
            return str(Path(safe_filename(fd)) / safe_filename(region) / safe_filename(industry) / safe_filename(subindustry, ext=".csv"))
        return str(Path(safe_filename(region)) / safe_filename(industry) / safe_filename(subindustry, ext=".csv"))

    export_df["__output_rel_path"] = export_df.apply(output_rel_path, axis=1)

    collision_rows = []
    for rel_path, group in export_df.groupby("__output_rel_path", dropna=False, sort=True):
        file_path = out_dir / str(rel_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        group_to_write = group.drop(columns=["__output_rel_path"], errors="ignore")
        # Keep original + Export* columns for traceability.
        sanitize_for_csv(group_to_write).to_csv(file_path, index=False, encoding="utf-8-sig")
        exported_total += len(group_to_write)

        unique_routes = group_to_write[["ExportRegion", "ExportIndustry", "ExportSubindustry", "ExportFederalDistrict"]].drop_duplicates()
        if len(unique_routes) > 1:
            collision_rows.append({
                "file": str(rel_path),
                "rows": str(len(group_to_write)),
                "unique_routes": str(len(unique_routes)),
                "routes": " | ".join(
                    f"{r.ExportFederalDistrict}/{r.ExportRegion}/{r.ExportIndustry}/{r.ExportSubindustry}"
                    for r in unique_routes.itertuples(index=False)
                ),
            })

        manifest.append({
            "file": str(rel_path),
            "rows": str(len(group_to_write)),
            "region": ";".join(sorted(set(group_to_write["ExportRegion"].astype(str)))),
            "industry": ";".join(sorted(set(group_to_write["ExportIndustry"].astype(str)))),
            "subindustry": ";".join(sorted(set(group_to_write["ExportSubindustry"].astype(str)))),
            "federal_district": ";".join(sorted(set(group_to_write["ExportFederalDistrict"].astype(str)))) if include_federal_district else "",
        })

    sanitize_for_csv(pd.DataFrame(manifest)).to_csv(reports_dir / "export_summary.csv", index=False, encoding="utf-8-sig")
    sanitize_for_csv(pd.DataFrame(collision_rows, columns=["file", "rows", "unique_routes", "routes"])).to_csv(
        reports_dir / "export_filename_collisions.csv", index=False, encoding="utf-8-sig"
    )
    issue_cols = ["row_index", "record_id", "INN", "CompanyNameOfficial", "issues", "RegionRegistration", "Industry", "Subindustry"]
    issues_df = sanitize_for_csv(pd.DataFrame(issues, columns=issue_cols))
    issues_df.to_csv(reports_dir / "export_issues.csv", index=False, encoding="utf-8-sig")
    # Route issue rows also go to final/review/ for manual correction. They are not deleted from export.
    if not issues_df.empty:
        routing_dir = review_root / "routing_issues"
        routing_dir.mkdir(parents=True, exist_ok=True)
        issues_df.to_csv(routing_dir / "routing_issues.csv", index=False, encoding="utf-8-sig")
        for issue_name in ["missing_region", "missing_industry", "missing_subindustry", "missing_federal_district"]:
            mask = issues_df["issues"].astype(str).str.contains(issue_name, regex=False, na=False)
            if mask.any():
                issues_df[mask].to_csv(routing_dir / f"{issue_name}.csv", index=False, encoding="utf-8-sig")
    summary = {
        "source_rows": source_rows,
        "active_rows": active_rows,
        "exported_rows": exported_total,
        "issues": len(issues),
        "restored_cells_from_clean": restored,
        "manual_override_rows_applied": overrides_applied,
        "groups": len(manifest),
    }
    pd.DataFrame([summary]).to_csv(reports_dir / "export_run_summary.csv", index=False, encoding="utf-8-sig")
    if exported_total != active_rows:
        log.error("Export row mismatch: active_rows=%s exported_rows=%s", active_rows, exported_total)
    else:
        log.info("Export complete: rows=%s groups=%s issues=%s", exported_total, len(manifest), len(issues))
    return {k: int(v) for k, v in summary.items()}


def choose_export_input(cfg, explicit_input: str | None = None) -> Path:
    """Choose export input by config mode.

    Modes:
    - auto: described -> spark_included -> active, first existing non-empty file
    - described: final/all_sectors_final_active_described.csv
    - spark_included: final/all_sectors_final_active_spark_included.csv
    - active: final/all_sectors_final_active.csv
    - custom: [export] input_csv or --input
    """
    if explicit_input:
        return Path(explicit_input).expanduser().resolve()
    mode = cfg.get("export", "input_mode", fallback="auto").strip().lower()
    candidates = {
        "described": resolve_path(cfg, "descriptions", "output_csv", "final/all_sectors_final_active_described.csv"),
        "spark_included": resolve_path(cfg, "spark", "included_csv", "final/all_sectors_final_active_spark_included.csv"),
        "active": resolve_path(cfg, "spark", "active_input_csv", "final/all_sectors_final_active.csv"),
        "custom": resolve_path(cfg, "export", "input_csv", "final/all_sectors_final_active_described.csv"),
    }
    if mode in candidates and mode != "auto":
        return candidates[mode]
    if mode == "custom":
        return candidates["custom"]
    for key in ("described", "spark_included", "active"):
        p = candidates[key]
        if p.exists() and p.stat().st_size > 0:
            return p
    return candidates["active"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Export final active CSV by Region/Industry/Subindustry.")
    parser.add_argument("--config", default="config.ini")
    parser.add_argument("--input", default=None, help="Input final active/described CSV")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--include-federal-district", action="store_true", help="Override config and include federal district level")
    args = parser.parse_args()

    cfg = read_config(args.config)
    configure_region_reference(cfg)
    paths = load_paths(cfg, create=True)
    include_fd = args.include_federal_district or cfg.getboolean("export", "export_include_federal_district", fallback=False)
    input_path = choose_export_input(cfg, args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Export input not found: {input_path}")
    out_dir = Path(args.out_dir) if args.out_dir else paths.export_by_category
    overrides_csv = resolve_path(cfg, "manual_overrides", "routing_overrides_csv", "manual_overrides/routing_overrides.csv")
    overrides_report_csv = paths.reports / "manual_routing_overrides_report.csv"
    export_by_category._overrides_csv = overrides_csv
    export_by_category._overrides_report_csv = overrides_report_csv

    export_by_category(
        input_csv=input_path,
        out_dir=out_dir,
        reports_dir=paths.reports,
        clean_dir=paths.clean,
        review_root=resolve_path(cfg, "spark", "review_root", "final/review"),
        include_federal_district=include_fd,
        clear_output=cfg.getboolean("export", "clear_output", fallback=True),
        active_only=cfg.getboolean("export", "active_only", fallback=False),
        logger=setup_logger(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
