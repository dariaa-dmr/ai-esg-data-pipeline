"""
Модуль проверки целостности данных и восстановления потерянных колонок.
Использует clean-файлы как эталон.
"""
import pandas as pd
from pathlib import Path
import logging

def restore_missing_columns_from_clean(target_file: Path, clean_file: Path, logger: logging.Logger = None) -> bool:
    """
    Восстанавливает недостающие колонки в target_file (например, geo или enriched)
    из clean_file по ИНН.
    Возвращает True, если было произведено восстановление (т.е. какие-то колонки были пусты и заполнены).
    """
    if not target_file.exists() or not clean_file.exists():
        return False

    # Колонки, которые должны быть перенесены из clean
    essential_cols = [
        "Sector", "Industry", "Subindustry", "CompanyName", "CompanyNameOfficial",
        "RegionRegistration", "RegionHeadOffice", "RegionOperation",
        "Description", "URL", "Source"
    ]

    try:
        target_df = pd.read_csv(target_file, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        clean_df = pd.read_csv(clean_file, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except Exception as e:
        if logger:
            logger.error(f"Не удалось прочитать файлы для восстановления: {e}")
        return False

    # Определяем, какие колонки из essential отсутствуют в target_df или полностью пустые
    missing_in_target = []
    for col in essential_cols:
        if col not in target_df.columns:
            missing_in_target.append(col)
        else:
            # Проверяем, все ли значения в этой колонке пустые (строка пустая или NaN)
            if target_df[col].astype(str).str.strip().eq('').all():
                missing_in_target.append(col)

    if not missing_in_target:
        return False  # Всё в порядке

    # Добавляем недостающие колонки в target_df (если их нет)
    for col in missing_in_target:
        if col not in target_df.columns:
            target_df[col] = ""

    # Объединяем по ИНН (если колонка INN есть в clean и target)
    if "INN" not in target_df.columns or "INN" not in clean_df.columns:
        if logger:
            logger.warning("Невозможно восстановить: отсутствует колонка INN в одном из файлов")
        return False

    # Выполняем left join: оставляем все строки target, дополняем из clean
    merged = target_df.merge(clean_df[["INN"] + missing_in_target], on="INN", how="left", suffixes=("", "_clean"))

    # Заполняем пустые значения в target из clean
    for col in missing_in_target:
        if f"{col}_clean" in merged.columns:
            merged[col] = merged[col].fillna(merged[f"{col}_clean"])
            merged.drop(columns=[f"{col}_clean"], inplace=True)

    # Убираем дубликаты колонок
    merged = merged.loc[:, ~merged.columns.duplicated()]

    # Сохраняем обратно
    merged.to_csv(target_file, index=False, encoding="utf-8-sig")
    if logger:
        logger.info(f"Восстановлены колонки {missing_in_target} в {target_file.name} из {clean_file.name}")
    return True


def check_and_restore(source_file: Path, stage: str, logger: logging.Logger = None) -> None:
    """
    Универсальная проверка для файлов enriched и geo.
    source_file - файл текущего этапа (enriched/*.csv или geo/*.csv)
    stage - "enriched" или "geo" (определяет, из какой папки брать clean)
    """
    if stage == "enriched":
        clean_file = Path("clean") / source_file.name.replace("_enriched.csv", "_clean.csv")
    elif stage == "geo":
        clean_file = Path("clean") / source_file.name.replace("_geo.csv", "_clean.csv")
    else:
        return

    if not clean_file.exists():
        if logger:
            logger.warning(f"Clean файл не найден для {source_file.name}, восстановление невозможно")
        return

    restored = restore_missing_columns_from_clean(source_file, clean_file, logger)
    if restored and logger:
        logger.info(f"✅ Восстановление данных для {source_file.name} выполнено")