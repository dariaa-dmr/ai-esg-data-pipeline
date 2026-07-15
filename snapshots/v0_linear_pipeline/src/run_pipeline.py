"""Universal CSV processing orchestrator.

Usage:
python run_pipeline.py --config config.ini
python run_pipeline.py --config config.ini --file incoming/ДФО_19.csv
"""
from __future__ import annotations

import argparse
import configparser
import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from csv_splitter import split_clean_dirty
from enrich_dadata import enrich_dadata_file
from geo_yandex import fill_geo_yandex_file
from normalizer import final_normalize_file
from integrity_check import check_and_restore  # fallback-механизм


def read_config(path: str | Path) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    read_files = cfg.read(path, encoding="utf-8")
    if not read_files:
        raise FileNotFoundError(f"Config not found: {path}")
    return cfg


def path_from_cfg(cfg: configparser.ConfigParser, section: str, option: str, default: str) -> Path:
    return Path(cfg.get(section, option, fallback=default)).expanduser().resolve()


def ensure_directories(cfg: configparser.ConfigParser) -> dict[str, Path]:
    paths = {
        "incoming": path_from_cfg(cfg, "paths", "incoming", "incoming"),
        "retry": path_from_cfg(cfg, "paths", "retry", "retry"),
        "clean": path_from_cfg(cfg, "paths", "clean", "clean"),
        "dirty": path_from_cfg(cfg, "paths", "dirty", "dirty"),
        "enriched": path_from_cfg(cfg, "paths", "enriched", "enriched"),
        "geo": path_from_cfg(cfg, "paths", "geo", "geo"),
        "final": path_from_cfg(cfg, "paths", "final", "final"),
        "archive": path_from_cfg(cfg, "paths", "archive", "archive"),
        "logs": path_from_cfg(cfg, "paths", "logs", "logs"),
        "cache": path_from_cfg(cfg, "paths", "cache", "cache"),
        "backup_source": path_from_cfg(cfg, "paths", "backup_source", "backup/source"),
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


def setup_logging(paths: dict[str, Path]) -> logging.Logger:
    log_path = paths["logs"] / "pipeline.log"
    logger = logging.getLogger("csv_pipeline")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


def safe_stem(path: Path) -> str:
    return path.stem.replace(" ", "_")


def backup_source_file(source: Path, backup_dir: Path, logger: logging.Logger) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{source.stem}_{timestamp}{source.suffix}"
    backup_path = backup_dir / backup_name
    shutil.copy2(source, backup_path)
    logger.info("backup source file=%s -> %s", source.name, backup_path)
    return backup_path


def archive_file(source: Path, archive_dir: Path, logger: logging.Logger) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = archive_dir / f"{source.stem}_{timestamp}{source.suffix}"
    counter = 1
    while target.exists():
        target = archive_dir / f"{source.stem}_{timestamp}_{counter}{source.suffix}"
        counter += 1
    shutil.move(str(source), str(target))
    logger.info("archived source=%s target=%s", source, target)
    return target


def run_external_script(script_path: str | Path, input_csv: Path, output_csv: Path, cfg_path: Path, logger: logging.Logger) -> bool:
    script = Path(script_path)
    if not script.exists():
        logger.warning("external_script_missing script=%s", script)
        return False
    cmd = [sys.executable, str(script), str(input_csv), str(output_csv)]
    logger.info("run_external_script cmd=%s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.stdout:
        logger.info("external_stdout script=%s output=%s", script.name, result.stdout[-3000:])
    if result.stderr:
        logger.warning("external_stderr script=%s output=%s", script.name, result.stderr[-3000:])
    if result.returncode != 0:
        logger.error("external_script_failed script=%s returncode=%s", script, result.returncode)
        return False
    return output_csv.exists()


def combine_split_outputs(paths: dict[str, Path], logger: logging.Logger, cfg: configparser.ConfigParser) -> None:
    split_by_status = cfg.getboolean("normalization", "split_by_status", fallback=False)
    if not split_by_status:
        logger.info("split_by_status is false, skipping combine_split_outputs")
        return

    active_dir = paths["final"] / "active_by_source"
    inactive_dir = paths["final"] / "inactive_by_source"
    combined_active = paths["final"] / "all_sectors_final_active.csv"
    combined_inactive = paths["final"] / "all_sectors_final_inactive.csv"

    if active_dir.exists():
        active_files = list(active_dir.glob("*_active.csv"))
        if active_files:
            all_active = []
            for f in active_files:
                try:
                    df = pd.read_csv(f, dtype=str, keep_default_na=False, encoding="utf-8-sig")
                    all_active.append(df)
                except Exception as e:
                    logger.warning("Не удалось прочитать %s: %s", f.name, e)
            if all_active:
                combined_df = pd.concat(all_active, ignore_index=True)
                combined_df.to_csv(combined_active, index=False, encoding="utf-8-sig")
                logger.info("Объединён активный файл: %s, строк: %s", combined_active, len(combined_df))
            else:
                logger.warning("Нет активных файлов для объединения")
        else:
            logger.info("Папка %s пуста, объединение не выполнено", active_dir)

    if inactive_dir.exists():
        inactive_files = list(inactive_dir.glob("*_inactive.csv"))
        if inactive_files:
            all_inactive = []
            for f in inactive_files:
                try:
                    df = pd.read_csv(f, dtype=str, keep_default_na=False, encoding="utf-8-sig")
                    all_inactive.append(df)
                except Exception as e:
                    logger.warning("Не удалось прочитать %s: %s", f.name, e)
            if all_inactive:
                combined_df = pd.concat(all_inactive, ignore_index=True)
                combined_df.to_csv(combined_inactive, index=False, encoding="utf-8-sig")
                logger.info("Объединён неактивный файл: %s, строк: %s", combined_inactive, len(combined_df))
            else:
                logger.warning("Нет неактивных файлов для объединения")
        else:
            logger.info("Папка %s пуста, объединение не выполнено", inactive_dir)


def process_one_file(input_file: Path, cfg: configparser.ConfigParser, paths: dict[str, Path], logger: logging.Logger, cfg_path: Path) -> None:
    stem = safe_stem(input_file)
    logger.info("start_file file=%s", input_file)

    # 1. Резервное копирование исходного файла
    backup_source_file(input_file, paths["backup_source"], logger)

    clean_path = paths["clean"] / f"{stem}_clean.csv"
    dirty_path = paths["dirty"] / f"dirty_{stem}.csv"
    enriched_path = paths["enriched"] / f"{stem}_enriched.csv"
    geo_path = paths["geo"] / f"{stem}_geo.csv"
    final_path = paths["final"] / f"{stem}_final.csv"

    # 2. Разделение
    split_result = split_clean_dirty(input_file, clean_path, dirty_path, logger=logger)
    if split_result.clean_rows == 0:
        logger.warning("no_clean_rows file=%s dirty=%s", input_file.name, split_result.dirty_rows)
        archive_file(input_file, paths["archive"], logger)
        return

    # 3. Обогащение через Dadata
    use_external = cfg.getboolean("scripts", "use_existing_scripts", fallback=False)
    if use_external:
        dadata_script = cfg.get("scripts", "dadata_script", fallback="validate_one_file_safe.py")
        if not run_external_script(dadata_script, clean_path, enriched_path, cfg_path, logger):
            logger.warning("fallback_to_internal_dadata file=%s", clean_path.name)
            enrich_dadata_file(clean_path, enriched_path, cfg, logger)
    else:
        enrich_dadata_file(clean_path, enriched_path, cfg, logger)

    # Fallback: восстанавливаем потерянные колонки в enriched из clean
    check_and_restore(enriched_path, "enriched", logger)

    # 4. Геокодирование через Яндекс
    if use_external:
        yandex_script = cfg.get("scripts", "yandex_script", fallback="fill_geo_yandex.py")
        if not run_external_script(yandex_script, enriched_path, geo_path, cfg_path, logger):
            logger.warning("fallback_to_internal_yandex file=%s", enriched_path.name)
            fill_geo_yandex_file(enriched_path, geo_path, cfg, logger)
    else:
        fill_geo_yandex_file(enriched_path, geo_path, cfg, logger)

    # Fallback: восстанавливаем потерянные колонки в geo из clean
    check_and_restore(geo_path, "geo", logger)

    # 5. Финальная нормализация
    final_normalize_file(geo_path, final_path, cfg, logger)

    # 6. Перемещаем исходный файл в архив
    archive_file(input_file, paths["archive"], logger)
    logger.info("complete_file file=%s", input_file.name)


def collect_input_files(paths: dict[str, Path], explicit_file: Optional[str]) -> list[Path]:
    if explicit_file:
        return [Path(explicit_file).expanduser().resolve()]
    files = sorted(paths["incoming"].glob("*.csv")) + sorted(paths["retry"].glob("*.csv"))
    return [p for p in files if p.is_file()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CSV clean/dirty/enrich/geocode/final pipeline.")
    parser.add_argument("--config", default="config.ini", help="Path to config.ini")
    parser.add_argument("--file", default=None, help="Process one CSV file instead of scanning incoming/retry")
    args = parser.parse_args()

    cfg_path = Path(args.config).expanduser().resolve()
    cfg = read_config(cfg_path)
    paths = ensure_directories(cfg)
    logger = setup_logging(paths)

    input_files = collect_input_files(paths, args.file)
    if not input_files:
        logger.info("no_input_files incoming=%s retry=%s", paths["incoming"], paths["retry"])
        return 0

    for input_file in input_files:
        try:
            process_one_file(input_file, cfg, paths, logger, cfg_path)
        except Exception as exc:
            logger.exception("file_failed file=%s error=%r", input_file, exc)
            error_dir = paths["dirty"] / "file_errors"
            error_dir.mkdir(parents=True, exist_ok=True)
            target = error_dir / input_file.name
            if input_file.exists():
                shutil.copy2(input_file, target)
            continue

    combine_split_outputs(paths, logger, cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())