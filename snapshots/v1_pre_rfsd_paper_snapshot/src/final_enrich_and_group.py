"""
Финальное обогащение чистых данных данными из enriched/geo и группировка по округам.
"""
import pandas as pd
from pathlib import Path

# 1. Загружаем справочник регионов
region_map_path = Path("00_регионы_по_федеральным_округам.csv")
if not region_map_path.exists():
    raise FileNotFoundError(f"Не найден справочник: {region_map_path}")

region_df = pd.read_csv(region_map_path, sep=';', dtype=str, keep_default_na=False, encoding='utf-8-sig')
region_to_district = dict(zip(region_df['Region'], region_df['FederalDistrictName']))

# 2. Собираем все clean-файлы (основа)
clean_dir = Path("clean")
all_clean = []
for f in clean_dir.glob("*_clean.csv"):
    df = pd.read_csv(f, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    all_clean.append(df)
if not all_clean:
    print("Нет clean-файлов")
    exit()

clean_df = pd.concat(all_clean, ignore_index=True)
print(f"Загружено clean-строк: {len(clean_df)}")

# 3. Собираем все enriched-файлы (обогащение Dadata)
enriched_dir = Path("enriched")
all_enriched = []
for f in enriched_dir.glob("*_enriched.csv"):
    df = pd.read_csv(f, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    all_enriched.append(df)
if all_enriched:
    enriched_df = pd.concat(all_enriched, ignore_index=True)
    # Оставляем только нужные колонки из enriched
    enriched_cols = ["INN", "INN_dadata", "CompanyName_dadata", "Address_dadata", "status_dadata", "OKVED_dadata"]
    enriched_df = enriched_df[[c for c in enriched_cols if c in enriched_df.columns]]
    print(f"Загружено enriched-строк: {len(enriched_df)}")
else:
    enriched_df = pd.DataFrame()
    print("Нет enriched-файлов")

# 4. Собираем все geo-файлы (координаты)
geo_dir = Path("geo")
all_geo = []
for f in geo_dir.glob("*_geo.csv"):
    df = pd.read_csv(f, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    all_geo.append(df)
if all_geo:
    geo_df = pd.concat(all_geo, ignore_index=True)
    geo_cols = ["INN", "lat_dadata", "lon_dadata"]
    geo_df = geo_df[[c for c in geo_cols if c in geo_df.columns]]
    print(f"Загружено geo-строк: {len(geo_df)}")
else:
    geo_df = pd.DataFrame()
    print("Нет geo-файлов")

# 5. Объединяем всё по INN из clean (левое соединение)
final_df = clean_df.copy()

if not enriched_df.empty:
    final_df = final_df.merge(enriched_df, on="INN", how="left", suffixes=("", "_enr"))
    # Убираем дубликаты колонок
    final_df = final_df.loc[:, ~final_df.columns.str.endswith('_enr')]
if not geo_df.empty:
    final_df = final_df.merge(geo_df, on="INN", how="left", suffixes=("", "_geo"))
    final_df = final_df.loc[:, ~final_df.columns.str.endswith('_geo')]

# 6. Оставляем только активные компании (если есть статус)
if "status_dadata" in final_df.columns:
    final_df = final_df[final_df["status_dadata"].str.upper() == "ACTIVE"]
    print(f"После фильтрации активных: {len(final_df)}")
else:
    print("Нет статуса – оставляем все компании")

# 7. Определяем федеральный округ по RegionRegistration
final_df['FederalDistrict'] = final_df['RegionRegistration'].map(region_to_district)
missing = final_df['FederalDistrict'].isna().sum()
if missing:
    print(f"Предупреждение: для {missing} записей не определён округ (будут исключены из группировки)")
    final_df = final_df.dropna(subset=['FederalDistrict'])

if final_df.empty:
    print("Нет данных для группировки")
    exit()

# 8. Группируем по округам, секторам, отраслям, подотраслям
out_dir = Path("final_enriched_grouped")
out_dir.mkdir(exist_ok=True)

for district, group_district in final_df.groupby('FederalDistrict'):
    district_dir = out_dir / district
    district_dir.mkdir(exist_ok=True)
    for sector, group_sector in group_district.groupby('Sector'):
        sector_dir = district_dir / sector
        sector_dir.mkdir(exist_ok=True)
        for industry, group_industry in group_sector.groupby('Industry'):
            industry_dir = sector_dir / industry
            industry_dir.mkdir(exist_ok=True)
            for subindustry, group_sub in group_industry.groupby('Subindustry'):
                safe_name = subindustry.replace('/', '_').replace('\\', '_')
                out_path = industry_dir / f"{safe_name}.csv"
                group_sub.to_csv(out_path, index=False, encoding='utf-8-sig')
                print(f"Сохранено: {out_path} ({len(group_sub)} записей)")

# 9. Сводная таблица
summary = final_df.groupby(['FederalDistrict', 'Sector', 'Industry', 'Subindustry']).size().reset_index(name='count')
summary.to_csv(out_dir / "summary.csv", index=False, encoding='utf-8-sig')
print(f"\nСводная таблица: {out_dir / 'summary.csv'}")
print(f"Всего записей в группировке: {len(final_df)}")