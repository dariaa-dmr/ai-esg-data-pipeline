# Validation Rules

## General principle: no silent data loss

A record must not disappear without an explicit route or report. Depending on the stage, a record may be:

- accepted for further processing;
- preserved as dirty or retry input;
- classified as active or inactive;
- routed to included, excluded, or review;
- sent to a technical export folder;
- flagged in a quality report.

## CSV validation

The splitter:

- detects likely encoding;
- detects comma, semicolon, tab, or pipe delimiters;
- parses quoted fields;
- uses INN as a repair anchor when possible;
- expects twelve source fields;
- preserves unresolved source text;
- records parse status and reason.

## Identifier validation

INN is normalized to digits. Ten- and twelve-digit identifiers are expected. Missing or malformed identifiers are not silently converted into verified matches.

## Integrity restoration

Stable source and classification values may be restored from the clean reference layer. The preferred join is `record_id`. Older files may use a composite fallback key:

```text
INN + RegionRegistration + Sector + Industry + Subindustry
```

Restoration fills empty cells only. It must not change the number of records.

## Deduplication

A repeated INN alone is not sufficient to remove a record. The composite classification and regional key protects legitimate repeated representations of the same organization in different analytical categories.

## SPARK matching

Structured SPARK-like data is matched by normalized INN. A match indicator and timestamp are stored. Missing matches remain visible and are routed to review.

## Size validation

Default thresholds in the archived pre-RFSD implementation are:

```text
minimum employees = 100
minimum revenue = 1,000,000 RUB
```

A record is included when either known threshold is met. A record is excluded only when both employee count and revenue are known and both are below their thresholds. Incomplete evidence is routed to review.

## Description validation

Descriptions must:

- rely only on supplied structured facts;
- use a neutral factual style;
- avoid advertising or superlative language;
- avoid unsupported claims;
- avoid links and source narration inside the description;
- preserve the rule-generated employee and financial sentence;
- satisfy structural checks used by the description builder.

Problematic rows receive `description_status` and `description_issues` values for targeted review.

## Export validation

The strict public map export checks:

- expected column order;
- physical line count;
- number of data rows;
- fixed delimiter count per line;
- coordinate availability statistics;
- agreement between source and exported row totals.

## Quality gate

The quality gate is read-only. It reports PASS, WARN, or FAIL conditions and checks, where applicable:

- required input/output files;
- active row count;
- SPARK partition identity;
- record identifiers;
- INN completeness;
- included-record validity;
- export source selection;
- exported row totals.
