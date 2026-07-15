"""Centralised path/config helpers for the CSV pipeline."""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path


RUNTIME_SECTION = "_runtime"


def read_config(path: str | Path) -> configparser.ConfigParser:
    cfg_path = Path(path).expanduser().resolve()
    cfg = configparser.ConfigParser()
    read_files = cfg.read(cfg_path, encoding="utf-8")
    if not read_files:
        raise FileNotFoundError(f"Config not found: {cfg_path}")
    if not cfg.has_section(RUNTIME_SECTION):
        cfg.add_section(RUNTIME_SECTION)
    cfg.set(RUNTIME_SECTION, "config_path", str(cfg_path))
    cfg.set(RUNTIME_SECTION, "config_dir", str(cfg_path.parent))
    return cfg


def get_config_dir(cfg: configparser.ConfigParser) -> Path:
    value = cfg.get(RUNTIME_SECTION, "config_dir", fallback="")
    return Path(value).expanduser().resolve() if value else Path.cwd().resolve()


def resolve_path(
    cfg: configparser.ConfigParser,
    section: str,
    option: str,
    default: str,
    *,
    base_dir: str | Path | None = None,
) -> Path:
    raw = cfg.get(section, option, fallback=default).strip()
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p.resolve()
    base = Path(base_dir).expanduser().resolve() if base_dir else get_config_dir(cfg)
    return (base / p).resolve()


@dataclass(frozen=True)
class PipelinePaths:
    incoming: Path
    retry: Path
    clean: Path
    dirty: Path
    review: Path
    enriched: Path
    geo: Path
    final: Path
    reports: Path
    export_by_category: Path
    archive: Path
    logs: Path
    cache: Path
    backup_source: Path
    secrets: Path

    def as_dict(self) -> dict[str, Path]:
        return self.__dict__.copy()


def load_paths(cfg: configparser.ConfigParser, create: bool = True) -> PipelinePaths:
    p = PipelinePaths(
        incoming=resolve_path(cfg, "paths", "incoming", "incoming"),
        retry=resolve_path(cfg, "paths", "retry", "retry"),
        clean=resolve_path(cfg, "paths", "clean", "clean"),
        dirty=resolve_path(cfg, "paths", "dirty", "dirty"),
        review=resolve_path(cfg, "paths", "review", "review"),
        enriched=resolve_path(cfg, "paths", "enriched", "enriched"),
        geo=resolve_path(cfg, "paths", "geo", "geo"),
        final=resolve_path(cfg, "paths", "final", "final"),
        reports=resolve_path(cfg, "paths", "reports", "final/reports"),
        export_by_category=resolve_path(cfg, "paths", "export_by_category", "final/export_by_category"),
        archive=resolve_path(cfg, "paths", "archive", "archive"),
        logs=resolve_path(cfg, "paths", "logs", "logs"),
        cache=resolve_path(cfg, "paths", "cache", "cache"),
        backup_source=resolve_path(cfg, "paths", "backup_source", "backup/source"),
        secrets=resolve_path(cfg, "paths", "secrets", "secrets"),
    )
    if create:
        for path in p.as_dict().values():
            path.mkdir(parents=True, exist_ok=True)
    return p


def get_secret(
    cfg: configparser.ConfigParser,
    env_name: str,
    filename: str,
    *,
    section: str = "api",
    option: str | None = None,
    default: str = "",
) -> str:
    env_value = os.getenv(env_name)
    if env_value:
        return env_value.strip()
    secrets_dir = resolve_path(cfg, "paths", "secrets", "secrets")
    secret_path = secrets_dir / filename
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()
    if option:
        return cfg.get(section, option, fallback=default).strip()
    return default
