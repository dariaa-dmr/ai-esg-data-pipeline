# Limitations

## Public-source coverage

Company websites and public records differ substantially in completeness, update frequency, terminology, and accessibility. Absence of a disclosed fact does not prove absence of the underlying practice.

## External-service dependence

Dadata, Yandex geocoding, and optional YandexGPT execution depend on external services, credentials, rate limits, model versions, and service availability. Results may therefore vary across execution dates.

## Proprietary SPARK materials

Raw SPARK exports are licensed commercial materials and cannot be redistributed. The public repository can reproduce the parsing and matching logic only with synthetic or independently obtained schema-compatible input.

## Historical dataset reconstruction

The complete working dataset is not included because it contains full operational records, licensed extracts, intermediate files, caches, and source materials unsuitable for public release. The repository therefore supports methodological and code reproducibility rather than exact public reconstruction of every historical record.

## Matching uncertainty

INN provides a strong organization identifier, but missing, malformed, duplicated, or outdated identifiers can still lead to unresolved matches. Review routing reduces, but does not eliminate, this limitation.

## Size threshold evidence

Employee and revenue values may refer to different reporting years or may be missing. The conservative review route avoids automatic exclusion but leaves a substantial unresolved group.

## Classification uncertainty

Sector, industry, subindustry, and regional classifications may be ambiguous for diversified or vertically integrated firms. Composite keys preserve analytical distinctions but do not guarantee that every classification is substantively unique.

## Generated descriptions

Descriptions are generated or edited from structured fields. Automated quality checks detect common problems but do not replace complete expert review. Manual verification was targeted to flagged, incomplete, or disputed cases rather than performed exhaustively for every description.

## Temporal scope

The dataset reflects the information available during the collection and validation period. Company status, websites, workforce, revenue, and operating geography can change.

## Snapshot boundary

The public paper snapshot ends before RFSD/RBBO. Later extensions may improve the workflow but should not be interpreted as part of the methods used for the paper version.
