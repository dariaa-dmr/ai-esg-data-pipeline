# Synthetic sample data

All records in this folder are fictional and must not be interpreted as real companies or real SPARK exports. Domains use the reserved `.example` namespace. INNs use deliberately non-production test patterns.

The five source rows demonstrate:

1. inclusion by employee count;
2. inclusion by revenue;
3. exclusion because both known indicators are below threshold;
4. review because employee count is missing and revenue is below threshold;
5. review because no SPARK-like INN match is available.

Input files:

- `input/sample_source.csv`;
- `input/sample_active_enriched.csv`;
- `input/sample_spark_extracted.csv` — a schema-compatible extracted table, not a raw commercial export.

Output files:

- `output/sample_clean_with_metadata.csv`;
- `output/sample_dirty.csv`;
- `output/sample_size_filter_all.csv`;
- `output/sample_included.csv`;
- `output/sample_excluded.csv`;
- `output/sample_review.csv`;
- `output/sample_described.csv`;
- `output/sample_map_upload_ready_COMMA_STRICT_FLAT.csv`.

All CSV files use UTF-8 with BOM and standard CSV quoting where required.
