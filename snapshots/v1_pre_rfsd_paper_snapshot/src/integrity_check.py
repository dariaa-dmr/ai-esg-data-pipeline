"""Integrity checks and safe restoration of immutable columns.

The module uses clean CSV files as the reference layer and restores only stable
source/classification fields. It never drops rows. Prefer record_id; fall back to
INN + RegionRegistration + Sector + Industry + Subindustry when processing old
files without record_id.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from row_identity import dedup_key, make_record_id, normalize_inn, norm_text

ESSENTIAL_COLS = [
    "Sector", "Industry", "Subindustry", "CompanyName", "CompanyNameOfficial", "INN",
    "RegionRegistration", "RegionHeadOffice", "RegionOperation",
    "Description", "URL", "Source", "record_id", "source_file", "source_row_no",
    "physical_line", "parse_status", "parse_reason", "raw_line",
]

CLASSIFICATION_COLS = [
    "Sector", "Industry", "Subindustry", "RegionRegistration", "RegionHeadOffice", "RegionOperation",
]


def _ensure_record_id(df: pd.DataFrame, source_name: str = "") -> pd.DataFrame:
    df = df.copy()
    if "record_id" not in df.columns:
        df["record_id"] = ""
    if "source_file" not in df.columns:
        df["source_file"] = source_name
    if "source_row_no" not in df.columns:
        df["source_row_no"] = [str(i + 1) for i in range(len(df))]
    mask = df["record_id"].astype(str).str.strip().eq("")
    if mask.any():
        df.loc[mask, "record_id"] = df.loc[mask].apply(
            lambda r: make_record_id(
                r.get("source_file") or source_name,
                r.get("source_row_no") or r.name + 1,
                r.get("INN") or r.get("INN_dadata"),
                r.get("Sector"),
                r.get("Industry"),
                r.get("Subindustry"),
            ),
            axis=1,
        )
    return df


def _fill_empty_from_series(target: pd.Series, ref: pd.Series) -> pd.Series:
    out = target.astype(str)
    ref = ref.astype(str)
    empty = out.str.strip().eq("")
    out.loc[empty] = ref.loc[empty]
    return out


def restore_missing_columns_from_clean(
    target_file: Path,
    clean_file: Path,
    logger: logging.Logger | None = None,
    report_path: Path | None = None,
) -> bool:
    target_file = Path(target_file)
    clean_file = Path(clean_file)
    if not target_file.exists() or not clean_file.exists():
        return False

    log = logger or logging.getLogger(__name__)
    try:
        target_df = pd.read_csv(target_file, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        clean_df = pd.read_csv(clean_file, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except Exception as e:
        log.error("Не удалось прочитать файлы для восстановления: %s", e)
        return False

    before_rows = len(target_df)
    target_df = _ensure_record_id(target_df, target_file.name)
    clean_df = _ensure_record_id(clean_df, clean_file.name)

    for col in ESSENTIAL_COLS:
        if col not in target_df.columns:
            target_df[col] = ""
        if col not in clean_df.columns:
            clean_df[col] = ""

    restored_cells = 0
    report_rows: list[dict[str, str]] = []

    # First pass: record_id mapping. Safe for duplicated INNs.
    ref_by_id = clean_df.drop_duplicates("record_id", keep="first").set_index("record_id")
    target_df = target_df.set_index("record_id", drop=False)
    common_ids = target_df.index.intersection(ref_by_id.index)
    for col in ESSENTIAL_COLS:
        if col == "record_id":
            continue
        if len(common_ids):
            old = target_df.loc[common_ids, col].astype(str)
            new = _fill_empty_from_series(old, ref_by_id.loc[common_ids, col].astype(str))
            restored_cells += int((old != new).sum())
            target_df.loc[common_ids, col] = new

    target_df = target_df.reset_index(drop=True)

    # Second pass for old files: composite key, only for still-empty fields.
    clean_df["_composite_key"] = clean_df.apply(lambda r: "|".join(dedup_key(r.to_dict())), axis=1)
    target_df["_composite_key"] = target_df.apply(lambda r: "|".join(dedup_key(r.to_dict())), axis=1)
    ref_by_key = clean_df.drop_duplicates("_composite_key", keep="first").set_index("_composite_key")
    for idx, row in target_df.iterrows():
        key = row.get("_composite_key", "")
        if not key or key not in ref_by_key.index:
            continue
        ref = ref_by_key.loc[key]
        for col in ESSENTIAL_COLS:
            if col == "record_id":
                continue
            if str(target_df.at[idx, col]).strip() == "" and str(ref.get(col, "")).strip():
                target_df.at[idx, col] = str(ref.get(col, ""))
                restored_cells += 1
                report_rows.append({
                    "target_file": target_file.name,
                    "clean_file": clean_file.name,
                    "record_id": str(row.get("record_id", "")),
                    "INN": str(row.get("INN") or row.get("INN_dadata") or ""),
                    "column": col,
                    "method": "composite_key",
                })

    target_df = target_df.drop(columns=["_composite_key"], errors="ignore")
    if len(target_df) != before_rows:
        log.error("CRITICAL row count changed during restore: before=%s after=%s file=%s", before_rows, len(target_df), target_file)
        return False

    target_df.to_csv(target_file, index=False, encoding="utf-8-sig")
    if report_path and report_rows:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(report_rows).to_csv(
            report_path, mode="a", header=not report_path.exists(), index=False, encoding="utf-8-sig"
        )
    if restored_cells:
        log.info("Восстановлено ячеек=%s в %s из %s", restored_cells, target_file.name, clean_file.name)
        return True
    return False


def check_and_restore(
    source_file: Path,
    stage: str,
    logger: logging.Logger | None = None,
    clean_dir: Path | None = None,
    reports_dir: Path | None = None,
) -> None:
    source_file = Path(source_file)
    clean_base = Path(clean_dir) if clean_dir else Path("clean")
    if stage == "enriched":
        clean_file = clean_base / source_file.name.replace("_enriched.csv", "_clean.csv")
    elif stage == "geo":
        clean_file = clean_base / source_file.name.replace("_geo.csv", "_clean.csv")
    else:
        return
    log = logger or logging.getLogger(__name__)
    if not clean_file.exists():
        log.warning("Clean файл не найден для %s, восстановление невозможно: %s", source_file.name, clean_file)
        return
    report_path = (Path(reports_dir) / "integrity_restore_report.csv") if reports_dir else None
    restore_missing_columns_from_clean(source_file, clean_file, log, report_path=report_path)


def validate_row_count(before_file: Path, after_file: Path, stage: str, logger: logging.Logger | None = None) -> bool:
    """Log and return whether row count was preserved between two pipeline stages."""
    log = logger or logging.getLogger(__name__)
    try:
        before = len(pd.read_csv(before_file, dtype=str, keep_default_na=False, encoding="utf-8-sig"))
        after = len(pd.read_csv(after_file, dtype=str, keep_default_na=False, encoding="utf-8-sig"))
    except Exception as exc:
        log.error("row_count_check_failed stage=%s error=%r", stage, exc)
        return False
    if before != after:
        log.error("ROW_COUNT_CHANGED stage=%s before=%s after=%s before_file=%s after_file=%s", stage, before, after, before_file, after_file)
        return False
    log.info("row_count_ok stage=%s rows=%s", stage, after)
    return True
