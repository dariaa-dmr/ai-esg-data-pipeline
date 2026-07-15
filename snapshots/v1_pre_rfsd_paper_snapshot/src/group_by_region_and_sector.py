#!/usr/bin/env python3
"""
Группировка компаний по федеральным округам, отраслям и подотраслям.

Использование:
    python group_by_region_and_sector.py --input final/all_sectors_final_active.csv --region-map 00_регионы_по_федеральным_округам.csv

Параметры:
    --input         Путь к финальному CSV (обязательный)
    --region-map    Путь к CSV с соответствием регион -> федеральный округ (обязательный)
    --region-col    Название колонки с регионом (по умолчанию: RegionFromAddress)
    --out-dir       Папка для результатов (по умолчанию: grouped)
    --subind-list   Файл со списком подотраслей (по одной строке) для задания порядка (опционально)
    --merge-district Создавать общий CSV по каждому федеральному округу (по умолчанию нет)
"""
import argparse
import csv
import sys
from pathlib import Path

import pandas as pd


def load_region_district_map(csv_path: Path) -> tuple[dict, dict]:
    """Загружает файл с соответствием регион -> федеральный округ.
       Ожидается формат: FederalDistrict;FederalDistrictName;Region
       Возвращает: dict[region_name, district_code] и dict[district_code, district_full_name].
    """
    df = pd.read_csv(csv_path, sep=';', dtype=str, keep_default_na=False, encoding='utf-8-sig')
    region_to_district = {}
    district_full = {}
    for _, row in df.iterrows():
        district_code = row['FederalDistrict'].strip()
        district_name = row['FederalDistrictName'].strip()
        region = row['Region'].strip()
        region_to_district[region] = district_code
        district_full[district_code] = district_name
    return region_to_district, district_full


def load_subindustry_order(file_path: Path = None) -> dict:
    """Загружает список подотраслей для задания порядка при создании папок.
       Если файл не указан, возвращает пустой словарь (порядок не задаётся).
    """
    if file_path is None or not file_path.exists():
        return {}
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        lines = [line.strip() for line in f if line.strip()]
    return {sub: i for i, sub in enumerate(lines)}


def safe_filename(text: str) -> str:
    """Заменяет символы, недопустимые в имени файла/папки."""
    # Заменяем слэши, двоеточия, звёздочки и т.д.
    for ch in r'\/:*?"<>|':
        text = text.replace(ch, '_')
    # Убираем точку в конце
    if text.endswith('.'):
        text = text[:-1]
    return text


def main():
    parser = argparse.ArgumentParser(description="Группировка компаний по федеральным округам и отраслям")
    parser.add_argument("--input", required=True, help="Путь к финальному CSV (например, final/all_sectors_final_active.csv)")
    parser.add_argument("--region-map", required=True, help="Путь к CSV с соответствием регион -> федеральный округ")
    parser.add_argument("--region-col", default="RegionFromAddress", help="Название колонки с регионом (по умолчанию: RegionFromAddress)")
    parser.add_argument("--out-dir", default="grouped", help="Папка для сохранения результатов (по умолчанию: grouped)")
    parser.add_argument("--subind-list", help="Файл со списком подотраслей для задания порядка (опционально)")
    parser.add_argument("--merge-district", action="store_true", help="Создавать общий CSV по каждому федеральному округу")
    args = parser.parse_args()

    input_path = Path(args.input)
    region_map_path = Path(args.region_map)
    out_dir = Path(args.out_dir)

    if not input_path.exists():
        print(f"Ошибка: входной файл не найден: {input_path}")
        sys.exit(1)
    if not region_map_path.exists():
        print(f"Ошибка: файл с регионами не найден: {region_map_path}")
        sys.exit(1)

    # Загружаем данные
    print("Загрузка основного файла...")
    df = pd.read_csv(input_path, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    print(f"Всего записей: {len(df)}")

    # Загружаем соответствие регион -> округ
    region_to_district, district_full = load_region_district_map(region_map_path)

    # Определяем федеральный округ для каждой записи
    region_col = args.region_col
    if region_col not in df.columns:
        print(f"Ошибка: колонка '{region_col}' не найдена. Доступные колонки: {list(df.columns)}")
        sys.exit(1)

    df['FederalDistrict'] = df[region_col].map(region_to_district)
    df['FederalDistrictName'] = df['FederalDistrict'].map(district_full)

    # Отбрасываем записи, для которых не найден округ
    missing = df['FederalDistrict'].isna().sum()
    if missing:
        print(f"Предупреждение: для {missing} записей не удалось определить федеральный округ. Они будут исключены.")
        df = df.dropna(subset=['FederalDistrict'])

    if df.empty:
        print("Нет данных для группировки.")
        return

    # Загружаем порядок подотраслей (если указан)
    subind_order = load_subindustry_order(Path(args.subind_list) if args.subind_list else None)

    # Создаём папку для результатов
    out_dir.mkdir(parents=True, exist_ok=True)

    # Статистика для сводной таблицы
    summary_rows = []

    # Группируем по федеральному округу
    for district_code, group_district in df.groupby('FederalDistrict'):
        district_name = district_full.get(district_code, district_code)
        district_dir = out_dir / safe_filename(district_name)
        district_dir.mkdir(parents=True, exist_ok=True)

        # Группируем по сектору (Sector)
        for sector, group_sector in group_district.groupby('Sector'):
            if pd.isna(sector):
                sector = "Не указано"
            sector_dir = district_dir / safe_filename(sector)
            sector_dir.mkdir(parents=True, exist_ok=True)

            # Группируем по отрасли (Industry)
            for industry, group_industry in group_sector.groupby('Industry'):
                if pd.isna(industry):
                    industry = "Не указано"
                industry_dir = sector_dir / safe_filename(industry)
                industry_dir.mkdir(parents=True, exist_ok=True)

                # Группируем по подотрасли (Subindustry)
                # Сначала определяем порядок для сортировки
                subindustries = group_industry['Subindustry'].unique()
                # Сортируем по порядку из файла, если он задан, иначе по алфавиту
                if subind_order:
                    subindustries = sorted(subindustries, key=lambda x: subind_order.get(x, 9999))
                else:
                    subindustries = sorted(subindustries)

                for subindustry in subindustries:
                    if pd.isna(subindustry):
                        subindustry = "Не указано"
                    group_sub = group_industry[group_industry['Subindustry'] == subindustry]
                    # Имя файла
                    filename = safe_filename(subindustry) + ".csv"
                    out_path = industry_dir / filename
                    group_sub.to_csv(out_path, index=False, encoding='utf-8-sig')
                    print(f"Сохранено: {out_path} ({len(group_sub)} записей)")

                    # Добавляем строку в сводную таблицу
                    summary_rows.append({
                        'FederalDistrictCode': district_code,
                        'FederalDistrictName': district_name,
                        'Sector': sector,
                        'Industry': industry,
                        'Subindustry': subindustry,
                        'CompaniesCount': len(group_sub)
                    })

        # Если запрошено объединение всех компаний федерального округа в один CSV
        if args.merge_district:
            district_all_path = district_dir / f"{safe_filename(district_name)}_all.csv"
            group_district.to_csv(district_all_path, index=False, encoding='utf-8-sig')
            print(f"Создан общий файл округа: {district_all_path} ({len(group_district)} записей)")

    # Сохраняем сводную таблицу
    summary_df = pd.DataFrame(summary_rows)
    summary_path = out_dir / "summary_by_region_and_sector.csv"
    summary_df.to_csv(summary_path, index=False, encoding='utf-8-sig')
    print(f"\nСводная таблица сохранена: {summary_path}")
    print(f"Всего групп: {len(summary_df)}")


if __name__ == "__main__":
    main()