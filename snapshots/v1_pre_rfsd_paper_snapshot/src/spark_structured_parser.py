"""Offline SPARK extractor for XML/CSV/XLSX/TXT packages.

This module does not call SPARK API. It processes files exported by a person who
has SPARK access. XML files are parsed deterministically; text-like files use
lightweight regex fallback. LLM extraction can be added later, but structured XML
should not be sent to an LLM because exact fields are cheaper and safer to parse.
"""
from __future__ import annotations

import argparse
import configparser
import csv
import logging
import re
import shutil
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from xml.etree import ElementTree as ET

import pandas as pd

from paths import read_config, resolve_path, load_paths


MONEY_DECIMAL_RE = re.compile(r"[^0-9,.-]")
INN_RE = re.compile(r"(?<!\d)(\d{10}|\d{12})(?!\d)")


@dataclass
class SparkExtractedRecord:
    INN: str = ""
    SparkID: str = ""
    SparkSourceFile: str = ""
    SparkExtractionMethod: str = ""
    SparkExtractionStatus: str = "ok"
    SparkExtractionIssues: str = ""
    SparkExtractionConfidence: str = "high"
    SparkReportActualDate: str = ""

    SparkShortName: str = ""
    SparkFullName: str = ""
    SparkNormName: str = ""
    SparkStatus: str = ""
    SparkStatusCode: str = ""
    SparkIsActing: str = ""
    SparkDateFirstReg: str = ""
    CompanyFoundedYear: str = ""

    SparkRegion: str = ""
    SparkCity: str = ""
    SparkRegionCode: str = ""
    SparkAddress: str = ""
    SparkLatitude: str = ""
    SparkLongitude: str = ""
    SparkWebsite: str = ""

    SparkOKVEDMainCode: str = ""
    SparkOKVEDMainName: str = ""

    CompanyEmployees: str = ""
    CompanyEmployeesYear: str = ""
    CompanyEmployeesDate: str = ""
    CompanyEmployeesSource: str = ""

    CompanyRevenueRawRUB: str = ""
    CompanyRevenue: str = ""  # млрд руб. as a machine-readable decimal string
    CompanyRevenueUnitOriginal: str = ""
    CompanyRevenueYear: str = ""
    CompanyRevenueSource: str = ""
    CompanyRevenueEvidence: str = ""

    CompanyBudgetRawRUB: str = ""
    CompanyBudget: str = ""
    CompanyBudgetYear: str = ""
    CompanyBudgetSource: str = ""

    SparkEvidenceText: str = ""
    ExtractedAt: str = ""


def setup_logger() -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger("spark_structured_parser")


def parse_money_to_float(value: object) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = MONEY_DECIMAL_RE.sub("", text).replace(" ", "")
    if not text or text in {"-", ",", "."}:
        return None
    if "," in text and "." in text:
        # Assume comma is decimal separator if it appears after the last dot.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def rub_to_bln(value_rub: Optional[float]) -> str:
    if value_rub is None:
        return ""
    bln = value_rub / 1_000_000_000
    return f"{bln:.3f}".rstrip("0").rstrip(".")


def format_raw_rub(value_rub: Optional[float]) -> str:
    if value_rub is None:
        return ""
    return str(int(round(value_rub)))


def infer_money_unit_from_text(text: object) -> str:
    """Return rub/thousand_rub/million_rub/billion_rub/unknown based on header or value text."""
    t = str(text or "").lower().replace("ё", "е")
    if any(x in t for x in ["млрд", "миллиард"]):
        return "billion_rub"
    if any(x in t for x in ["млн", "миллион"]):
        return "million_rub"
    if any(x in t for x in ["тыс", "тысяч"]):
        return "thousand_rub"
    if "руб" in t or "rur" in t or "rub" in t:
        return "rub"
    return "unknown"


def money_to_rub(value: object, unit_hint: str = "unknown") -> tuple[Optional[float], str]:
    """Convert a money value to RUB using an explicit/header unit when available."""
    value_text = str(value or "")
    unit_from_value = infer_money_unit_from_text(value_text)
    unit = unit_from_value if unit_from_value != "unknown" else (unit_hint or "unknown")
    val = parse_money_to_float(value_text)
    if val is None:
        return None, unit
    if unit == "billion_rub":
        return val * 1_000_000_000, unit
    if unit == "million_rub":
        return val * 1_000_000, unit
    if unit == "thousand_rub":
        return val * 1_000, unit
    if unit == "rub":
        return val, unit
    # Conservative fallback for flattened tables: large values are likely RUB;
    # small decimal values in revenue columns are usually billion RUB.
    if val > 1_000_000:
        return val, "rub_inferred"
    return val * 1_000_000_000, "billion_rub_inferred"


def latest_date(items: Iterable[tuple[str, object]]) -> tuple[str, object] | tuple[str, None]:
    valid: list[tuple[str, object]] = []
    for date_str, value in items:
        if date_str:
            valid.append((date_str, value))
    if not valid:
        return "", None
    valid.sort(key=lambda x: x[0])
    return valid[-1]


def first_text(root: ET.Element, tag: str) -> str:
    el = root.find(f".//{tag}")
    return (el.text or "").strip() if el is not None else ""


def first_attr(root: ET.Element, tag: str, attr: str) -> str:
    el = root.find(f".//{tag}")
    return (el.attrib.get(attr, "") or "").strip() if el is not None else ""


def parse_spark_xml(path: Path) -> SparkExtractedRecord:
    rec = SparkExtractedRecord(
        SparkSourceFile=str(path),
        SparkExtractionMethod="xml_rules",
        ExtractedAt=datetime.now(timezone.utc).isoformat(),
    )
    issues: list[str] = []
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception as exc:
        rec.SparkExtractionStatus = "failed"
        rec.SparkExtractionConfidence = "low"
        rec.SparkExtractionIssues = f"xml_parse_error:{exc}"
        return rec

    report = root.find(".//Report")
    if report is not None:
        rec.SparkReportActualDate = report.attrib.get("ActualDate", "")

    rec.SparkID = first_text(root, "SparkID")
    rec.INN = first_text(root, "INN") or infer_inn_from_name(path.name)
    rec.SparkShortName = first_text(root, "ShortNameRus")
    rec.SparkFullName = first_text(root, "FullNameRus")
    rec.SparkNormName = first_text(root, "NormName")
    rec.SparkDateFirstReg = first_text(root, "DateFirstReg")
    rec.CompanyFoundedYear = rec.SparkDateFirstReg[:4] if re.match(r"\d{4}", rec.SparkDateFirstReg or "") else ""

    status = root.find(".//Status")
    if status is not None:
        rec.SparkStatus = status.attrib.get("Type") or status.attrib.get("GroupName", "")
        rec.SparkStatusCode = status.attrib.get("Code", "")
        rec.SparkIsActing = status.attrib.get("IsActing", "")
    if not rec.SparkIsActing:
        is_acting = first_text(root, "IsActing")
        rec.SparkIsActing = is_acting

    address = root.find(".//LegalAddresses/Address")
    if address is None:
        address = root.find(".//LegalAddresses//Address")
    if address is not None:
        rec.SparkRegion = address.attrib.get("Region", "")
        rec.SparkCity = address.attrib.get("City", "")
        rec.SparkAddress = address.attrib.get("Address", "")
        rec.SparkLatitude = address.attrib.get("Latitude", "")
        rec.SparkLongitude = address.attrib.get("Longitude", "")
        rec.SparkRegionCode = address.attrib.get("FiasRegion", "")
    if not rec.SparkRegion:
        okato = root.find(".//OKATO")
        if okato is not None:
            rec.SparkRegion = okato.attrib.get("RegionName", "")
            rec.SparkRegionCode = okato.attrib.get("RegionCode", "")

    rec.SparkWebsite = first_text(root, "Www")

    # Main OKVED: prefer OKVED2 IsMain true.
    okved_main = None
    for okved in root.findall(".//OKVED2List/OKVED"):
        if okved.attrib.get("IsMain", "").lower() == "true" or okved.attrib.get("IsMainEGRUL", "").lower() == "true":
            okved_main = okved
            break
    if okved_main is None:
        okved_main = root.find(".//OKVED2List/OKVED")
    if okved_main is not None:
        rec.SparkOKVEDMainCode = okved_main.attrib.get("Code", "")
        rec.SparkOKVEDMainName = okved_main.attrib.get("Name", "")

    # StaffNumberFTS: latest ActualDate.
    staff_items: list[tuple[str, ET.Element]] = []
    for number in root.findall(".//StaffNumberFTS/Number"):
        staff_items.append((number.attrib.get("ActualDate", ""), number))
    staff_date, staff_el = latest_date(staff_items)
    if staff_el is not None:
        rec.CompanyEmployees = re.sub(r"\D", "", staff_el.text or "")
        rec.CompanyEmployeesDate = staff_date
        rec.CompanyEmployeesYear = staff_date[:4]
        rec.CompanyEmployeesSource = "StaffNumberFTS"
    else:
        issues.append("missing_StaffNumberFTS")

    # Revenue: latest Finance/FinPeriod String Code=2110.
    revenue_candidates: list[tuple[str, str, str, str]] = []
    for fin_period in root.findall(".//Finance/FinPeriod"):
        period_name = fin_period.attrib.get("PeriodName", "")
        date_end = fin_period.attrib.get("DateEnd", "") or period_name
        for item in fin_period.findall(".//String"):
            code = item.attrib.get("Code", "")
            name = item.attrib.get("Name", "")
            if code == "2110" or name.strip().lower() == "выручка":
                revenue_candidates.append((date_end, period_name, item.attrib.get("Value", ""), name))
    if revenue_candidates:
        revenue_candidates.sort(key=lambda x: (x[0], x[1]))
        date_end, period_name, value, name = revenue_candidates[-1]
        value_rub = parse_money_to_float(value)
        rec.CompanyRevenueRawRUB = format_raw_rub(value_rub)
        rec.CompanyRevenue = rub_to_bln(value_rub)
        rec.CompanyRevenueUnitOriginal = "rub"
        rec.CompanyRevenueYear = period_name[:4] if period_name else date_end[:4]
        rec.CompanyRevenueSource = "Finance.Code2110"
        rec.CompanyRevenueEvidence = f"FinPeriod={period_name};DateEnd={date_end};Code=2110;Name={name};Value={value}"
    else:
        # Fallback: CompanySize Revenue often comes in million RUB in SPARK-like exports.
        company_size = root.find(".//CompanySize")
        if company_size is not None and company_size.attrib.get("Revenue"):
            val = parse_money_to_float(company_size.attrib.get("Revenue"))
            if val is not None:
                # Heuristic: if value is modest, treat as million RUB. If already huge, treat as RUB.
                value_rub = val * 1_000_000 if val < 100_000_000 else val
                rec.CompanyRevenueRawRUB = format_raw_rub(value_rub)
                rec.CompanyRevenue = rub_to_bln(value_rub)
                rec.CompanyRevenueUnitOriginal = "million_rub" if val < 100_000_000 else "rub"
                rec.CompanyRevenueYear = (company_size.attrib.get("ActualDate", "") or "")[:4]
                rec.CompanyRevenueSource = "CompanySize.Revenue"
                rec.CompanyRevenueEvidence = f"CompanySize ActualDate={company_size.attrib.get('ActualDate','')};Revenue={company_size.attrib.get('Revenue','')}"
            else:
                issues.append("missing_finance_code_2110")
        else:
            issues.append("missing_finance_code_2110")

    evidence_bits = []
    if rec.CompanyEmployees:
        evidence_bits.append(f"employees={rec.CompanyEmployees};date={rec.CompanyEmployeesDate};source={rec.CompanyEmployeesSource}")
    if rec.CompanyRevenueRawRUB:
        evidence_bits.append(f"revenue_raw_rub={rec.CompanyRevenueRawRUB};year={rec.CompanyRevenueYear};source={rec.CompanyRevenueSource}")
    rec.SparkEvidenceText = " | ".join(evidence_bits)

    if not rec.INN:
        issues.append("missing_inn")
    if issues:
        rec.SparkExtractionIssues = ";".join(issues)
        rec.SparkExtractionConfidence = "medium" if rec.INN else "low"
    return rec


def infer_inn_from_name(name: str) -> str:
    m = INN_RE.search(name or "")
    return m.group(1) if m else ""


def parse_text_file(path: Path) -> SparkExtractedRecord:
    text = path.read_text(encoding="utf-8", errors="ignore")
    rec = SparkExtractedRecord(
        INN=infer_inn_from_name(path.name) or (INN_RE.search(text).group(1) if INN_RE.search(text) else ""),
        SparkSourceFile=str(path),
        SparkExtractionMethod="text_regex",
        SparkExtractionConfidence="medium",
        ExtractedAt=datetime.now(timezone.utc).isoformat(),
    )
    year_match = re.search(r"(?:Дата\s+регистрации|зарегистрирован[ао]?|основан[ао]?)[^0-9]{0,80}((?:19|20)\d{2})", text, re.I)
    if year_match:
        rec.CompanyFoundedYear = year_match.group(1)
    emp_match = re.search(r"(?:численность|среднесписочная численность|работников|сотрудников)[^0-9]{0,80}(\d[\d\s]*)", text, re.I)
    if emp_match:
        rec.CompanyEmployees = re.sub(r"\D", "", emp_match.group(1))
        rec.CompanyEmployeesSource = "text_regex"
    rev_match = re.search(r"(?:выручка)[^0-9]{0,80}(\d[\d\s,.]*)\s*(млрд|млн|тыс)?", text, re.I)
    if rev_match:
        unit_hint = infer_money_unit_from_text(rev_match.group(2) or "")
        rub, unit = money_to_rub(rev_match.group(1), unit_hint)
        if rub is not None:
            rec.CompanyRevenueRawRUB = format_raw_rub(rub)
            rec.CompanyRevenue = rub_to_bln(rub)
            rec.CompanyRevenueUnitOriginal = unit
            rec.CompanyRevenueSource = "text_regex"
    if not rec.INN:
        rec.SparkExtractionStatus = "review"
        rec.SparkExtractionConfidence = "low"
        rec.SparkExtractionIssues = "missing_inn"
    return rec


def unpack_archives(incoming_dir: Path, unpacked_dir: Path, *, clear: bool = False, logger: Optional[logging.Logger] = None) -> list[Path]:
    log = logger or setup_logger()
    unpacked_dir.mkdir(parents=True, exist_ok=True)
    if clear and unpacked_dir.exists():
        for item in unpacked_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    extracted: list[Path] = []
    if not incoming_dir.exists():
        return extracted
    for path in incoming_dir.rglob("*"):
        if path.is_dir():
            continue
        if path.suffix.lower() == ".zip":
            target = unpacked_dir / path.stem
            target.mkdir(parents=True, exist_ok=True)
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    zf.extractall(target)
                extracted.append(target)
                log.info("Unpacked SPARK archive %s -> %s", path, target)
            except Exception as exc:
                log.error("Failed to unpack %s: %s", path, exc)
        else:
            # Also copy loose files to unpacked so the rest of the pipeline is uniform.
            target = unpacked_dir / path.name
            if path.resolve() != target.resolve():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            extracted.append(target)
    return extracted


def iter_spark_files(unpacked_dir: Path) -> Iterable[Path]:
    allowed = {".xml", ".txt", ".csv", ".xlsx", ".html", ".htm"}
    if not unpacked_dir.exists():
        return []
    return [p for p in unpacked_dir.rglob("*") if p.is_file() and p.suffix.lower() in allowed]


def parse_any_file(path: Path) -> list[SparkExtractedRecord]:
    suffix = path.suffix.lower()
    if suffix == ".xml":
        return [parse_spark_xml(path)]
    if suffix in {".txt", ".html", ".htm"}:
        return [parse_text_file(path)]
    if suffix in {".csv", ".xlsx"}:
        try:
            if suffix == ".csv":
                df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
            else:
                df = pd.read_excel(path, dtype=str, keep_default_na=False)
        except Exception as exc:
            return [SparkExtractedRecord(SparkSourceFile=str(path), SparkExtractionMethod="table_parse", SparkExtractionStatus="failed", SparkExtractionIssues=str(exc), SparkExtractionConfidence="low", ExtractedAt=datetime.now(timezone.utc).isoformat())]
        return parse_table_records(df, path)
    return []


def parse_table_records(df: pd.DataFrame, path: Path) -> list[SparkExtractedRecord]:
    # Flexible column mapping for already flattened SPARK extracts.
    normalized = {str(c).strip().lower(): c for c in df.columns}

    def find_col(*names: str) -> Optional[str]:
        for name in names:
            key = name.lower()
            if key in normalized:
                return normalized[key]
        for key, col in normalized.items():
            if any(n.lower() in key for n in names):
                return col
        return None

    col_inn = find_col("inn", "инн")
    col_emp = find_col("companyemployees", "employees", "численность", "сотруд")
    col_rev = find_col("companyrevenuerawrub", "revenue_raw", "выручка", "revenue")
    col_year = find_col("companyrevenueyear", "год выручки", "revenueyear")
    col_name = find_col("sparkshortname", "shortnamerus", "название", "companyname")
    records = []
    for _, row in df.iterrows():
        raw_rev_value = row.get(col_rev, "") if col_rev else ""
        unit_hint = infer_money_unit_from_text(col_rev or "")
        rev_rub, rev_unit = money_to_rub(raw_rev_value, unit_hint) if col_rev else (None, "")
        rev_raw_rub = format_raw_rub(rev_rub)
        rev_bln = rub_to_bln(rev_rub)
        rec = SparkExtractedRecord(
            INN=str(row.get(col_inn, "") if col_inn else infer_inn_from_name(path.name)).strip(),
            SparkShortName=str(row.get(col_name, "") if col_name else "").strip(),
            SparkSourceFile=str(path),
            SparkExtractionMethod="table_rules",
            SparkExtractionConfidence="medium",
            CompanyEmployees=re.sub(r"\D", "", str(row.get(col_emp, "") if col_emp else "")),
            CompanyEmployeesSource="table_rules" if col_emp else "",
            CompanyRevenueRawRUB=rev_raw_rub,
            CompanyRevenue=rev_bln,
            CompanyRevenueUnitOriginal=rev_unit,
            CompanyRevenueYear=str(row.get(col_year, "") if col_year else "").strip()[:4],
            CompanyRevenueSource="table_rules" if col_rev else "",
            ExtractedAt=datetime.now(timezone.utc).isoformat(),
        )
        if not rec.INN:
            rec.SparkExtractionStatus = "review"
            rec.SparkExtractionIssues = "missing_inn"
            rec.SparkExtractionConfidence = "low"
        records.append(rec)
    return records


def extract_spark_files(unpacked_dir: Path, output_csv: Path, reports_dir: Path, *, logger: Optional[logging.Logger] = None) -> pd.DataFrame:
    log = logger or setup_logger()
    records: list[dict] = []
    for file_path in iter_spark_files(unpacked_dir):
        for rec in parse_any_file(file_path):
            records.append(asdict(rec))
    df = pd.DataFrame(records)
    if df.empty:
        df = pd.DataFrame(columns=list(asdict(SparkExtractedRecord()).keys()))
    # Prefer better records per INN if duplicates appear: high confidence and richer fields.
    if "INN" in df.columns and not df.empty:
        df["_richness"] = df.apply(lambda r: sum(bool(str(r.get(c, "")).strip()) for c in ["CompanyEmployees", "CompanyRevenueRawRUB", "CompanyFoundedYear", "SparkShortName"]), axis=1)
        df["_confidence_rank"] = df["SparkExtractionConfidence"].map({"high": 3, "medium": 2, "low": 1}).fillna(0)
        df = df.sort_values(["INN", "_confidence_rank", "_richness"], ascending=[True, False, False])
        df = df.drop_duplicates(subset=["INN"], keep="first").drop(columns=["_richness", "_confidence_rank"])
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    summary = {
        "files_scanned": len(list(iter_spark_files(unpacked_dir))),
        "records_extracted": len(df),
        "with_inn": int((df.get("INN", pd.Series(dtype=str)).astype(str).str.len() > 0).sum()) if not df.empty else 0,
        "with_employees": int((df.get("CompanyEmployees", pd.Series(dtype=str)).astype(str).str.len() > 0).sum()) if not df.empty else 0,
        "with_revenue": int((df.get("CompanyRevenueRawRUB", pd.Series(dtype=str)).astype(str).str.len() > 0).sum()) if not df.empty else 0,
    }
    pd.DataFrame([summary]).to_csv(reports_dir / "spark_extraction_summary.csv", index=False, encoding="utf-8-sig")
    # Additional control for revenue units/conversion.
    if not df.empty and "CompanyRevenueRawRUB" in df.columns:
        check = df[[c for c in ["INN", "SparkSourceFile", "CompanyRevenueRawRUB", "CompanyRevenue", "CompanyRevenueUnitOriginal", "CompanyRevenueYear", "CompanyRevenueSource", "CompanyRevenueEvidence"] if c in df.columns]].copy()
        def revenue_issue(v):
            rub = parse_money_to_float(v)
            if rub is None:
                return "missing_revenue"
            if rub < 0:
                return "negative_revenue"
            if 0 < rub < 1_000_000:
                return "revenue_below_1m"
            if rub > 10_000_000_000_000:
                return "revenue_extremely_high_check_unit"
            return ""
        check["RevenueUnitIssue"] = check["CompanyRevenueRawRUB"].apply(revenue_issue)
        check[check["RevenueUnitIssue"].astype(str) != ""].to_csv(reports_dir / "revenue_unit_issues.csv", index=False, encoding="utf-8-sig")
    log.info("SPARK extraction complete: %s", summary)
    return df


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract useful fields from offline SPARK exports.")
    parser.add_argument("--config", default="config.ini")
    parser.add_argument("--incoming", default=None)
    parser.add_argument("--unpacked", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--clear-unpacked", action="store_true")
    args = parser.parse_args()
    cfg = read_config(args.config)
    load_paths(cfg, create=True)
    incoming = Path(args.incoming) if args.incoming else resolve_path(cfg, "spark", "incoming_dir", "spark/incoming")
    unpacked = Path(args.unpacked) if args.unpacked else resolve_path(cfg, "spark", "unpacked_dir", "spark/unpacked")
    output = Path(args.output) if args.output else resolve_path(cfg, "spark", "extracted_csv", "spark/extracted/spark_extracted.csv")
    reports = resolve_path(cfg, "spark", "reports_dir", "spark/reports")
    log = setup_logger()
    unpack_archives(incoming, unpacked, clear=args.clear_unpacked, logger=log)
    extract_spark_files(unpacked, output, reports, logger=log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
