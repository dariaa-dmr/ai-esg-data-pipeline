"""Final normalization and cleanup for enriched company CSV files."""
from __future__ import annotations

import configparser
import csv
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import pandas as pd

from description_generator import generate_company_description

OPF_RE = re.compile(r"\b(ООО|ОАО|АО|ПАО|ЗАО|ИП|НАО|ФГУП|ГУП|МУП|НКО|ЧУП|ОДО|ТОО)\b", re.I)
QUOTE_CONTENT_RE = re.compile(r"[«\"]([^»\"]+)[»\"]")
URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s,;\]<>\)]+|\b[a-zA-Z0-9][a-zA-Z0-9-]{1,}\.(?:ru|рф|com|org|net|su|by|kz|io)\b[^\s,;\]<>\)]*",
    re.I,
)
REGION_PATTERNS = [
    re.compile(r"\b(Республика\s+\S+)\b", re.I),
    re.compile(r"\b([А-ЯЁа-яё\-]+\s+(?:область|обл\.))\b", re.I),
    re.compile(r"\b([А-ЯЁа-яё\-]+\s+край)\b", re.I),
    re.compile(r"\b(г\.\s*(?:Москва|Санкт-Петербург|Севастополь))\b", re.I),
    re.compile(r"\b([А-ЯЁа-яё\-]+\s+(?:автономный округ|АО))\b", re.I),
]
BRACKETED_NOISE_RE = re.compile(r"\[[^\]]*\]")

DEFAULT_REFERENCE_BLACKLIST = {
    "spark-interfax.ru", "list-org.com", "rusprofile.ru", "zachestnyibiznes.ru",
    "checko.ru", "sbis.ru", "synapsenet.ru", "kartoteka.ru", "audit-it.ru",
    "egrul.nalog.ru", "nalog.gov.ru", "2gis.ru", "yandex.ru", "google.com",
}


def clean_text(value: object) -> str:
    text = str(value or "")
    text = text.replace("\x00", " ")
    text = BRACKETED_NOISE_RE.sub(" ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\r\n;,.—-")


def normalize_title_ru(value: str) -> str:
    words = []
    for word in re.split(r"(\s+|-)", value.lower().strip()):
        if not word or word.isspace() or word == "-":
            words.append(word)
        elif word.upper() in {"РФ", "РЖД", "МТС", "НЛМК", "ГК", "ТК"}:
            words.append(word.upper())
        else:
            words.append(word[:1].upper() + word[1:])
    return "".join(words).strip()


def normalize_official_name(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("\"", "«", 1).replace("\"", "»", 1) if text.count('"') >= 2 else text
    text = re.sub(r"\s+", " ", text)
    opf_match = OPF_RE.search(text)
    opf = opf_match.group(1).upper() if opf_match else ""
    content_match = QUOTE_CONTENT_RE.search(text)
    if content_match:
        name = normalize_title_ru(content_match.group(1))
    elif opf_match:
        name = text[opf_match.end():].strip(" \t\r\n.,;:-«»\"")
        name = normalize_title_ru(name)
    else:
        name = normalize_title_ru(text.strip("«»\""))
    if opf and name:
        return f"{opf} «{name}»"
    return name or text


def short_name_from_official(official: object) -> str:
    normalized = normalize_official_name(official)
    m = QUOTE_CONTENT_RE.search(normalized)
    if m:
        return m.group(1).strip()
    return OPF_RE.sub("", normalized).strip(" «»\".,;:-")


def make_variants(*values: object) -> str:
    seen = set()
    result = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        variants = {text, normalize_official_name(text), short_name_from_official(text)}
        for variant in variants:
            variant = re.sub(r"\s+", " ", variant).strip(" ,;")
            key = variant.lower()
            if variant and key not in seen:
                seen.add(key)
                result.append(variant)
    return ", ".join(result)


def normalize_domain(candidate: str) -> str:
    candidate = candidate.strip().rstrip("/.,;)]}")
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
    """Извлекает название региона (субъекта РФ) из адреса Dadata."""
    text = str(address or "")
    if not text:
        return ""
    # Удаляем индекс и лишние пробелы
    text = re.sub(r'^\d+\s*,?\s*', '', text)
    # Ищем по шаблонам
    for pattern in REGION_PATTERNS:
        m = pattern.search(text)
        if m:
            region = m.group(1).strip()
            return re.sub(r"\s+", " ", region)
    # Если не нашли, пробуем взять первый значимый элемент после индекса
    parts = text.split(',')
    if len(parts) > 1:
        candidate = parts[1].strip()
        if candidate and len(candidate) > 3:
            return candidate
    return ""


def normalize_region_name(region: str) -> str:
    """Приводит название региона к единому формату (Заглавная Первая Буква каждого слова)."""
    if not region or not isinstance(region, str):
        return ""
    words = region.strip().lower().split()
    capitalized = ' '.join(w.capitalize() for w in words)
    replacements = {
        "Чукотский Ао": "Чукотский автономный округ",
        "Ао": "автономный округ",
        "Хмао": "Ханты-Мансийский автономный округ",
        "Янао": "Ямало-Ненецкий автономный округ",
    }
    for bad, good in replacements.items():
        if capitalized == bad:
            capitalized = good
    return capitalized


def clean_numeric(value: object) -> str:
    text = str(value or "").lower()
    if not text or "неизвест" in text:
        return ""
    text = text.replace("около", "").replace("примерно", "")
    text = text.replace("млрд", "000000000").replace("млн", "000000")
    text = re.sub(r"[^0-9,.-]", "", text)
    text = text.replace(",", ".")
    return text.strip(".-")


def is_active_status(value: object) -> bool:
    return str(value or "").strip().upper() in {"ACTIVE", "ДЕЙСТВУЮЩАЯ", "ДЕЙСТВУЮЩИЙ"}


def _write_dicts_to_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    if not rows:
        return
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=',',
                                quotechar='"', doublequote=True, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)


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

    chunksize = cfg.getint("pipeline", "chunksize", fallback=1000)
    keep_status = cfg.get("normalization", "keep_status", fallback="all").strip().lower()
    blacklist_raw = cfg.get("normalization", "site_blacklist", fallback="")
    blacklist = set(DEFAULT_REFERENCE_BLACKLIST)
    blacklist.update(x.strip().lower().removeprefix("www.") for x in blacklist_raw.split(",") if x.strip())

    split_by_status = cfg.getboolean("normalization", "split_by_status", fallback=False)

    if split_by_status:
        base_name = input_path.stem
        if base_name.endswith("_geo"):
            base_name = base_name[:-4]
        active_dir = output_path.parent / "active_by_source"
        inactive_dir = output_path.parent / "inactive_by_source"
        active_dir.mkdir(parents=True, exist_ok=True)
        inactive_dir.mkdir(parents=True, exist_ok=True)
        active_path = active_dir / f"{base_name}_active.csv"
        inactive_path = inactive_dir / f"{base_name}_inactive.csv"
    else:
        active_path = None
        inactive_path = None

    seen_inn: set[str] = set()
    all_rows: list[dict] = []
    written = 0
    dropped_duplicates = 0
    dropped_inactive = 0

    final_columns = [
        "INN", "CompanyNameOfficial", "CompanyName", "CompanyNameVariants",
        "CompanyDescription", "CompanyEmployees", "CompanyRevenue",
        "Address_dadata", "RegionFromAddress", "lat_dadata", "lon_dadata",
        "Website", "Sector", "Industry", "Subindustry", "OKVED_dadata",
        "Source", "is_active"
    ]

    df = pd.read_csv(input_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    log.info(f"Loaded {len(df)} rows from {input_path.name}")

    required_cols = [
        "INN", "INN_dadata", "status_dadata", "CompanyNameOfficial", "CompanyName",
        "CompanyName_dadata", "Description", "Source", "URL", "Address_dadata",
        "lat_dadata", "lon_dadata", "Sector", "Industry", "Subindustry",
        "OKVED_dadata", "CompanyEmployees", "CompanyRevenue"
    ]
    for col in required_cols:
        if col not in df.columns:
            df[col] = ""

    for _, row in df.iterrows():
        inn = "".join(ch for ch in str(row.get("INN") or row.get("INN_dadata") or "") if ch.isdigit())
        if inn and inn in seen_inn:
            dropped_duplicates += 1
            continue
        if inn:
            seen_inn.add(inn)

        active = is_active_status(row.get("status_dadata"))
        if keep_status == "active" and not active:
            dropped_inactive += 1
            continue

        official_source = row.get("CompanyNameOfficial") or row.get("CompanyName_dadata") or row.get("CompanyName")
        official_norm = normalize_official_name(official_source)
        company_short = str(row.get("CompanyName") or "").strip() or short_name_from_official(official_norm)
        dadata_name = str(row.get("CompanyName_dadata") or "").strip()
        address = str(row.get("Address_dadata") or "").strip()
        sector = row.get("Sector", "")
        industry = row.get("Industry", "")
        subindustry = row.get("Subindustry", "")
        okved = row.get("OKVED_dadata", "")
        source_raw = row.get("Source", "")
        source = clean_text(source_raw)
        url = row.get("URL", "")
        description_raw = row.get("Description", "")

        row_for_desc = {
            "INN": inn,
            "CompanyNameOfficial": official_norm,
            "Address_dadata": address,
            "OKVED_dadata": okved,
            "Description": description_raw,
            "Sector": sector,
            "Industry": industry,
            "Subindustry": subindustry,
        }
        company_description, employees, revenue = generate_company_description(row_for_desc)

        website = extract_site([url, source, description_raw, company_description], blacklist)
        region_raw = extract_region_from_address(address)
        region = normalize_region_name(region_raw)

        out_row = {
            "INN": inn or str(row.get("INN") or "").strip(),
            "CompanyNameOfficial": official_norm,
            "CompanyName": company_short,
            "CompanyNameVariants": make_variants(company_short, official_norm, dadata_name),
            "CompanyDescription": company_description,
            "CompanyEmployees": employees,
            "CompanyRevenue": revenue,
            "Address_dadata": address,
            "RegionFromAddress": region,
            "lat_dadata": str(row.get("lat_dadata") or ""),
            "lon_dadata": str(row.get("lon_dadata") or ""),
            "Website": website,
            "Sector": sector,
            "Industry": industry,
            "Subindustry": subindustry,
            "OKVED_dadata": okved,
            "Source": source,
            "is_active": "1" if active else "0"
        }
        all_rows.append(out_row)
        written += 1

    if not all_rows:
        log.info("normalize complete file=%s no rows", input_path.name)
        return output_path

    if not split_by_status:
        _write_dicts_to_csv(output_path, all_rows, final_columns)
        log.info("normalize complete file=%s written=%s output=%s", input_path.name, written, output_path)
        return output_path

    active_rows = [r for r in all_rows if r.get("is_active") == "1"]
    inactive_rows = [r for r in all_rows if r.get("is_active") != "1"]

    if active_rows:
        _write_dicts_to_csv(active_path, active_rows, final_columns)
        log.info("normalize active file=%s rows=%s", active_path.name, len(active_rows))
    else:
        log.info("normalize no active rows for %s, skipping file", input_path.name)

    if inactive_rows:
        _write_dicts_to_csv(inactive_path, inactive_rows, final_columns)
        log.info("normalize inactive file=%s rows=%s", inactive_path.name, len(inactive_rows))
    else:
        log.info("normalize no inactive rows for %s, skipping file", input_path.name)

    return active_path if active_path else inactive_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Final normalize enriched company CSV.")
    parser.add_argument("input_csv")
    parser.add_argument("output_csv")
    parser.add_argument("--config", default="config.ini")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = configparser.ConfigParser()
    config.read(args.config, encoding="utf-8")
    final_normalize_file(args.input_csv, args.output_csv, config)