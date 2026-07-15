# Reproducibility

## Reproducibility levels

The repository distinguishes three levels:

1. **Architectural reproducibility** — readers can inspect the stages, branches, interfaces, and validation logic.
2. **Code and schema reproducibility** — readers can run curated modules on synthetic schema-compatible examples.
3. **Historical full-data reproduction** — requires original public-source collection, service credentials, and licensed SPARK input and is therefore not fully public.

## Recommended environment

- Windows, macOS, or Linux;
- Python 3.10 or later;
- a virtual environment;
- dependencies listed in the relevant snapshot.

## Windows CMD setup

From the repository root:

```cmd
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

To create a local configuration for a snapshot:

```cmd
copy snapshots\v1_pre_rfsd_paper_snapshot\config.example.ini snapshots\v1_pre_rfsd_paper_snapshot\config.ini
```

Do not commit the resulting `config.ini`. Add credentials only to local configuration, environment variables, or ignored local secret storage.

## Snapshot selection

Use:

```text
snapshots/v0_linear_pipeline
```

to inspect the improved linear history.

Use:

```text
snapshots/v1_pre_rfsd_paper_snapshot
```

for the principal pre-RFSD paper architecture.

## Sample execution

Synthetic sample files and canonical schemas will be added to each snapshot before release. They are intended to demonstrate:

- source parsing;
- clean/dirty routing;
- identifier preservation;
- SPARK-like matching;
- included/review/excluded routing;
- description output;
- strict public map export.

They are not intended to reproduce the full archived row counts.

## External services

Live Dadata, Yandex geocoding, and YandexGPT calls require the user's own credentials and may create costs or rate-limit effects. A publication reviewer can inspect the client and transformation code without invoking those services.

## SPARK

To test the SPARK contour without licensed material, use the synthetic extracted table supplied in the sample package. Do not upload raw licensed exports to a public fork.

## Safety verification

Before publication or release, run:

```cmd
python tools\repo_safety_scan.py . --large-mb 5 --out tools\final_release_scan
```

The release should have zero credential-like findings, zero blocked working paths, zero raw/cache/binary findings, and no unexpected large files.

## Versioning

The intended release tag is:

```text
v1.0-paper-snapshot-pre-rfsd
```

The release should be created only after documentation, sample schemas, license, citation metadata, and the final safety report have been reviewed.
