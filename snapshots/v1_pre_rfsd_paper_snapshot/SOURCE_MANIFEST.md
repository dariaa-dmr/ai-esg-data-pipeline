# v1 source manifest

This package contains a curated code-only snapshot extracted from the mature pre-RFSD pipeline archive.

## Included source files

- `src/run_pipeline.py` — SHA-256 `b7958151c0b4c5dc1df52c3317f66e0d56b361613d15e637a66ab9491bbc86ab`
- `src/csv_splitter.py` — SHA-256 `b7e856aaa28ab274f8bb3954c4d6941bedad250753c5d08122bda93a0f222d57`
- `src/enrich_dadata.py` — SHA-256 `ae996a6a2bb48ca8f99579ba304f4ae020bf55437951f600c23ca3b1ce149a4b`
- `src/geo_yandex.py` — SHA-256 `2e3636b77c929b4dd4ab7d46a069dbada2c9a35d14549f291e8b1cd710c47fe2`
- `src/normalizer.py` — SHA-256 `9a177b063c467c12c39465ac1d2078e31a3a797f17f3e049cd8f3516ca7502bb`
- `src/integrity_check.py` — SHA-256 `33bec34996635e58365f8ca27d190c49169b61adb9b646bbbf0b9fa9078d4226`
- `src/paths.py` — SHA-256 `8234da20834ec4cfd4f5d57036f08b9db1f8859ef5452dce0ab177dd8dc2f86f`
- `src/safe_filename.py` — SHA-256 `2ea84acf6a9e080ee80517987000532e632d749b4e178aff97b5daefe926fab2`
- `src/row_identity.py` — SHA-256 `4467373d1e04e5ab7f9e132b01f9d0b0a0ed6df61ba9035b8c1b69e776a2dfb4`
- `src/regions_reference.py` — SHA-256 `2f07e7f8f49835efab7f0d9d65fd0645215154330f376e5aea5cb5a6c96fccf6`
- `src/spark_request_export.py` — SHA-256 `eb125c16dca1baefd63c14f57643af3c3a0fd784103bc054e9e94ae4f9cf3f8b`
- `src/spark_pipeline.py` — SHA-256 `c6b75ed0df16fb34bada443dc0a87fd72cf77da58dd11b17d367abb90b6fcb3c`
- `src/spark_structured_parser.py` — SHA-256 `38fe6875efcb88ac3f1a3122b6509253e2b1af39c5dc3590c58240843dcb2ea4`
- `src/spark_size_filter.py` — SHA-256 `a8c79190d770b8a76b5204cd9377ea6ee107d4ce13ede18ee3173dc636c1b1e0`
- `src/description_builder.py` — SHA-256 `75c2a7930c64e7d42401550094cd23c962508ddcba52d8c4ed66e9a684cb7a4c`
- `src/yandexgpt_client.py` — SHA-256 `46c229b4f6bb593ed0d020871296e602c5fe78419835923d54d4ae6ccc91628a`
- `src/export_by_category.py` — SHA-256 `f316e10f23b8800431871601cd0c18b02192f62011b7328d0534cdfbee2607d2`
- `src/public_exports.py` — SHA-256 `ff0ba60a4f856b14c174cb193e4a9a91a92200237980e738f6af7cb0a3509e3b`
- `src/quality_gate.py` — SHA-256 `15082fd2caf683fff7198cd4f89f699e3235a8035c668e3c86c0d75eac56dfe9`
- `src/manual_overrides.py` — SHA-256 `27354f3c207b5d995fa7763e050b69d83b51322c2c4c922b5af228085c2da652`
- `src/pipeline_control.py` — SHA-256 `d35a4a30b04340674a78ae81b3bd4de6a3497b6320ad9ad31f146b94f72a1946`
- `src/recover_lost_by_inn.py` — SHA-256 `79615d9c36592e1efcd5561300b0e3be9557875b8c40fea9047edd2d0b7732da`
- `src/final_enrich_and_group.py` — SHA-256 `9af44c23eda659051cbee399068ca02f4db930d35f7b3354d64519891f0bd569`
- `src/group_by_region_and_sector.py` — SHA-256 `0da4d4284e3e536b74b02c471cd27a03f67f1339863f624b2cf3de0631f4f5e4`
- `src/group_from_clean.py` — SHA-256 `4603c78b7f176e949cf1df5e84906acb841bc343838a0369bb5ab00aff947aa4`
- `src/merge_active.py` — SHA-256 `0cd6030ef4f4e1b461aa166339a771f20f8437f5aad79317fefe67c24944c0c2`
- `src/description_generator.py` — SHA-256 `843e47c834103d826558af1e0837739f25b500fec2df7687e299175f1a0754f8`

## Included configuration files

- `config.example.ini` — public template with empty credential fields.
- `.env.example` — optional empty environment-variable template.
- `requirements.txt` — Python dependencies from the source snapshot.

## Excluded from this package

- working `config.ini` copies and any credential-bearing files;
- `.venv`, `__pycache__`, caches, SQLite databases and logs;
- raw SPARK ZIP/XML/HTML/Excel exports and `spark/incoming` / `spark/unpacked`;
- full working CSV datasets from processing and export directories;
- backup and archive directories;
- historical, patched and duplicate script variants;
- RFSD/RBBO modules or data (not present in the source snapshot).

No code was executed while creating this package.
