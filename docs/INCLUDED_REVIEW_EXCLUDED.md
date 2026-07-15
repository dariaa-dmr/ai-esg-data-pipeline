# Included, Review, and Excluded Criteria

## Purpose

The mature pipeline separates evidence-based inclusion from unresolved cases. The review route is a substantive methodological category, not an error folder.

## Included

A record is included when at least one supported size criterion is satisfied:

```text
CompanyEmployees >= 100
OR
CompanyRevenueRawRUB >= 1,000,000
```

Typical reason codes include:

- `employees>=100`;
- `revenue>=1000000`.

## Excluded

A record is excluded only when both indicators are available and both fall below their thresholds:

```text
CompanyEmployees < 100
AND
CompanyRevenueRawRUB < 1,000,000
```

Typical reason code:

- `employees<100_and_revenue<1000000`.

This conservative rule avoids treating missing information as evidence of small size.

## Review

A record is routed to review when evidence is insufficient or the match is unresolved. Typical reasons include:

- no SPARK match;
- both employee count and revenue are missing;
- employee count is below the threshold but revenue is missing;
- revenue is below the threshold but employee count is missing;
- unresolved or conflicting size evidence.

## Archived run

The archived mature pre-RFSD run produced:

| Route | Rows |
|---|---:|
| Included | 1,890 |
| Excluded | 0 |
| Review | 471 |

The zero excluded count describes the archived run; it does not mean that the exclusion branch was absent. The branch existed, but no records met the conservative exclusion rule in that run.

## Manual handling

Review records may be examined using additional licensed data, company websites, organization registries, or documented manual overrides. Any override should preserve the original automated route and store an explicit reason.
