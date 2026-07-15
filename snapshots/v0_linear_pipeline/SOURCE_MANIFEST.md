# v0 source manifest

This folder contains the cleaned source-code selection for the historical linear pipeline snapshot.

- Source archive: `csv_pipeline_без_ключей.zip`
- Snapshot role: improved linear prototype used as the starting point in the architecture-evolution narrative.
- Extraction rule: explicit whitelist; no recursive copy of the working project.
- Source code was copied without executing it.

## Included source files

- `run_pipeline.py`
- `csv_splitter.py`
- `enrich_dadata.py`
- `geo_yandex.py`
- `normalizer.py`
- `integrity_check.py`
- `recover_lost_by_inn.py`
- `final_enrich_and_group.py`
- `group_by_region_and_sector.py`
- `group_from_clean.py`
- `merge_active.py`
- `description_generator.py`

## Intentionally excluded

- virtual environments and compiled files;
- working CSV data and backup/archive directories;
- cache databases and logs;
- the ambiguous file `Python File.py`;
- the original working `config.ini`;
- historical working README and local helper files.

## SHA-256 of included Python files

| File | SHA-256 |
|---|---|
| `csv_splitter.py` | `8da00c19619a1419e9931b26ad82f6946311df4e4d9f8e6adf0e835931ef1d4a` |
| `description_generator.py` | `843e47c834103d826558af1e0837739f25b500fec2df7687e299175f1a0754f8` |
| `enrich_dadata.py` | `dff5c966289a7e2934aaa834617b5f1f7ad7589c5caf3290e148f68bcb5dfe2d` |
| `final_enrich_and_group.py` | `9af44c23eda659051cbee399068ca02f4db930d35f7b3354d64519891f0bd569` |
| `geo_yandex.py` | `761b643d5c31db8c6df1ad12d3d4def71fe36b6aeb8a2f2a0340b3fbacf61938` |
| `group_by_region_and_sector.py` | `0da4d4284e3e536b74b02c471cd27a03f67f1339863f624b2cf3de0631f4f5e4` |
| `group_from_clean.py` | `4603c78b7f176e949cf1df5e84906acb841bc343838a0369bb5ab00aff947aa4` |
| `integrity_check.py` | `ae51240c52b4611ad17f7b17577dbbe8baae92aa73d3e5997be9982a491b76ef` |
| `merge_active.py` | `0cd6030ef4f4e1b461aa166339a771f20f8437f5aad79317fefe67c24944c0c2` |
| `normalizer.py` | `2c0b837d9dce9e82d99868373714627d7c36c985660c58f1bb792af7c65010a2` |
| `recover_lost_by_inn.py` | `79615d9c36592e1efcd5561300b0e3be9557875b8c40fea9047edd2d0b7732da` |
| `run_pipeline.py` | `8ef871718a6d684d5541e4035a742d1032d5600d44af754fb388470a4cb40bfe` |
