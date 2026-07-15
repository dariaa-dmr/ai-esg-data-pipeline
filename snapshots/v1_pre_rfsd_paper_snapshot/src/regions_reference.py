"""Region code/name/federal district mapping and normalization."""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Optional

# region_code -> (official region name, federal district)
REGION_BY_CODE: dict[str, tuple[str, str]] = {
    "01": ("Республика Адыгея", "ЮФО"), "02": ("Республика Башкортостан", "ПФО"),
    "03": ("Республика Бурятия", "ДФО"), "04": ("Республика Алтай", "СФО"),
    "05": ("Республика Дагестан", "СКФО"), "06": ("Республика Ингушетия", "СКФО"),
    "07": ("Кабардино-Балкарская Республика", "СКФО"), "08": ("Республика Калмыкия", "ЮФО"),
    "09": ("Карачаево-Черкесская Республика", "СКФО"), "10": ("Республика Карелия", "СЗФО"),
    "11": ("Республика Коми", "СЗФО"), "12": ("Республика Марий Эл", "ПФО"),
    "13": ("Республика Мордовия", "ПФО"), "14": ("Республика Саха (Якутия)", "ДФО"),
    "15": ("Республика Северная Осетия — Алания", "СКФО"), "16": ("Республика Татарстан", "ПФО"),
    "17": ("Республика Тыва", "СФО"), "18": ("Удмуртская Республика", "ПФО"),
    "19": ("Республика Хакасия", "СФО"), "20": ("Чеченская Республика", "СКФО"),
    "21": ("Чувашская Республика", "ПФО"), "22": ("Алтайский край", "СФО"),
    "23": ("Краснодарский край", "ЮФО"), "24": ("Красноярский край", "СФО"),
    "25": ("Приморский край", "ДФО"), "26": ("Ставропольский край", "СКФО"),
    "27": ("Хабаровский край", "ДФО"), "28": ("Амурская область", "ДФО"),
    "29": ("Архангельская область", "СЗФО"), "30": ("Астраханская область", "ЮФО"),
    "31": ("Белгородская область", "ЦФО"), "32": ("Брянская область", "ЦФО"),
    "33": ("Владимирская область", "ЦФО"), "34": ("Волгоградская область", "ЮФО"),
    "35": ("Вологодская область", "СЗФО"), "36": ("Воронежская область", "ЦФО"),
    "37": ("Ивановская область", "ЦФО"), "38": ("Иркутская область", "СФО"),
    "39": ("Калининградская область", "СЗФО"), "40": ("Калужская область", "ЦФО"),
    "41": ("Камчатский край", "ДФО"), "42": ("Кемеровская область — Кузбасс", "СФО"),
    "43": ("Кировская область", "ПФО"), "44": ("Костромская область", "ЦФО"),
    "45": ("Курганская область", "УФО"), "46": ("Курская область", "ЦФО"),
    "47": ("Ленинградская область", "СЗФО"), "48": ("Липецкая область", "ЦФО"),
    "49": ("Магаданская область", "ДФО"), "50": ("Московская область", "ЦФО"),
    "51": ("Мурманская область", "СЗФО"), "52": ("Нижегородская область", "ПФО"),
    "53": ("Новгородская область", "СЗФО"), "54": ("Новосибирская область", "СФО"),
    "55": ("Омская область", "СФО"), "56": ("Оренбургская область", "ПФО"),
    "57": ("Орловская область", "ЦФО"), "58": ("Пензенская область", "ПФО"),
    "59": ("Пермский край", "ПФО"), "60": ("Псковская область", "СЗФО"),
    "61": ("Ростовская область", "ЮФО"), "62": ("Рязанская область", "ЦФО"),
    "63": ("Самарская область", "ПФО"), "64": ("Саратовская область", "ПФО"),
    "65": ("Сахалинская область", "ДФО"), "66": ("Свердловская область", "УФО"),
    "67": ("Смоленская область", "ЦФО"), "68": ("Тамбовская область", "ЦФО"),
    "69": ("Тверская область", "ЦФО"), "70": ("Томская область", "СФО"),
    "71": ("Тульская область", "ЦФО"), "72": ("Тюменская область", "УФО"),
    "73": ("Ульяновская область", "ПФО"), "74": ("Челябинская область", "УФО"),
    "75": ("Забайкальский край", "ДФО"), "76": ("Ярославская область", "ЦФО"),
    "77": ("Москва", "ЦФО"), "78": ("Санкт-Петербург", "СЗФО"),
    "79": ("Еврейская автономная область", "ДФО"), "82": ("Камчатский край", "ДФО"), "83": ("Ненецкий автономный округ", "СЗФО"),
    "86": ("Ханты-Мансийский автономный округ — Югра", "УФО"),
    "87": ("Чукотский автономный округ", "ДФО"), "89": ("Ямало-Ненецкий автономный округ", "УФО"),
    "91": ("Республика Крым", "ЮФО"), "92": ("Севастополь", "ЮФО"),
}

ALIASES: dict[str, str] = {}
for code, (name, _fd) in REGION_BY_CODE.items():
    aliases = {name, name.replace(" — ", " "), name.replace("Республика ", "респ "), name.replace("область", "обл")}
    if name == "Москва": aliases.update({"г Москва", "город Москва"})
    if name == "Санкт-Петербург": aliases.update({"г Санкт-Петербург", "город Санкт-Петербург", "СПб", "Санкт Петербург"})
    if name == "Севастополь": aliases.update({"г Севастополь", "город Севастополь"})
    if name == "Республика Бурятия": aliases.update({"Респ Бурятия", "Бурятия"})
    if name == "Республика Саха (Якутия)": aliases.update({"Респ Саха", "Респ Саха Якутия", "Якутия", "Саха Якутия"})
    if name == "Республика Дагестан": aliases.update({"Респ Дагестан", "Дагестан"})
    if name == "Забайкальский край": aliases.update({"Забайкальский кр"})
    for a in aliases:
        key = re.sub(r"\s+", " ", a.lower().replace("ё", "е")).strip(" .,;")
        ALIASES[key] = name


def _alias_key(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip(" .,;")


def _register_alias(alias: object, official_name: str) -> None:
    key = _alias_key(alias)
    if key:
        ALIASES[key] = official_name


def load_region_reference(csv_path: str | Path) -> None:
    """Load/extend region mapping from a CSV reference file.

    Expected columns: region_code, region_name, federal_district, aliases.
    aliases are separated with |. The hardcoded reference remains as fallback.
    """
    path = Path(csv_path)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = str(row.get("region_code") or row.get("code") or "").strip().zfill(2)
            name = str(row.get("region_name") or row.get("name") or "").strip()
            fd = str(row.get("federal_district") or row.get("fd") or "").strip()
            if not code or not name:
                continue
            REGION_BY_CODE[code] = (name, fd)
            _register_alias(name, name)
            for alias in str(row.get("aliases") or "").split("|"):
                _register_alias(alias, name)


def configure_region_reference(cfg) -> None:
    """Load reference file configured in [references] regions_csv if present."""
    try:
        from paths import resolve_path
        path = resolve_path(cfg, "references", "regions_csv", "references/regions.csv")
        load_region_reference(path)
    except Exception:
        # Region normalization must never crash the pipeline.
        return


def region_from_inn(inn: object) -> tuple[str, str, str]:
    digits = "".join(ch for ch in str(inn or "") if ch.isdigit())
    code = digits[:2] if len(digits) >= 2 else ""
    if code in REGION_BY_CODE:
        name, fd = REGION_BY_CODE[code]
        return code, name, fd
    return code, "", ""


def normalize_region_name(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "").replace("ё", "е")).strip(" .,;")
    if not text:
        return ""
    key = text.lower()
    if key in ALIASES:
        return ALIASES[key]
    # Try containment for addresses such as "Респ Бурятия, г Улан-Удэ".
    for alias, official in sorted(ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True):
        if alias and re.search(r"(?<![а-яa-z])" + re.escape(alias) + r"(?![а-яa-z])", key):
            return official
    return text


def federal_district_for_region(region: object) -> str:
    name = normalize_region_name(region)
    for _code, (official, fd) in REGION_BY_CODE.items():
        if official == name:
            return fd
    return ""


def region_operation_codes(row: dict) -> str:
    raw = str(row.get("RegionOperation") or "").strip()
    codes: list[str] = []
    if raw:
        for m in re.finditer(r"\b\d{2}\b", raw):
            if m.group(0) in REGION_BY_CODE and m.group(0) not in codes:
                codes.append(m.group(0))
    inn_code, _name, _fd = region_from_inn(row.get("INN") or row.get("INN_dadata"))
    if inn_code and inn_code in REGION_BY_CODE and inn_code not in codes:
        codes.insert(0, inn_code)
    return ",".join(codes)
