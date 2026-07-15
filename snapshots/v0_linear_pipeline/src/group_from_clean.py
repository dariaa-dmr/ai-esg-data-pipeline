"""
Группировка компаний по федеральным округам, отраслям и подотраслям
НАПРЯМУЮ ИЗ CLEAN-ФАЙЛОВ (без использования RegionFromAddress).
"""
import pandas as pd
from pathlib import Path

# Загружаем справочник регион -> федеральный округ
region_map_path = Path("00_регионы_по_федеральным_округам.csv")
if not region_map_path.exists():
    raise FileNotFoundError(f"Не найден справочник: {region_map_path}")

region_df = pd.read_csv(region_map_path, sep=';', dtype=str, keep_default_na=False, encoding='utf-8-sig')
region_to_district = dict(zip(region_df['Region'], region_df['FederalDistrictName']))

# Читаем все clean-файлы
clean_dir = Path("clean")
all_dfs = []
for clean_file in clean_dir.glob("*_clean.csv"):
    df = pd.read_csv(clean_file, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    all_dfs.append(df)

if not all_dfs:
    print("Нет clean-файлов")
    exit()

full_df = pd.concat(all_dfs, ignore_index=True)

# Определяем федеральный округ по RegionRegistration
full_df['FederalDistrict'] = full_df['RegionRegistration'].map(region_to_district)

# Отбрасываем записи без округа (если есть)
missing = full_df['FederalDistrict'].isna().sum()
if missing:
    print(f"Предупреждение: для {missing} записей не найден округ. Они будут исключены.")
    full_df = full_df.dropna(subset=['FederalDistrict'])

if full_df.empty:
    print("Нет данных для группировки")
    exit()

# Группируем
out_dir = Path("grouped_from_clean")
out_dir.mkdir(exist_ok=True)

for district, group_district in full_df.groupby('FederalDistrict'):
    district_dir = out_dir / district
    district_dir.mkdir(exist_ok=True)
    for sector, group_sector in group_district.groupby('Sector'):
        sector_dir = district_dir / sector
        sector_dir.mkdir(exist_ok=True)
        for industry, group_industry in group_sector.groupby('Industry'):
            industry_dir = sector_dir / industry
            industry_dir.mkdir(exist_ok=True)
            for subindustry, group_sub in group_industry.groupby('Subindustry'):
                # Имя файла – подотрасль (заменяем недопустимые символы)
                safe_name = subindustry.replace('/', '_').replace('\\', '_')
                out_path = industry_dir / f"{safe_name}.csv"
                group_sub.to_csv(out_path, index=False, encoding='utf-8-sig')
                print(f"Сохранено: {out_path} ({len(group_sub)} записей)")

# Сводная таблица
summary = full_df.groupby(['FederalDistrict', 'Sector', 'Industry', 'Subindustry']).size().reset_index(name='count')
summary.to_csv(out_dir / "summary.csv", index=False, encoding='utf-8-sig')
print(f"\nСводная таблица: {out_dir / 'summary.csv'}")
print(f"Всего записей в группировке: {len(full_df)}")