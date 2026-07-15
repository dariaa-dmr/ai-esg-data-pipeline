# Architecture Evolution

## Purpose

The repository presents a compact research history rather than every working revision. The comparison begins with an already improved linear pipeline and ends with the mature pre-RFSD paper snapshot.

## Stage 1: improved linear pipeline

The earlier architecture used a mostly sequential flow:

```text
source CSV
→ versioned working copy
→ split clean and dirty records
→ retry/repair
→ Dadata enrichment
→ Yandex geocoding
→ integrity restoration
→ active-company normalization
→ final assembly
→ grouped outputs
```

This version established the basic processing logic and demonstrated that heterogeneous company records could be transformed into a structured map dataset. Its main limitation was that most decisions remained inside one primary flow, with less explicit separation between confirmed, rejected, and unresolved cases.

## Stage 2: mature multi-stage and branched pipeline

The pre-RFSD version transformed the sequential flow into a layered pipeline with explicit control nodes:

```text
collection and CSV versioning
             ↓
      clean / dirty / retry
             ↓
 Dadata enrichment and geocoding
             ↓
identity, integrity, recovery, deduplication
             ↓
      offline SPARK verification
             ↓
   included / excluded / review
        ↙          ↓          ↘
 descriptions   reports   manual review
             ↓
  grouped and public exports
             ↓
         quality gate
```

The main change was not simply the addition of more scripts. The pipeline began to preserve uncertainty explicitly. Records were routed to review instead of being silently discarded when evidence was incomplete.

## Key design changes

| Design dimension | Improved linear snapshot | Mature pre-RFSD snapshot |
|---|---|---|
| Main control logic | Predominantly sequential | Multi-stage with explicit branches |
| Problematic CSV rows | Dirty and retry folders | Dirty/retry plus stable row identity and reports |
| Identity | Primarily company identifiers | `record_id` plus composite fallback keys |
| Deduplication | Earlier implementation | Composite key preserving legitimate repeated INNs |
| SPARK | Not a mature contour | Offline request, extraction, match, filter, and evidence |
| Uncertain size | Limited handling | Explicit `review` route |
| Descriptions | Earlier generator | Rule-based builder plus constrained optional LLM editor |
| Export | Final grouping | Category exports and strict public map export |
| Final control | Integrity checks | Formal quality gate and public-export validation |

## Relationship to the paper figure

The architecture figure is conceptual. A single block in the figure may correspond to several scripts in the repository. For example, the SPARK block is implemented through request preparation, extraction, structured parsing, matching, size filtering, and report generation.

## RFSD/RBBO

RFSD/RBBO belongs to a later development phase. It is excluded from the paper snapshot to keep the repository aligned with the architecture and methods actually described in the article.
