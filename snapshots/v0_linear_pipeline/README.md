# v0 — Improved Linear Pipeline

## Role in the repository

This snapshot represents the improved linear system discussed as the earlier stage of the pipeline evolution. It is not the very first experimental prototype.

Its primary logic is sequential:

```text
incoming
→ backup/source
→ CSV splitting
→ clean/dirty/retry
→ Dadata enrichment
→ Yandex geocoding
→ integrity and recovery
→ final assembly
→ grouped outputs
```

## What this snapshot demonstrates

- detection and repair of inconsistent CSV input;
- separation of processable and problematic records;
- enrichment using company identifiers;
- geocoding;
- restoration of selected fields;
- active-company normalization;
- final assembly and grouping.

## What had not yet matured

This version does not contain the mature pre-RFSD implementation of:

- the complete offline SPARK contour;
- explicit `included/review/excluded` routing;
- a formal quality gate;
- strict public map exports;
- the later description-builder and constrained YandexGPT editing layer.

## Included files

The `src/` directory contains a curated historical code snapshot. `SOURCE_MANIFEST.md` records the included files and their SHA-256 hashes.

## Data policy

No complete historical working data is distributed. The `sample_data/` directory is reserved for small synthetic input and output examples.

## Interpretation

This snapshot is included to make the architecture evolution visible to readers and reviewers. It should not be treated as the principal implementation underlying the final pre-RFSD paper results.
