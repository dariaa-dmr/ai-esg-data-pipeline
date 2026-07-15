"""Dadata enrichment for clean company CSV files.

Keeps all original columns and adds Dadata columns.
"""
from __future__ import annotations

import configparser
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests
from tqdm import tqdm

DADATA_COLUMNS = [
    "INN_dadata",
    "CompanyName_dadata",
    "Address_dadata",
    "lat_dadata",
    "lon_dadata",
    "status_dadata",
    "OKVED_dadata",
]


class DadataCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dadata_cache (
                inn TEXT PRIMARY KEY,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def get(self, inn: str) -> Optional[dict[str, Any]]:
        cur = self.conn.execute("SELECT response_json FROM dadata_cache WHERE inn = ?", (inn,))
        row = cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return None

    def set(self, inn: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            "REPLACE INTO dadata_cache (inn, response_json, created_at) VALUES (?, ?, ?)",
            (inn, json.dumps(payload, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


class DadataClient:
    def __init__(
        self,
        token: str,
        secret: str = "",
        retries: int = 3,
        retry_delay_sec: float = 2.0,
        request_delay_sec: float = 0.2,
        timeout_sec: float = 20.0,
    ):
        self.token = token
        self.secret = secret
        self.retries = retries
        self.retry_delay_sec = retry_delay_sec
        self.request_delay_sec = request_delay_sec
        self.timeout_sec = timeout_sec
        self.session = requests.Session()
        headers = {
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if secret:
            headers["X-Secret"] = secret
        self.session.headers.update(headers)

    def find_by_inn(self, inn: str) -> dict[str, Any]:
        url = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.post(url, json={"query": inn}, timeout=self.timeout_sec)
                if response.status_code == 429:
                    time.sleep(self.retry_delay_sec * attempt)
                    continue
                response.raise_for_status()
                time.sleep(self.request_delay_sec)
                return response.json()
            except Exception:
                time.sleep(self.retry_delay_sec * attempt)
        return {"suggestions": [], "_error": "max retries exceeded"}


def normalize_inn(value: object) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits if len(digits) in {10, 12} else ""


def parse_dadata_payload(payload: dict[str, Any]) -> dict[str, str]:
    suggestions = payload.get("suggestions") or []
    if not suggestions:
        return {col: "" for col in DADATA_COLUMNS}

    item = suggestions[0] or {}
    data = item.get("data") or {}
    name = data.get("name") or {}
    address = data.get("address") or {}
    state = data.get("state") or {}

    return {
        "INN_dadata": str(data.get("inn") or ""),
        "CompanyName_dadata": str(name.get("full_with_opf") or item.get("value") or ""),
        "Address_dadata": str(address.get("unrestricted_value") or address.get("value") or ""),
        "lat_dadata": str(address.get("geo_lat") or ""),
        "lon_dadata": str(address.get("geo_lon") or ""),
        "status_dadata": str(state.get("status") or ""),
        "OKVED_dadata": str(data.get("okved") or ""),
    }


def enrich_dadata_file(
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

    def read_secret_file(filename: str) -> str:
        secrets_dir = Path("secrets")
        if not secrets_dir.exists():
            return ""
        file_path = secrets_dir / filename
        if file_path.exists():
            return file_path.read_text(encoding="utf-8").strip()
        return ""

    token = (
        os.getenv("DADATA_TOKEN") or
        read_secret_file("dadata_token.txt") or
        cfg.get("api", "dadata_token", fallback="")
    ).strip()
    secret = (
        os.getenv("DADATA_SECRET") or
        read_secret_file("dadata_secret.txt") or
        cfg.get("api", "dadata_secret", fallback="")
    ).strip()
    chunksize = cfg.getint("pipeline", "chunksize", fallback=100)
    retries = cfg.getint("api", "retries", fallback=3)
    retry_delay = cfg.getfloat("api", "retry_delay_sec", fallback=2.0)
    request_delay = cfg.getfloat("api", "dadata_request_delay_sec", fallback=0.2)
    cache_path = cfg.get("paths", "cache_db", fallback="cache/api_cache.sqlite")

    # Читаем входной файл
    df = pd.read_csv(input_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    total_rows = len(df)
    log.info(f"Processing {total_rows} rows")

    if not token:
        log.warning("DADATA_TOKEN is empty. Copying %s with empty Dadata columns.", input_path.name)
        for col in DADATA_COLUMNS:
            df[col] = ""
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        return output_path

    client = DadataClient(token, secret, retries=retries, retry_delay_sec=retry_delay, request_delay_sec=request_delay)
    cache = DadataCache(cache_path)

    # Обрабатываем построчно
    rows = []
    for idx, row in tqdm(df.iterrows(), total=total_rows, desc=f"Dadata {input_path.name}"):
        inn = normalize_inn(row.get("INN", ""))
        if not inn:
            enriched = {col: "" for col in DADATA_COLUMNS}
        else:
            payload = cache.get(inn)
            if payload is None:
                payload = client.find_by_inn(inn)
                cache.set(inn, payload)
            enriched = parse_dadata_payload(payload)
        new_row = row.to_dict()
        new_row.update(enriched)
        rows.append(new_row)

    out_df = pd.DataFrame(rows)
    out_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    log.info(f"Dadata enrichment completed. Output: {output_path}")
    return output_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Enrich clean CSV through Dadata by INN.")
    parser.add_argument("input_csv")
    parser.add_argument("output_csv")
    parser.add_argument("--config", default="config.ini")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = configparser.ConfigParser()
    config.read(args.config, encoding="utf-8")
    enrich_dadata_file(args.input_csv, args.output_csv, config)