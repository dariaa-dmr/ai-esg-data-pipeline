"""Small CMD helper for choosing pipeline inputs without editing config.ini by hand.

This is not a one-button runner. It only shows status and writes selected filters/paths
into config.ini, so the ordinary scripts still run stage by stage.
"""
from __future__ import annotations

import argparse
import configparser
from pathlib import Path

import pandas as pd

from paths import read_config, resolve_path, get_config_dir


EXPORT_MODES = {
    "auto": "auto: described -> spark_included -> active",
    "active": "use final/all_sectors_final_active.csv",
    "spark_included": "use final/all_sectors_final_active_spark_included.csv",
    "described": "use final/all_sectors_final_active_described.csv",
    "custom": "use [export] input_csv custom path",
}


def row_count(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        return str(len(pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")))
    except Exception as exc:
        return f"exists but unreadable: {exc}"


def load_for_write(config_path: str | Path) -> configparser.ConfigParser:
    p = Path(config_path)
    cfg = configparser.ConfigParser()
    cfg.read(p, encoding="utf-8")
    return cfg


def save_config(cfg: configparser.ConfigParser, config_path: str | Path) -> None:
    with Path(config_path).open("w", encoding="utf-8") as f:
        cfg.write(f)


def status(config_path: str) -> None:
    cfg = read_config(config_path)
    candidates = {
        "active": resolve_path(cfg, "spark", "active_input_csv", "final/all_sectors_final_active.csv"),
        "spark_all": resolve_path(cfg, "spark", "matched_csv", "final/all_sectors_final_active_spark.csv"),
        "spark_included": resolve_path(cfg, "spark", "included_csv", "final/all_sectors_final_active_spark_included.csv"),
        "spark_excluded": resolve_path(cfg, "spark", "excluded_csv", "final/all_sectors_final_active_spark_excluded.csv"),
        "spark_review": resolve_path(cfg, "spark", "review_csv", "final/review/size_filter_unknown/size_filter_unknown.csv"),
        "described": resolve_path(cfg, "descriptions", "output_csv", "final/all_sectors_final_active_described.csv"),
        "export_dir": resolve_path(cfg, "paths", "export_by_category", "final/export_by_category"),
        "spark_incoming": resolve_path(cfg, "spark", "incoming_dir", "spark/incoming"),
    }
    print("PIPELINE STATUS")
    print("=" * 70)
    for name, path in candidates.items():
        if path.is_dir():
            files = len([p for p in path.rglob("*") if p.is_file()]) if path.exists() else 0
            print(f"{name:16} {path} | files={files}")
        else:
            print(f"{name:16} {path} | rows={row_count(path)}")
    print("=" * 70)
    print(f"export.input_mode = {cfg.get('export', 'input_mode', fallback='auto')}")
    print(f"export.input_csv  = {cfg.get('export', 'input_csv', fallback='')}")
    print(f"spark.active_input_csv = {cfg.get('spark', 'active_input_csv', fallback='')}")


def choose_export(config_path: str, mode: str | None = None, custom_path: str | None = None) -> None:
    if mode is None:
        print("Choose export input mode:")
        for i, (m, desc) in enumerate(EXPORT_MODES.items(), start=1):
            print(f"{i}. {m} — {desc}")
        choice = input("Number or mode [auto]: ").strip() or "auto"
        if choice.isdigit():
            keys = list(EXPORT_MODES)
            idx = int(choice) - 1
            mode = keys[idx] if 0 <= idx < len(keys) else "auto"
        else:
            mode = choice
    mode = mode.strip().lower()
    if mode not in EXPORT_MODES:
        raise ValueError(f"Unknown export mode: {mode}. Allowed: {', '.join(EXPORT_MODES)}")
    if mode == "custom" and not custom_path:
        custom_path = input("Path to custom export input CSV: ").strip()
        if not custom_path:
            raise ValueError("custom mode requires a path")
    cfg = load_for_write(config_path)
    if not cfg.has_section("export"):
        cfg.add_section("export")
    cfg.set("export", "input_mode", mode)
    if custom_path:
        cfg.set("export", "input_csv", custom_path)
    save_config(cfg, config_path)
    print(f"Saved: export.input_mode={mode}")
    if custom_path:
        print(f"Saved: export.input_csv={custom_path}")


def choose_spark_input(config_path: str, active_path: str | None = None) -> None:
    cfg_read = read_config(config_path)
    default_active = resolve_path(cfg_read, "spark", "active_input_csv", "final/all_sectors_final_active.csv")
    if active_path is None:
        print("Choose active file for SPARK matching.")
        print(f"1. Current/default: {default_active} | rows={row_count(default_active)}")
        print("2. Custom path")
        choice = input("Number [1]: ").strip() or "1"
        if choice == "2":
            active_path = input("Path to active CSV: ").strip()
        else:
            active_path = str(default_active)
    cfg = load_for_write(config_path)
    if not cfg.has_section("spark"):
        cfg.add_section("spark")
    cfg.set("spark", "active_input_csv", active_path)
    save_config(cfg, config_path)
    print(f"Saved: spark.active_input_csv={active_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and configure pipeline stage inputs.")
    parser.add_argument("command", choices=["status", "choose-export", "choose-spark-input"])
    parser.add_argument("--config", default="config.ini")
    parser.add_argument("--mode", choices=list(EXPORT_MODES), default=None, help="For choose-export")
    parser.add_argument("--path", default=None, help="Custom CSV path")
    args = parser.parse_args()
    if args.command == "status":
        status(args.config)
    elif args.command == "choose-export":
        choose_export(args.config, args.mode, args.path)
    elif args.command == "choose-spark-input":
        choose_spark_input(args.config, args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
