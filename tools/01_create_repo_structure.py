#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

FOLDERS = [
    "docs",
    "figures",
    "tools",
    "snapshots/v0_linear_pipeline/src",
    "snapshots/v0_linear_pipeline/sample_data/input",
    "snapshots/v0_linear_pipeline/sample_data/output",
    "snapshots/v0_linear_pipeline/schemas",
    "snapshots/v1_pre_rfsd_paper_snapshot/src",
    "snapshots/v1_pre_rfsd_paper_snapshot/sample_data/input",
    "snapshots/v1_pre_rfsd_paper_snapshot/sample_data/output",
    "snapshots/v1_pre_rfsd_paper_snapshot/schemas",
]

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the folder structure for ai-esg-data-pipeline."
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Existing repository folder. Default: current folder.",
    )
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()

    if not target.exists():
        print(f"ERROR: folder does not exist: {target}")
        return 1

    if not target.is_dir():
        print(f"ERROR: target is not a folder: {target}")
        return 1

    if target.name.lower() != "ai-esg-data-pipeline":
        print("WARNING: the folder name is not 'ai-esg-data-pipeline'.")
        print(f"Current folder: {target}")

    created = []
    existing = []

    for relative in FOLDERS:
        path = target / Path(relative)
        if path.exists():
            existing.append(relative)
        else:
            path.mkdir(parents=True, exist_ok=False)
            created.append(relative)

    print()
    print("Repository structure is ready.")
    print(f"Target: {target}")
    print()

    if created:
        print("Created folders:")
        for item in created:
            print(f"  + {item}")

    if existing:
        print()
        print("Already existed:")
        for item in existing:
            print(f"  = {item}")

    print()
    print("No files were deleted, overwritten, copied, or published.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
