"""Fill missing coordinates via Yandex Geocoder.

Supports resuming after interruption using temporary files and progress tracking.
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

from paths import get_secret, resolve_path


class GeocodeCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS yandex_geo_cache (
                address TEXT PRIMARY KEY,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def get(self, address: str) -> Optional[dict[str, Any]]:
        cur = self.conn.execute("SELECT response_json FROM yandex_geo_cache WHERE address = ?", (address,))
        row = cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return None

    def set(self, address: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            "REPLACE INTO yandex_geo_cache (address, response_json, created_at) VALUES (?, ?, ?)",
            (address, json.dumps(payload, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


class YandexGeocoderClient:
    def __init__(
        self,
        api_key: str,
        retries: int = 3,
        retry_delay_sec: float = 2.0,
        request_delay_sec: float = 0.2,
        timeout_sec: float = 20.0,
    ):
        self.api_key = api_key
        self.retries = retries
        self.retry_delay_sec = retry_delay_sec
        self.request_delay_sec = request_delay_sec
        self.timeout_sec = timeout_sec
        self.session = requests.Session()

    def geocode(self, address: str) -> dict[str, Any]:
        url = "https://geocode-maps.yandex.ru/1.x/"
        params = {
            "apikey": self.api_key,
            "geocode": address,
            "format": "json",
            "results": 1,
            "lang": "ru_RU",
        }
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout_sec)
                if response.status_code == 429:
                    time.sleep(self.retry_delay_sec * attempt)
                    continue
                response.raise_for_status()
                time.sleep(self.request_delay_sec)
                return response.json()
            except Exception:
                time.sleep(self.retry_delay_sec * attempt)
        return {"_error": "max retries exceeded"}


def is_missing(value: object) -> bool:
    text = str(value or "").strip().lower()
    return text in {"", "nan", "none", "null"}


def parse_yandex_payload(payload: dict[str, Any]) -> tuple[str, str, str]:
    try:
        members = payload["response"]["GeoObjectCollection"]["featureMember"]
        if not members:
            return "", "", "not_found"
        pos = members[0]["GeoObject"]["Point"]["pos"]
        lon, lat = pos.split()
        return lat, lon, "ok"
    except Exception as exc:
        return "", "", f"parse_error:{exc!r}"


def _get_progress(progress_path: Path, input_lines: int) -> int:
    if progress_path.exists():
        try:
            with open(progress_path, "r") as f:
                data = json.load(f)
            processed = data.get("processed", 0)
            if processed <= input_lines:
                return processed
        except:
            pass
    return 0


def _save_progress(progress_path: Path, processed: int) -> None:
    with open(progress_path, "w") as f:
        json.dump({"processed": processed, "updated": datetime.now().isoformat()}, f)


def fill_geo_yandex_file(
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

    api_key = get_secret(cfg, "YANDEX_GEOCODER_KEY", "yandex_key.txt", section="api", option="yandex_geocoder_key")
    chunksize = cfg.getint("pipeline", "chunksize", fallback=100)
    save_every = cfg.getint("pipeline", "save_every", fallback=10)
    retries = cfg.getint("api", "retries", fallback=3)
    retry_delay = cfg.getfloat("api", "retry_delay_sec", fallback=2.0)
    request_delay = cfg.getfloat("api", "yandex_request_delay_sec", fallback=0.2)
    cache_path = resolve_path(cfg, "paths", "cache_db", "cache/api_cache.sqlite")
    missing_geo_path = resolve_path(cfg, "paths", "missing_geo", "logs/missing_geo.csv")
    missing_geo_path.parent.mkdir(parents=True, exist_ok=True)

    if not api_key:
        log.warning("YANDEX_GEOCODER_KEY is empty. Copying %s without geocoding.", input_path.name)
        df = pd.read_csv(input_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        if "lat_dadata" not in df.columns:
            df["lat_dadata"] = ""
        if "lon_dadata" not in df.columns:
            df["lon_dadata"] = ""
        if "geo_source" not in df.columns:
            df["geo_source"] = df.apply(
                lambda r: "dadata" if not is_missing(r.get("lat_dadata")) and not is_missing(r.get("lon_dadata")) else "",
                axis=1,
            )
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        return output_path

    client = YandexGeocoderClient(api_key, retries=retries, retry_delay_sec=retry_delay, request_delay_sec=request_delay)
    cache = GeocodeCache(cache_path)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    progress_path = output_path.with_suffix(output_path.suffix + ".progress")

    # Читаем входной файл
    input_df = pd.read_csv(input_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    total_input = len(input_df)
    processed = _get_progress(progress_path, total_input)

    if processed > 0 and tmp_path.exists():
        log.info("Resuming from previous run: %s of %s rows already processed.", processed, total_input)
        existing_df = pd.read_csv(tmp_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        if len(existing_df) != processed:
            log.warning("Mismatch between progress and tmp file. Starting from scratch.")
            processed = 0
            tmp_path.unlink(missing_ok=True)
            progress_path.unlink(missing_ok=True)
    else:
        processed = 0
        if tmp_path.exists():
            tmp_path.unlink()
        if progress_path.exists():
            progress_path.unlink()

    df_remaining = input_df.iloc[processed:]
    total_remaining = len(df_remaining)
    if total_remaining == 0:
        log.info("All rows already processed. Copying tmp to output.")
        if tmp_path.exists():
            tmp_path.replace(output_path)
        return output_path

    log.info("Processing %s rows (already done: %s)", total_remaining, processed)

    missing_rows: list[dict[str, str]] = []
    # Будем обрабатывать построчно и периодически сохранять
    processed_in_session = 0
    all_rows = []   # накопление всех строк (уже обработанных + новых)
    if processed > 0:
        # загрузим уже обработанные
        all_rows = pd.read_csv(tmp_path, dtype=str, keep_default_na=False, encoding="utf-8-sig").to_dict('records')

    with tqdm(total=total_remaining, desc=f"Yandex geo {input_path.name}") as pbar:
        for idx, (_, row) in enumerate(df_remaining.iterrows()):
            has_coords = not is_missing(row.get("lat_dadata")) and not is_missing(row.get("lon_dadata"))
            if has_coords:
                if is_missing(row.get("geo_source")):
                    row["geo_source"] = "dadata"
                all_rows.append(row.to_dict())
            else:
                address = str(row.get("Address_dadata") or "").strip()
                if not address:
                    missing_rows.append({
                        "source_file": input_path.name,
                        "INN": str(row.get("INN") or ""),
                        "Address_dadata": "",
                        "reason": "no_address_for_geocoding",
                    })
                    row["lat_dadata"] = ""
                    row["lon_dadata"] = ""
                    row["geo_source"] = ""
                else:
                    payload = cache.get(address)
                    if payload is None:
                        payload = client.geocode(address)
                        cache.set(address, payload)
                    lat, lon, status = parse_yandex_payload(payload)
                    if lat and lon:
                        row["lat_dadata"] = lat
                        row["lon_dadata"] = lon
                        row["geo_source"] = "yandex"
                    else:
                        missing_rows.append({
                            "source_file": input_path.name,
                            "INN": str(row.get("INN") or ""),
                            "Address_dadata": address,
                            "reason": status,
                        })
                        row["lat_dadata"] = ""
                        row["lon_dadata"] = ""
                        row["geo_source"] = ""
                all_rows.append(row.to_dict())

            processed_in_session += 1
            if processed_in_session % save_every == 0 or processed_in_session == total_remaining:
                # Сохраняем промежуточный результат
                temp_df = pd.DataFrame(all_rows)
                temp_df.to_csv(tmp_path, index=False, encoding="utf-8-sig")
                _save_progress(progress_path, processed + processed_in_session)
                log.debug("Saved progress: %s rows", processed + processed_in_session)
            pbar.update(1)

    # Запись финального результата
    final_df = pd.DataFrame(all_rows)
    final_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    # Сохраняем пропущенные геокодирования
    if missing_rows:
        pd.DataFrame(missing_rows).to_csv(
            missing_geo_path,
            mode="a",
            header=not missing_geo_path.exists(),
            index=False,
            encoding="utf-8-sig",
        )
    # Удаляем временные файлы
    tmp_path.unlink(missing_ok=True)
    progress_path.unlink(missing_ok=True)
    log.info("Yandex geocoding completed. Output: %s", output_path)
    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fill missing coordinates using Yandex Geocoder.")
    parser.add_argument("input_csv")
    parser.add_argument("output_csv")
    parser.add_argument("--config", default="config.ini")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = configparser.ConfigParser()
    config.read(args.config, encoding="utf-8")
    fill_geo_yandex_file(args.input_csv, args.output_csv, config)