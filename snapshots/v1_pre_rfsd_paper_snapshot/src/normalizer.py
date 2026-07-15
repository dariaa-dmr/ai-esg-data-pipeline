"""Final normalization and cleanup for enriched/geocoded company CSV files.

No Data Loss rules:
- never deduplicate by INN alone;
- preserve source/classification fields required for export;
- split active/inactive, but do not silently delete inactive rows;
- write diagnostics to final/reports.
"""
from __future__ import annotations

import configparser
import csv
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import pandas as pd

from row_identity import dedup_key, make_record_id, normalize_inn
from regions_reference import normalize_region_name as normalize_ref_region, region_from_inn, region_operation_codes

OPF_CANON = {
    "ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ": "ООО",
    "АКЦИОНЕРНОЕ ОБЩЕСТВО": "АО",
    "ПУБЛИЧНОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО": "ПАО",
    "ЗАКРЫТОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО": "ЗАО",
    "ОТКРЫТОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО": "ОАО",
    "МУНИЦИПАЛЬНОЕ УНИТАРНОЕ ПРЕДПРИЯТИЕ": "МУП",
    "ГОСУДАРСТВЕННОЕ УНИТАРНОЕ ПРЕДПРИЯТИЕ": "ГУП",
    "ФЕДЕРАЛЬНОЕ ГОСУДАРСТВЕННОЕ УНИТАРНОЕ ПРЕДПРИЯТИЕ": "ФГУП",
    "ГОСУДАРСТВЕННОЕ БЮДЖЕТНОЕ УЧРЕЖДЕНИЕ": "ГБУ",
    "ГОСУДАРСТВЕННОЕ КАЗЕННОЕ УЧРЕЖДЕНИЕ": "ГКУ",
    "МУНИЦИПАЛЬНОЕ КАЗЕННОЕ УЧРЕЖДЕНИЕ": "МКУ",
}
OPF_RE = re.compile(
    r"\b(СПБ\s+ГБУ|ГУП\s+НАО|ГП\s+КО|МП\s+г\.\s*[^\s]+|ООО|ОАО|АО|ПАО|ЗАО|НАО|ФГУП|ГУП|МУП|ГБУ|ГКУ|МКУ|ИП)\b",
    re.I,
)
QUOTE_CONTENT_RE = re.compile(r"[«\"]([^»\"]+)[»\"]")
URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s,;\]<>\)]+|\b[a-zA-Z0-9][a-zA-Z0-9-]{1,}\.(?:ru|рф|com|org|net|su|by|kz|io)\b[^\s,;\]<>\)]*",
    re.I,
)
BRACKETED_NOISE_RE = re.compile(r"\[[^\]]*\]")
FORBIDDEN_DESC_WORDS = ("неизвестн",)

DEFAULT_REFERENCE_BLACKLIST = {
    "spark-interfax.ru", "list-org.com", "rusprofile.ru", "zachestnyibiznes.ru",
    "checko.ru", "sbis.ru", "synapsenet.ru", "kartoteka.ru", "audit-it.ru",
    "egrul.nalog.ru", "nalog.gov.ru", "2gis.ru", "yandex.ru", "google.com",
}

BASE_SOURCE_COLUMNS = [
    "record_id", "source_file", "source_row_no", "physical_line", "parse_status", "parse_reason", "raw_line",
    "Sector", "Industry", "Subindustry", "CompanyName", "CompanyNameOfficial", "INN",
    "RegionRegistration", "RegionHeadOffice", "RegionOperation", "Description", "URL", "Source",
]

FINAL_COLUMNS = [
    "record_id", "source_file", "source_row_no",
    "INN", "INN_dadata", "status_dadata", "is_active",
    "CompanyNameOfficial", "CompanyName", "CompanyNameVariants",
    "CompanyDescription", "CompanyEmployees", "CompanyRevenue",
    "Address_dadata", "Region", "RegionName", "RegionRegistration", "RegionHeadOffice", "RegionOperation",
    "RegionFromAddress", "FederalDistrict", "lat_dadata", "lon_dadata", "geo_source",
    "Website", "Sector", "Industry", "Subindustry", "OKVED_dadata",
    "Description", "URL", "Source", "parse_status", "parse_reason", "raw_line",
]


def clean_text(value: object, *, remove_urls: bool = True) -> str:
    text = str(value or "")
    text = text.replace("\x00", " ")
    text = BRACKETED_NOISE_RE.sub(" ", text)
    if remove_urls:
        text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\r\n;,.—-")


def normalize_title_ru(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    keep_upper = {"РФ", "РЖД", "МТС", "НЛМК", "ГК", "ТК", "ТГК-2", "ЖКХ", "ГЭС", "ТЭЦ"}
    words = []
    for word in re.split(r"(\s+|-)", value.lower()):
        if not word or word.isspace() or word == "-":
            words.append(word)
        elif word.upper() in keep_upper:
            words.append(word.upper())
        elif re.fullmatch(r"[а-яёa-z]+-?\d+", word, re.I):
            words.append(word.upper())
        else:
            words.append(word[:1].upper() + word[1:])
    return "".join(words).strip()


def _canon_opf(text: str) -> tuple[str, str]:
    upper = re.sub(r"\s+", " ", text.upper()).strip()
    for long, short in sorted(OPF_CANON.items(), key=lambda x: len(x[0]), reverse=True):
        if upper.startswith(long):
            return short, text[len(long):].strip()
    m = OPF_RE.search(text)
    if m:
        return re.sub(r"\s+", " ", m.group(1).upper()).strip(), text[:m.start()] + text[m.end():]
    return "", text


def normalize_official_name(value: object, fallback: object = "") -> str:
    text = str(value or fallback or "").strip()
    if not text:
        return ""
    text = text.replace("“", '"').replace("”", '"').replace("„", '"')
    text = re.sub(r"\s+", " ", text)
    opf, rest = _canon_opf(text)
    content_match = QUOTE_CONTENT_RE.search(text)
    if content_match:
        name = content_match.group(1)
    else:
        name = rest.strip(" \t\r\n.,;:-«»\"")
    name = normalize_title_ru(name)
    if opf and name:
        return f"{opf} «{name}»"
    return name or normalize_title_ru(text.strip("«»\""))


def short_name_from_official(official: object) -> str:
    normalized = normalize_official_name(official)
    m = QUOTE_CONTENT_RE.search(normalized)
    if m:
        return m.group(1).strip()
    return OPF_RE.sub("", normalized).strip(" «»\".,;:-")


def company_name_short(official: str, original_short: object = "") -> str:
    opf_match = OPF_RE.search(official)
    opf = opf_match.group(1).upper() if opf_match else ""
    base = str(original_short or "").strip()
    if not base:
        base = short_name_from_official(official)
    base = re.sub(r"\b(ООО|АО|ПАО|ЗАО|ОАО|МУП|ГУП|ФГУП|ГБУ|ГКУ|МКУ)\b", "", base, flags=re.I)
    base = base.strip(" ,;«»\"")
    if opf and base and not base.upper().endswith(opf):
        return f"{base}, {opf}"
    return base or official


def make_variants(*values: object) -> str:
    seen = set()
    result = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        candidates = {text, normalize_official_name(text), short_name_from_official(text)}
        for variant in candidates:
            variant = re.sub(r"\b(ООО|АО|ПАО|ЗАО|ОАО|МУП|ГУП|ФГУП|ГБУ|ГКУ|МКУ)\b", "", variant, flags=re.I)
            variant = re.sub(r"\s+", " ", variant).strip(" ,;«»")
            if len(variant) < 3:
                continue
            # Avoid single generic words.
            if variant.lower() in {"компания", "инвест", "формат", "сервис", "центр"}:
                continue
            key = variant.lower()
            if key not in seen:
                seen.add(key)
                result.append(variant)
            if len(result) >= 5:
                break
    return ",".join(result[:5])


def normalize_domain(candidate: str) -> str:
    candidate = str(candidate or "").strip().rstrip("/.,;)]}")
    if not candidate:
        return ""
    if candidate.startswith("www."):
        candidate = "https://" + candidate
    if not re.match(r"https?://", candidate, re.I):
        candidate = "https://" + candidate
    parsed = urlparse(candidate)
    domain = parsed.netloc.lower().removeprefix("www.")
    return domain


def extract_site(values, blacklist):
    for value in values:
        text = str(value or "")
        for match in URL_RE.finditer(text):
            domain = normalize_domain(match.group(0))
            if not domain:
                continue
            if any(domain == bad or domain.endswith("." + bad) for bad in blacklist):
                continue
            return domain
    return ""


def extract_region_from_address(address: object) -> str:
    text = str(address or "")
    if not text:
        return ""
    return normalize_ref_region(text)


def clean_numeric(value: object) -> str:
    text = str(value or "").lower().strip()
    if not text or "неизвест" in text or "нет данных" in text:
        return ""
    text = text.replace("около", "").replace("примерно", "")
    text = text.replace("тыс.", "000").replace("тысяч", "000")
    text = text.replace("млрд", "000000000").replace("млн", "000000")
    text = re.sub(r"[^0-9,.-]", "", text).replace(",", ".")
    return text.strip(".-")


def is_active_status(value: object) -> bool:
    return str(value or "").strip().upper() in {"ACTIVE", "ДЕЙСТВУЮЩАЯ", "ДЕЙСТВУЮЩИЙ"}


def _safe_value(value: object) -> object:
    if isinstance(value, str):
        return re.sub(r"[\ud800-\udfff]", "_", value)
    return value


def _write_dicts_to_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_rows = [{k: _safe_value(v) for k, v in row.items()} for row in rows]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=",", quotechar='"', doublequote=True, quoting=csv.QUOTE_MINIMAL, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(safe_rows)


def _ensure_cols(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for col in cols:
        if col not in df.columns:
            df[col] = ""
    return df


def final_normalize_file(
    input_csv: str | Path,
    output_csv: str | Path,
    cfg: Optional[configparser.ConfigParser] = None,
    logger: Optional[logging.Logger] = None,
) -> Path:
    log = logger or logging.getLogger(__name__)
    cfg = cfg or configparser.ConfigParser()
    input_path = Path(input_csv)
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    keep_status = cfg.get("normalization", "keep_status", fallback="all").strip().lower()
    blacklist_raw = cfg.get("normalization", "site_blacklist", fallback="")
    blacklist = set(DEFAULT_REFERENCE_BLACKLIST)
    blacklist.update(x.strip().lower().removeprefix("www.") for x in blacklist_raw.split(",") if x.strip())
    split_by_status = cfg.getboolean("normalization", "split_by_status", fallback=False)
    reports_dir = output_path.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    if split_by_status:
        base_name = input_path.stem
        if base_name.endswith("_geo"):
            base_name = base_name[:-4]
        active_dir = output_path.parent / "active_by_source"
        inactive_dir = output_path.parent / "inactive_by_source"
        active_path = active_dir / f"{base_name}_active.csv"
        inactive_path = inactive_dir / f"{base_name}_inactive.csv"
    else:
        active_path = None
        inactive_path = None

    df = pd.read_csv(input_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    log.info("Loaded %s rows from %s", len(df), input_path.name)

    required_cols = BASE_SOURCE_COLUMNS + [
        "INN_dadata", "status_dadata", "CompanyName_dadata", "Address_dadata",
        "lat_dadata", "lon_dadata", "geo_source", "OKVED_dadata", "CompanyEmployees", "CompanyRevenue",
        "CompanyDescription",
    ]
    df = _ensure_cols(df, required_cols)

    all_rows: list[dict] = []
    duplicate_rows: list[dict] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for idx, row in df.iterrows():
        rowd = {k: str(v or "") for k, v in row.to_dict().items()}
        inn = normalize_inn(rowd.get("INN") or rowd.get("INN_dadata"))
        if not rowd.get("record_id"):
            rowd["record_id"] = make_record_id(
                rowd.get("source_file") or input_path.name,
                rowd.get("source_row_no") or idx + 1,
                inn,
                rowd.get("Sector"), rowd.get("Industry"), rowd.get("Subindustry"),
            )
        key = dedup_key({**rowd, "INN": inn})
        if key in seen and inn:
            duplicate_rows.append({
                "record_id": rowd.get("record_id", ""), "INN": inn,
                "RegionRegistration": rowd.get("RegionRegistration", ""),
                "Sector": rowd.get("Sector", ""), "Industry": rowd.get("Industry", ""), "Subindustry": rowd.get("Subindustry", ""),
                "action": "dropped_exact_composite_duplicate",
            })
            continue
        seen.add(key)

        active = is_active_status(rowd.get("status_dadata"))
        if keep_status == "active" and not active:
            continue

        official_source = rowd.get("CompanyNameOfficial") or rowd.get("CompanyName_dadata") or rowd.get("CompanyName")
        official_norm = normalize_official_name(official_source, fallback=rowd.get("CompanyName_dadata"))
        company_short = company_name_short(official_norm, rowd.get("CompanyName"))
        dadata_name = rowd.get("CompanyName_dadata", "")
        address = rowd.get("Address_dadata", "").strip()
        source = clean_text(rowd.get("Source", ""), remove_urls=False)
        description_raw = clean_text(rowd.get("Description", ""), remove_urls=False)
        old_desc = clean_text(rowd.get("CompanyDescription", ""), remove_urls=False)
        if any(w in old_desc.lower() for w in FORBIDDEN_DESC_WORDS):
            old_desc = ""
        region_code, region_by_inn, fd_by_inn = region_from_inn(inn)
        region_registration = normalize_ref_region(rowd.get("RegionRegistration")) or region_by_inn
        region_name = region_registration or region_by_inn
        federal_district = fd_by_inn
        if region_name:
            from regions_reference import federal_district_for_region
            federal_district = federal_district_for_region(region_name) or federal_district
        region_from_address = extract_region_from_address(address)
        website = extract_site([rowd.get("URL"), source, description_raw, old_desc], blacklist)
        employees = clean_numeric(rowd.get("CompanyEmployees"))
        revenue = clean_numeric(rowd.get("CompanyRevenue"))

        out_row = {
            "record_id": rowd.get("record_id", ""),
            "source_file": rowd.get("source_file") or input_path.name,
            "source_row_no": rowd.get("source_row_no") or str(idx + 1),
            "INN": inn or rowd.get("INN", ""),
            "INN_dadata": rowd.get("INN_dadata", ""),
            "status_dadata": rowd.get("status_dadata", ""),
            "is_active": "1" if active else "0",
            "CompanyNameOfficial": official_norm,
            "CompanyName": company_short,
            "CompanyNameVariants": make_variants(company_short, official_norm, dadata_name),
            "CompanyDescription": old_desc or description_raw,
            "CompanyEmployees": employees,
            "CompanyRevenue": revenue,
            "Address_dadata": address,
            "Region": region_code,
            "RegionName": region_name,
            "RegionRegistration": region_registration,
            "RegionHeadOffice": normalize_ref_region(rowd.get("RegionHeadOffice")) or region_registration,
            "RegionOperation": region_operation_codes({**rowd, "INN": inn}),
            "RegionFromAddress": region_from_address,
            "FederalDistrict": federal_district,
            "lat_dadata": rowd.get("lat_dadata", ""),
            "lon_dadata": rowd.get("lon_dadata", ""),
            "geo_source": rowd.get("geo_source", ""),
            "Website": website,
            "Sector": rowd.get("Sector", ""),
            "Industry": rowd.get("Industry", ""),
            "Subindustry": rowd.get("Subindustry", ""),
            "OKVED_dadata": rowd.get("OKVED_dadata", ""),
            "Description": description_raw,
            "URL": rowd.get("URL", ""),
            "Source": source,
            "parse_status": rowd.get("parse_status", ""),
            "parse_reason": rowd.get("parse_reason", ""),
            "raw_line": rowd.get("raw_line", ""),
        }
        all_rows.append(out_row)

    if duplicate_rows:
        pd.DataFrame(duplicate_rows).to_csv(reports_dir / "deduplication_report.csv", index=False, encoding="utf-8-sig")
        log.info("Dropped exact composite duplicates: %s", len(duplicate_rows))

    if not split_by_status:
        _write_dicts_to_csv(output_path, all_rows, FINAL_COLUMNS)
        log.info("normalize complete file=%s written=%s output=%s", input_path.name, len(all_rows), output_path)
        return output_path

    active_rows = [r for r in all_rows if r.get("is_active") == "1"]
    inactive_rows = [r for r in all_rows if r.get("is_active") != "1"]
    if active_rows:
        _write_dicts_to_csv(active_path, active_rows, FINAL_COLUMNS)
        log.info("normalize active file=%s rows=%s", active_path.name, len(active_rows))
    if inactive_rows:
        _write_dicts_to_csv(inactive_path, inactive_rows, FINAL_COLUMNS)
        log.info("normalize inactive file=%s rows=%s", inactive_path.name, len(inactive_rows))
    return active_path if active_rows and active_path else (inactive_path or output_path)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Final normalize enriched/geocoded company CSV.")
    parser.add_argument("input_csv")
    parser.add_argument("output_csv")
    parser.add_argument("--config", default="config.ini")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = configparser.ConfigParser()
    config.read(args.config, encoding="utf-8")
    final_normalize_file(args.input_csv, args.output_csv, config)
