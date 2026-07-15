"""Stable record identity helpers.

INN identifies a company, not a dataset row. A company can be present in several
industries/subindustries, so every row gets a separate record_id.
"""
from __future__ import annotations

import hashlib
import re


def normalize_inn(value: object) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits if len(digits) in {10, 12} else digits


def norm_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def make_record_id(
    source_file: object,
    source_row_no: object,
    inn: object,
    sector: object,
    industry: object,
    subindustry: object,
) -> str:
    parts = [source_file, source_row_no, normalize_inn(inn), sector, industry, subindustry]
    payload = "|".join(norm_text(p) for p in parts)
    return hashlib.sha1(payload.encode("utf-8", "replace")).hexdigest()[:20]


def dedup_key(row: dict) -> tuple[str, str, str, str, str]:
    return (
        normalize_inn(row.get("INN") or row.get("INN_dadata") or ""),
        norm_text(row.get("RegionRegistration")),
        norm_text(row.get("Sector")),
        norm_text(row.get("Industry")),
        norm_text(row.get("Subindustry")),
    )
