"""Manual override helpers.

Manual overrides are small reproducible CSV patches that are applied by the
pipeline before export. They are safer than editing final CSV files by hand,
because every correction remains visible and can be replayed after reruns.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from row_identity import normalize_inn

ROUTING_OVERRIDE_FIELDS = [
    "RegionRegistration",
    "RegionHeadOffice",
    "RegionOperation",
    "Sector",
    "Industry",
    "Subindustry",
]

OVERRIDE_META_COLUMNS = [
    "ManualOverrideApplied",
    "ManualOverrideReason",
    "ManualOverrideSource",
]


def read_csv_safe(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def ensure_override_template(path: Path) -> None:
    """Create an empty routing override template if it does not exist."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "record_id",
        "INN",
        "CompanyNameOfficial",
        *ROUTING_OVERRIDE_FIELDS,
        "OverrideReason",
    ]
    pd.DataFrame(columns=cols).to_csv(path, index=False, encoding="utf-8-sig")


def _match_rows(df: pd.DataFrame, override: pd.Series) -> pd.Series:
    """Return boolean mask for rows affected by one override row.

    Priority:
    1. exact record_id, if present;
    2. INN + CompanyNameOfficial, if both present;
    3. INN only, but only if it matches exactly one row.
    """
    mask = pd.Series(False, index=df.index)
    rid = str(override.get("record_id", "")).strip()
    if rid and "record_id" in df.columns:
        rid_mask = df["record_id"].astype(str).str.strip().eq(rid)
        if rid_mask.any():
            return rid_mask

    inn = normalize_inn(override.get("INN", ""))
    name = str(override.get("CompanyNameOfficial", "")).strip()
    if inn and "INN" in df.columns:
        inn_series = df["INN"].astype(str).map(normalize_inn)
        inn_mask = inn_series.eq(inn)
        if name and "CompanyNameOfficial" in df.columns:
            name_mask = df["CompanyNameOfficial"].astype(str).str.strip().eq(name)
            both = inn_mask & name_mask
            if both.any():
                return both
        # Use INN-only fallback only when unique to avoid changing several
        # valid sector/subindustry rows of the same company.
        if int(inn_mask.sum()) == 1:
            return inn_mask
    return mask


def apply_routing_overrides(
    df: pd.DataFrame,
    overrides_csv: str | Path,
    *,
    report_csv: str | Path | None = None,
    create_template: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply routing overrides and optionally write an audit report.

    Non-empty values in override columns replace existing row values. Empty
    values do nothing. Rows are matched primarily by record_id.
    """
    path = Path(overrides_csv)
    if create_template:
        ensure_override_template(path)
    overrides = read_csv_safe(path)
    result = df.copy()
    for col in ROUTING_OVERRIDE_FIELDS + OVERRIDE_META_COLUMNS:
        if col not in result.columns:
            result[col] = ""

    report_rows: list[dict[str, str]] = []
    if overrides.empty:
        report = pd.DataFrame(columns=["override_row", "matched_rows", "status", "record_id", "INN", "fields", "reason"])
        if report_csv:
            Path(report_csv).parent.mkdir(parents=True, exist_ok=True)
            report.to_csv(report_csv, index=False, encoding="utf-8-sig")
        return result, report

    for i, ov in overrides.iterrows():
        mask = _match_rows(result, ov)
        matched = int(mask.sum())
        fields_applied = []
        reason = str(ov.get("OverrideReason", "")).strip()
        if matched:
            for col in ROUTING_OVERRIDE_FIELDS:
                value = str(ov.get(col, "")).strip()
                if value:
                    result.loc[mask, col] = value
                    fields_applied.append(col)
            if fields_applied:
                result.loc[mask, "ManualOverrideApplied"] = "1"
                result.loc[mask, "ManualOverrideReason"] = reason
                result.loc[mask, "ManualOverrideSource"] = str(path)
                status = "applied"
            else:
                status = "matched_no_values"
        else:
            status = "not_matched"
        report_rows.append({
            "override_row": str(i + 1),
            "matched_rows": str(matched),
            "status": status,
            "record_id": str(ov.get("record_id", "")).strip(),
            "INN": str(ov.get("INN", "")).strip(),
            "fields": ";".join(fields_applied),
            "reason": reason,
        })

    report = pd.DataFrame(report_rows)
    if report_csv:
        Path(report_csv).parent.mkdir(parents=True, exist_ok=True)
        report.to_csv(report_csv, index=False, encoding="utf-8-sig")
    return result, report
