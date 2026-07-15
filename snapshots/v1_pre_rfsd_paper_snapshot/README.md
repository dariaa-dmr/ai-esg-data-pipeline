# v1 — Mature Pre-RFSD Paper Snapshot

## Role in the repository

This is the principal code snapshot associated with the architecture described in the paper. It represents the mature pipeline before RFSD/RBBO was introduced.

## Main architectural additions

Compared with the improved linear snapshot, this version adds:

- stable row identity and source metadata;
- strengthened `clean/dirty/retry` processing;
- no-data-loss restoration and row-count checks;
- composite-key deduplication;
- an offline SPARK request, extraction, matching, and size-verification contour;
- explicit `included`, `excluded`, and `review` routes;
- rule-based description construction with optional constrained YandexGPT editing;
- manual overrides for documented exceptional cases;
- category and public map exports;
- a formal quality gate.

## Archived run totals

The archived working run associated with this snapshot reported:

| Output | Rows |
|---|---:|
| Active | 2,361 |
| Included | 1,890 |
| Excluded | 0 |
| Review | 471 |
| Described | 1,890 |

The archived quality gate and public export checks both passed.

These counts are provenance information for the archived research run. Full working files are not included in this public package.

## SPARK contour

SPARK is represented as an offline/manual verification contour rather than as a public API dependency. Raw licensed exports are not redistributed. The public repository contains only the parsing, matching, routing, and validation code, together with synthetic schema-compatible examples.

## Description layer

The description layer first builds a fact-bounded rule-based description. When credentials are available, YandexGPT may edit the first three sentences using only the supplied structured fields. The final sentence containing employee and financial information is fixed by the rule-based layer. The output is then checked for structure, prohibited promotional language, missing facts, and review conditions.

## RFSD/RBBO boundary

RFSD/RBBO is deliberately absent from this snapshot because it was added after the architecture described in the paper. It may be mentioned in the documentation only as a subsequent extension.

## Included files

The `src/` directory contains the curated canonical scripts. Historical copies, patch scripts, raw exports, caches, logs, and working datasets were excluded. See `SOURCE_MANIFEST.md`.
