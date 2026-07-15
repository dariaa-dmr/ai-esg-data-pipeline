import pandas as pd
from pathlib import Path

active_dir = Path("final/active_by_source")
out_file = Path("final/all_sectors_final_active.csv")

dfs = []
for f in active_dir.glob("*_active.csv"):
    try:
        df = pd.read_csv(f, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        dfs.append(df)
    except Exception as e:
        print(f"Ошибка при чтении {f.name}: {e}")

if dfs:
    combined = pd.concat(dfs, ignore_index=True)
    combined.to_csv(out_file, index=False, encoding="utf-8-sig")
    print(f"Объединённый файл сохранён: {out_file}, строк: {len(combined)}")
else:
    print("Нет файлов для объединения")