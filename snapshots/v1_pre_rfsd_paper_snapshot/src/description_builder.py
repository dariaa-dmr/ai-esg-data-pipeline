"""Build human-readable company descriptions from final CSV fields.

Mode 2 implementation: YandexGPT is used only as an editor for existing fields.
It must not search the web or add unsupported facts. If YandexGPT credentials are
absent or the generated text fails quality checks, the script uses a conservative
rule-based fallback and marks the row for review.
"""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from normalizer import normalize_official_name, company_name_short, make_variants, clean_text
from paths import read_config, load_paths, resolve_path
from regions_reference import normalize_region_name, region_from_inn, region_operation_codes
from yandexgpt_client import YandexGPTClient

INPUT_FACT_COLUMNS = [
    "INN", "CompanyNameOfficial", "CompanyName", "CompanyName_dadata", "CompanyNameVariants",
    "Sector", "Industry", "Subindustry", "Region", "RegionName", "RegionRegistration", "RegionHeadOffice", "RegionOperation",
    "Address_dadata", "OKVED_dadata", "Description", "CompanyDescription",
    "CompanyEmployees", "CompanyEmployeesYear", "CompanyEmployeesSource",
    "CompanyRevenue", "CompanyRevenueRawRUB", "CompanyRevenueYear", "CompanyRevenueSource",
    "CompanyBudget", "CompanyBudgetYear", "CompanyBudgetSource", "CompanyFoundedYear",
    "SparkActivity", "SparkEvidenceText", "SparkShortName", "SparkFullName", "SparkOKVEDMainName",
    "Website", "SparkWebsite", "Source",
]
FORBIDDEN_WORDS = ["лидер", "лучший", "уникальный", "динамично развивающийся", "неизвестн", "нет данных"]


class DescriptionCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS descriptions_cache (
                input_hash TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                quality_score INTEGER NOT NULL,
                issues TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def get(self, input_hash: str) -> Optional[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT description,status,quality_score,issues,model FROM descriptions_cache WHERE input_hash=?",
            (input_hash,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"description": row[0], "status": row[1], "quality_score": row[2], "issues": row[3], "model": row[4]}

    def set(self, input_hash: str, description: str, status: str, quality_score: int, issues: str, model: str) -> None:
        self.conn.execute(
            "REPLACE INTO descriptions_cache VALUES (?, ?, ?, ?, ?, ?, ?)",
            (input_hash, description, status, int(quality_score), issues, model, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def setup_logger() -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger("description_builder")


def input_hash(row: dict) -> str:
    payload = {col: str(row.get(col, "")) for col in INPUT_FACT_COLUMNS}
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def extract_year(*values: object) -> str:
    for v in values:
        text = str(v or "")
        m = re.search(r"\b(19|20)\d{2}\b", text)
        if m:
            return m.group(0)
    return ""


def extract_city(address: object, region: object = "") -> str:
    text = str(address or "")
    if text:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        for p in parts:
            if re.search(r"\bг\.?\s+", p, re.I):
                return re.sub(r"^г\.?\s*", "", p, flags=re.I).strip()
        for p in parts:
            if "область" not in p.lower() and "респ" not in p.lower() and "край" not in p.lower() and len(p) > 2:
                return p
    return str(region or "").strip()


def numeric_clean(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text or "неизвест" in text or "нет данных" in text:
        return ""
    text = re.sub(r"[^0-9,.]", "", text).replace(",", ".")
    return text.strip(".")




def extract_employees_from_text(*values: object) -> str:
    for v in values:
        text = str(v or "")
        patterns = [
            r"(?:численность|среднесписочная численность|штат|сотрудников|работников)[^0-9]{0,80}(?:около|примерно|более|свыше)?\s*(\d+[\d\s,.]*)\s*(тыс\.?|тысяч)?",
            r"(?:около|примерно|более|свыше)\s*(\d+[\d\s,.]*)\s*(тыс\.?|тысяч)?\s*(?:человек|сотрудник|сотрудников|работник|работников)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                num = m.group(1).replace(" ", "").replace(",", ".")
                mult = 1000 if (len(m.groups()) > 1 and m.group(2)) else 1
                try:
                    return str(int(float(num) * mult))
                except Exception:
                    return num
    return ""


def extract_revenue_from_text(*values: object) -> str:
    for v in values:
        text = str(v or "")
        patterns = [
            r"(?:выручка|доходы|годовая выручка|бюджет)[^0-9]{0,80}(?:около|примерно|более|свыше)?\s*(\d+[\d\s,.]*)\s*(млрд|млн|тыс)?",
            r"(?:около|примерно|более|свыше)\s*(\d+[\d\s,.]*)\s*(млрд|млн)\s*руб",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                num = m.group(1).replace(" ", "").replace(",", ".")
                unit = (m.group(2) or "").lower() if len(m.groups()) > 1 else ""
                try:
                    val = float(num)
                    if unit.startswith("млн"):
                        val = val / 1000
                    elif unit.startswith("тыс"):
                        val = val / 1_000_000
                    elif not unit:
                        # assume already млрд if not full rubles
                        pass
                    return str(val)
                except Exception:
                    return num
    return ""

def format_employees(value: str) -> str:
    value = numeric_clean(value)
    if not value:
        return ""
    try:
        n = float(value)
    except Exception:
        return value
    if n >= 1000:
        return f"{round(n / 1000, 1):g}".replace(".", ",") + " тыс."
    return f"{int(round(n))}"


def format_revenue(value: str) -> str:
    value = numeric_clean(value)
    if not value:
        return ""
    try:
        n = float(value)
    except Exception:
        return value
    # If value looks like full rubles, convert to млрд руб.
    if n > 1_000_000:
        n = n / 1_000_000_000
    return f"{n:.1f}".replace(".0", "").replace(".", ",") + " млрд руб."


def tail_with_years(employees: str, revenue: str, employees_year: str = "", revenue_year: str = "", *, budget: bool = False) -> str:
    emp_part = f"Численность работников — около {employees} человек"
    if employees_year:
        emp_part += f" по данным за {employees_year} год"
    fin_kind = "годовой бюджет" if budget else "годовая выручка"
    fin_part = f"{fin_kind} — около {revenue}"
    if revenue_year:
        fin_part += f" по данным за {revenue_year} год"
    return f"{emp_part}, {fin_part}."


def is_budget_org(row: dict) -> bool:
    name = (str(row.get("CompanyNameOfficial", "")) + " " + str(row.get("CompanyName", ""))).upper()
    return any(token in name for token in ["ГБУ", "ГКУ", "МКУ", "ГУП", "ФГУП", "МУП", "КАЗЕН", "БЮДЖЕТ"])


def activity_phrase(row: dict) -> str:
    sub = str(row.get("Subindustry") or "").strip()
    ind = str(row.get("Industry") or "").strip()
    okved = str(row.get("OKVED_dadata") or "").strip()
    desc = clean_text(row.get("Description") or row.get("CompanyDescription") or "", remove_urls=True)
    if desc and len(desc) > 40:
        first = re.split(r"(?<=[.!?])\s+", desc)[0].strip(" .")
        if first and not any(w in first.lower() for w in FORBIDDEN_WORDS):
            return first[:220].lower()
    if sub:
        return f"деятельностью в подотрасли {sub.lower()}"
    if ind:
        return f"деятельностью в отрасли {ind.lower()}"
    if okved:
        return f"деятельностью по ОКВЭД {okved}"
    return "профильной деятельностью, указанной в исходных данных"


def key_fact_phrase(row: dict) -> str:
    sub = str(row.get("Subindustry") or "").strip().lower()
    ind = str(row.get("Industry") or "").strip().lower()
    if "водоснаб" in sub or "водоотвед" in sub:
        return "Ключевая функция компании связана с эксплуатацией систем водоснабжения и водоотведения."
    if "тепл" in sub:
        return "Ключевая функция компании связана с эксплуатацией тепловой инфраструктуры и теплоснабжением потребителей."
    if "элект" in sub or "энерг" in ind:
        return "Ключевая функция компании связана с эксплуатацией энергетической инфраструктуры и обеспечением потребителей ресурсами."
    if "транспорт" in sub or "перевоз" in sub:
        return "Ключевая функция компании связана с организацией перевозок и эксплуатацией транспортной инфраструктуры."
    if "отход" in sub:
        return "Ключевая функция компании связана с обращением с отходами и эксплуатацией коммунальной инфраструктуры."
    if sub:
        return f"Ключевая функция компании связана с направлением «{sub}»."
    return "Ключевая функция компании связана с обслуживанием профильной инфраструктуры."


def build_rule_description(row: dict) -> tuple[str, list[str]]:
    issues: list[str] = []
    official = normalize_official_name(row.get("CompanyNameOfficial") or row.get("CompanyName_dadata") or row.get("CompanyName"))
    region_code, region_by_inn, _fd = region_from_inn(row.get("INN"))
    region = normalize_region_name(row.get("RegionRegistration") or row.get("RegionName")) or region_by_inn
    city = extract_city(row.get("Address_dadata"), region)
    year = str(row.get("CompanyFoundedYear") or "").strip() or extract_year(row.get("Description"), row.get("CompanyDescription"), row.get("Source"))
    employees_year = str(row.get("CompanyEmployeesYear") or "").strip()[:4]
    revenue_year = str(row.get("CompanyRevenueYear") or row.get("CompanyBudgetYear") or "").strip()[:4]
    employees_raw = row.get("CompanyEmployees") or extract_employees_from_text(row.get("Description"), row.get("CompanyDescription"), row.get("Source"))
    revenue_raw = row.get("CompanyRevenueRawRUB") or row.get("CompanyRevenue") or row.get("CompanyBudget") or extract_revenue_from_text(row.get("Description"), row.get("CompanyDescription"), row.get("Source"))
    employees = format_employees(employees_raw)
    revenue = format_revenue(revenue_raw)
    if not official:
        issues.append("missing_company_name")
        official = "Компания"
    if not year:
        issues.append("missing_year")
    if not city:
        issues.append("missing_city")
        city = region or "указанном регионе"
    if not region:
        issues.append("missing_region")
        region = "указанный регион"
    if not employees:
        issues.append("missing_employees")
    if not revenue:
        issues.append("missing_revenue_or_budget")

    verb = "работает"
    if year:
        sent1 = f"{official} {verb} с {year} года в {city} и занимается {activity_phrase(row)}."
    else:
        sent1 = f"{official} работает в {city} и занимается {activity_phrase(row)}."
    sent2 = f"Компания обслуживает {region}; основная база связана с {city}."
    sent3 = key_fact_phrase(row)
    if employees and revenue:
        sent4 = tail_with_years(
            employees,
            revenue,
            employees_year=employees_year,
            revenue_year=revenue_year,
            budget=is_budget_org({**row, "CompanyNameOfficial": official}),
        )
    else:
        sent4 = "Данные о численности работников и годовых финансовых показателях требуют уточнения."
    return " ".join([sent1, sent2, sent3, sent4]), issues


def build_prompt(row: dict) -> tuple[str, str]:
    system_prompt = (
        "Ты редактор корпоративных описаний. Составляй текст только по переданным полям. "
        "Не ищи информацию в интернете и не добавляй неподтверждённые факты. "
        "Не упоминай источники вроде hh.ru, РБК, открытые источники, официальный сайт или сайт компании. "
        "Стиль нейтральный, деловой, без рекламы."
    )
    facts = {col: str(row.get(col, "")) for col in INPUT_FACT_COLUMNS}

    rule_desc, _missing = build_rule_description(row)
    rule_sentences = split_sentences(rule_desc)
    required_tail = rule_sentences[-1] if rule_sentences else ""

    user_prompt = (
        "Сформируй CompanyDescription на русском языке по инструкции.\n"
        "Нужно ровно 4 предложения. Общая длина желательно 500–650 знаков.\n"
        "Первые 3 предложения можно отредактировать по смыслу только на основе JSON ниже.\n"
        "Первое предложение: название, год если есть, город или регион, роль или вид деятельности.\n"
        "Второе предложение: география работы или региональная привязка.\n"
        "Третье предложение: конкретная функция, актив, услуга или инфраструктурный факт из переданных полей.\n"
        "Четвёртое предложение скопируй ДОСЛОВНО без изменений.\n\n"
        f"ОБЯЗАТЕЛЬНОЕ 4-Е ПРЕДЛОЖЕНИЕ:\n{required_tail}\n\n"
        "Запрещено добавлять факты и источники, которых нет в JSON.\n"
        "Запрещено писать: по открытым данным, по открытым источникам, hh.ru, РБК, официальный сайт, сайт компании, на дату поиска.\n"
        "Запрещено использовать рекламные слова: лидер, лучший, уникальный, динамично развивающийся.\n"
        "Не вставляй ссылки, адреса и пояснения.\n\n"
        f"Поля строки JSON:\n{json.dumps(facts, ensure_ascii=False, indent=2)}\n\n"
        "Верни только текст описания без пояснений. Ровно 4 предложения. "
        "Четвёртое предложение должно полностью совпадать с обязательным 4-м предложением."
    )
    return system_prompt, user_prompt


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []
    protected = text

    # Protect common Russian numeric and financial abbreviations.
    protected = re.sub(r"\bруб\.", "руб<dot>", protected, flags=re.I)
    protected = re.sub(r"\bтыс\.", "тыс<dot>", protected, flags=re.I)
    protected = re.sub(r"\bмлн\.", "млн<dot>", protected, flags=re.I)
    protected = re.sub(r"\bмлрд\.", "млрд<dot>", protected, flags=re.I)

    # Protect address/territory abbreviations such as ВН.ТЕР.Г.
    protected = re.sub(r"\bВН\.", "ВН<dot>", protected, flags=re.I)
    protected = re.sub(r"\bТЕР\.", "ТЕР<dot>", protected, flags=re.I)
    protected = re.sub(r"(?<![А-Яа-яA-Za-z])[Гг]\.", "г<dot>", protected)

    parts = [
        part.replace("<dot>", ".").strip()
        for part in re.split(r"(?<=[.!?])\s+", protected)
        if part.strip()
    ]
    return parts


def enforce_required_tail(text: str, row: dict) -> str:
    rule_desc, _missing = build_rule_description(row)
    rule_sentences = split_sentences(rule_desc)
    if not rule_sentences:
        return text
    required_tail = rule_sentences[-1]
    sentences = split_sentences(text)
    if len(sentences) >= 3:
        return " ".join(sentences[:3] + [required_tail])
    return text


def sanitize_description_text(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    replacements = {
        "на дату поиска действует": "является действующей организацией",
        "На дату поиска действует": "Является действующей организацией",
        "по открытым данным": "по переданным данным",
        "По открытым данным": "По переданным данным",
        "по открытым источникам": "по переданным данным",
        "По открытым источникам": "По переданным данным",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def expand_short_description(text: str, row: dict, min_len: int = 420) -> str:
    text = sanitize_description_text(text)
    sentences = split_sentences(text)
    if len(sentences) != 4 or len(text) >= min_len:
        return text

    region = str(row.get("RegionName") or row.get("RegionRegistration") or row.get("RegionOperation") or "").strip()
    profile = str(row.get("Subindustry") or row.get("Industry") or row.get("OKVED") or row.get("SparkActivity") or "").strip()

    additions = []
    if region:
        additions.append(f"региональная привязка сформирована по направлению «{region}»")
    if profile:
        additions.append(f"профиль деятельности относится к направлению «{profile}»")

    if not additions:
        additions.append("операционная роль компании описана на основе переданных регистрационных и отраслевых данных")

    extra = "; " + ", а ".join(additions)

    # Расширяем 3-е предложение, чтобы сохранить ровно 4 предложения и обязательный хвост в 4-м.
    sentences[2] = sentences[2].rstrip(".") + extra + "."
    return " ".join(sentences)


def validate_description(text: str, row: dict | None = None) -> tuple[int, str, list[str]]:
    issues: list[str] = []
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    sentences = split_sentences(text)
    if len(sentences) != 4:
        issues.append(f"sentence_count_{len(sentences)}")
    if len(text) < 420:
        issues.append("too_short")
    if len(text) > 800:
        issues.append("too_long")
    lower = text.lower()
    for word in FORBIDDEN_WORDS:
        if word in lower:
            issues.append(f"forbidden_word_{word}")
    if re.search(r"https?://|www\.", text, re.I):
        issues.append("contains_link")
    if not re.search(r"\b(19|20)\d{2}\b", text):
        issues.append("missing_year")
    if not re.search(r"Численность работников\s+—\s+около", text):
        issues.append("missing_required_tail")
    if "требуют уточнения" in lower:
        issues.append("missing_financial_or_employees_values")
    score = max(0, 100 - 12 * len(issues))
    status = "ok" if not issues else "needs_review"
    return score, status, issues


def build_descriptions(
    input_csv: Path,
    output_csv: Path,
    reports_dir: Path,
    cfg: configparser.ConfigParser,
    *,
    logger: Optional[logging.Logger] = None,
) -> dict[str, int]:
    log = logger or setup_logger()
    reports_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(input_csv, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    for col in INPUT_FACT_COLUMNS + ["record_id"]:
        if col not in df.columns:
            df[col] = ""

    mode = cfg.get("descriptions", "description_mode", fallback="llm_from_existing_fields").strip()
    cache_path = resolve_path(cfg, "paths", "description_cache_db", "cache/descriptions.sqlite")
    cache = DescriptionCache(cache_path)
    client = YandexGPTClient.from_config(cfg, logger=log) if mode != "rules_only" else None
    rows = []
    quality_rows = []
    used_cache = 0
    called_llm = 0
    fallback_rows = 0

    for idx, row in df.iterrows():
        rowd = {k: str(v or "") for k, v in row.to_dict().items()}

        # Normalize SPARK merged fields: pandas merge may create _x/_y columns.
        # Description builder uses base fields, so fill them from SPARK-enriched _y columns.
        if not rowd.get("CompanyEmployees"):
            rowd["CompanyEmployees"] = rowd.get("CompanyEmployees_y") or rowd.get("CompanyEmployees_x") or ""
        if not rowd.get("CompanyRevenue"):
            rowd["CompanyRevenue"] = rowd.get("CompanyRevenue_y") or rowd.get("CompanyRevenue_x") or ""
        if not rowd.get("CompanyBudget"):
            rowd["CompanyBudget"] = rowd.get("CompanyBudget_y") or rowd.get("CompanyBudget_x") or ""
        if not rowd.get("CompanyRevenueRawRUB"):
            rowd["CompanyRevenueRawRUB"] = rowd.get("CompanyRevenueRawRUB_y") or rowd.get("CompanyRevenueRawRUB_x") or ""
        if not rowd.get("CompanyBudgetRawRUB"):
            rowd["CompanyBudgetRawRUB"] = rowd.get("CompanyBudgetRawRUB_y") or rowd.get("CompanyBudgetRawRUB_x") or ""

        # Normalize linked fields before prompt.
        official = normalize_official_name(rowd.get("CompanyNameOfficial") or rowd.get("CompanyName_dadata") or rowd.get("CompanyName"))
        rowd["CompanyNameOfficial"] = official
        rowd["CompanyName"] = company_name_short(official, rowd.get("CompanyName"))
        rowd["CompanyNameVariants"] = make_variants(rowd.get("CompanyName"), official, rowd.get("CompanyName_dadata"))
        code, reg_by_inn, _fd = region_from_inn(rowd.get("INN"))
        rowd["Region"] = rowd.get("Region") or code
        rowd["RegionName"] = normalize_region_name(rowd.get("RegionName") or rowd.get("RegionRegistration")) or reg_by_inn
        rowd["RegionRegistration"] = normalize_region_name(rowd.get("RegionRegistration")) or rowd["RegionName"]
        rowd["RegionOperation"] = rowd.get("RegionOperation") or region_operation_codes(rowd)

        h = input_hash(rowd)
        cached = cache.get(h)
        model = ""
        if cached:
            desc = cached["description"]
            score = int(cached["quality_score"])
            status = str(cached["status"])
            issues = str(cached["issues"]).split(";") if cached["issues"] else []
            model = str(cached["model"])
            used_cache += 1
        else:
            desc = ""
            if client is not None:
                system_prompt, user_prompt = build_prompt(rowd)
                desc = client.complete(system_prompt, user_prompt).strip().strip('"')
                desc = sanitize_description_text(desc)
                desc = enforce_required_tail(desc, rowd)
                desc = expand_short_description(desc, rowd)
                called_llm += 1
                model = cfg.get("yandexgpt", "model_uri", fallback="").strip() or "yandexgpt"
            if not desc:
                desc, _missing = build_rule_description(rowd)
                desc = sanitize_description_text(desc)
                desc = expand_short_description(desc, rowd)
                fallback_rows += 1
                model = "rules_fallback_no_llm" if client is None and mode != "rules_only" else "rules_only"
            score, status, issues = validate_description(desc, rowd)
            # If LLM returned broken text, fall back to deterministic version.
            if client is not None and status != "ok":
                rule_desc, _missing = build_rule_description(rowd)
                rule_desc = sanitize_description_text(rule_desc)
                rule_desc = expand_short_description(rule_desc, rowd)
                r_score, r_status, r_issues = validate_description(rule_desc, rowd)
                if r_score >= score:
                    desc, score, status, issues = rule_desc, r_score, r_status, r_issues
                    model = "rules_fallback_after_llm_quality"
                    fallback_rows += 1
            cache.set(h, desc, status, score, ";".join(issues), model)

        out = row.to_dict()
        out.update({
            "CompanyNameOfficial": rowd["CompanyNameOfficial"],
            "CompanyName": rowd["CompanyName"],
            "CompanyNameVariants": rowd["CompanyNameVariants"],
            "Region": rowd["Region"],
            "RegionName": rowd["RegionName"],
            "RegionRegistration": rowd["RegionRegistration"],
            "RegionOperation": rowd["RegionOperation"],
            "CompanyDescription": desc,
            "description_status": status,
            "description_quality_score": str(score),
            "description_issues": ";".join(issues),
            "description_model": model,
            "description_cached": "1" if cached else "0",
            "description_input_hash": h,
        })
        rows.append(out)
        quality_rows.append({
            "record_id": str(rowd.get("record_id", "")),
            "INN": str(rowd.get("INN", "")),
            "CompanyNameOfficial": rowd["CompanyNameOfficial"],
            "description_status": status,
            "description_quality_score": str(score),
            "description_issues": ";".join(issues),
            "description_model": model,
        })

    out_df = pd.DataFrame(rows)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    qdf = pd.DataFrame(quality_rows)
    qdf.to_csv(reports_dir / "description_quality.csv", index=False, encoding="utf-8-sig")
    qdf[qdf["description_status"] != "ok"].to_csv(reports_dir / "description_needs_review.csv", index=False, encoding="utf-8-sig")
    summary = {
        "input_rows": len(df),
        "output_rows": len(out_df),
        "ok_rows": int((qdf["description_status"] == "ok").sum()) if not qdf.empty else 0,
        "needs_review_rows": int((qdf["description_status"] != "ok").sum()) if not qdf.empty else 0,
        "cache_hits": used_cache,
        "llm_calls": called_llm,
        "fallback_rows": fallback_rows,
    }
    pd.DataFrame([summary]).to_csv(reports_dir / "description_run_summary.csv", index=False, encoding="utf-8-sig")
    log.info("Descriptions complete: %s", summary)
    cache.close()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build CompanyDescription and name fields from final active CSV.")
    parser.add_argument("--config", default="config.ini")
    parser.add_argument("--input", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    cfg = read_config(args.config)
    paths = load_paths(cfg, create=True)
    input_path = Path(args.input) if args.input else resolve_path(cfg, "descriptions", "input_csv", "final/all_sectors_final_active_spark_included.csv")
    if not input_path.exists() and not args.input:
        input_path = resolve_path(cfg, "descriptions", "fallback_input_csv", "final/all_sectors_final_active.csv")
    output_path = Path(args.output) if args.output else resolve_path(cfg, "descriptions", "output_csv", "final/all_sectors_final_active_described.csv")
    build_descriptions(input_path, output_path, paths.reports, cfg, logger=setup_logger())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
