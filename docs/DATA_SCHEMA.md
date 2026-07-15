# Data Schema

## Core source schema

The input splitter expects the following twelve fields:

| Field | Meaning |
|---|---|
| `Sector` | High-level economic sector |
| `Industry` | Industry classification |
| `Subindustry` | More specific activity group |
| `CompanyName` | Short display name |
| `CompanyNameOfficial` | Official legal name |
| `INN` | Russian taxpayer identifier |
| `RegionRegistration` | Legal registration region |
| `RegionHeadOffice` | Head-office region |
| `RegionOperation` | Regions of operation |
| `Description` | Source-stage factual description |
| `URL` | Company or evidence URL |
| `Source` | Source attribution |

## Parsing and provenance metadata

The mature snapshot adds fields used to preserve provenance and parsing decisions:

| Field | Meaning |
|---|---|
| `record_id` | Stable row identifier |
| `source_file` | Input filename |
| `source_row_no` | Logical source row number |
| `physical_line` | Physical line reference |
| `parse_status` | Parsing result |
| `parse_reason` | Reason for the route or repair |
| `raw_line` | Preserved source text for review |

## Enrichment fields

Representative Dadata and geocoding fields include:

| Field | Meaning |
|---|---|
| `CompanyName_dadata` | Normalized organization name |
| `Address_dadata` | Standardized address |
| `OKVED_dadata` | Activity classification returned by the service |
| `lat_dadata` | Latitude used for map export |
| `lon_dadata` | Longitude used for map export |

The exact set of service-returned fields may vary by configuration and source response.

## SPARK-derived fields

The offline verification contour may produce:

| Field | Meaning |
|---|---|
| `SparkMatched` | Whether an INN match was found |
| `SparkMatchStatus` | Human-readable match status |
| `SparkMatchedAt` | Match timestamp |
| `CompanyEmployees` | Employee count |
| `CompanyEmployeesYear` | Reporting year |
| `CompanyEmployeesSource` | Evidence/source field |
| `CompanyRevenueRawRUB` | Revenue in raw ruble units |
| `CompanyRevenue` | Formatted revenue |
| `CompanyRevenueYear` | Reporting year |
| `CompanyRevenueSource` | Evidence/source field |
| `CompanyFoundedYear` | Foundation year |
| `SparkActivity` | Activity information |
| `SparkEvidenceText` | Extracted supporting text |
| `SparkWebsite` | Website found in the licensed source |

## Routing fields

| Field | Meaning |
|---|---|
| `size_status` | Include, exclude, or review decision |
| `size_reason` | Machine-readable reason for the decision |
| `manual_override` | Documented exceptional adjustment, when applied |
| `manual_override_reason` | Explanation for the adjustment |

Exact capitalization may differ in historical files; the public schemas will document the canonical sample format.

## Description fields

| Field | Meaning |
|---|---|
| `CompanyDescription` | Final factual company description |
| `description_status` | Quality or review status |
| `description_issues` | Detected problems |
| `description_quality_score` | Automated quality score where produced |
| `description_model` | Rule-based or configured LLM mode |

## Strict public map schema

The strict map export uses the following columns:

```text
id,title,lat,lon,address,description,inn,region,industry,subindustry,website,description_status
```

The export normalizes line breaks and removes delimiter-breaking punctuation from fields so that every physical line contains the expected number of commas.

## Synthetic examples

The `sample_data/` and `schemas/` folders will contain small synthetic files. They will preserve the structure and routing logic without reproducing real commercial exports or the complete research dataset.
