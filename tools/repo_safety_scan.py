#!/usr/bin/env python3
r"""Safety scanner for a research repository or ZIP archive.

The scanner never prints credential values. It reports only file path, line,
credential key name, value length, and a short SHA-256 fingerprint.

Examples for Windows CMD:
    python repo_safety_scan.py C:\path\to\ai-esg-data-pipeline
    python repo_safety_scan.py C:\path\to\archive.zip --large-mb 5
    python repo_safety_scan.py . --out safety_report

Outputs:
    <out>.json
    <out>.md

Exit codes:
    0 = no confirmed credential-like values found
    2 = one or more credential-like values found
    1 = scanner error
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator

TEXT_EXTENSIONS = {
    ".py", ".ini", ".cfg", ".conf", ".toml", ".yaml", ".yml", ".json",
    ".md", ".txt", ".log", ".env", ".bat", ".cmd", ".ps1", ".cff",
}

SECRET_SCAN_SKIP_DIRS = {
    ".venv", "venv", "__pycache__", "cache", "cache_before_yandex_test",
    "archive", "backup", "incoming", "retry", "clean", "dirty", "review",
    "enriched", "geo", "final", "grouped", "grouped_from_clean", "unpacked",
    "extracted", "matched", "test_reports",
}

BLOCKED_DIR_NAMES = {
    ".venv", "venv", "__pycache__", "secrets", "cache", "logs", "archive",
    "backup", "incoming", "retry", "clean", "dirty", "review", "enriched",
    "geo", "final", "grouped", "grouped_from_clean", "unpacked",
}

BLOCKED_SUFFIXES = {
    ".sqlite", ".sqlite3", ".db", ".xml", ".html", ".htm", ".xlsx", ".xls",
    ".zip", ".7z", ".rar", ".log", ".pyc", ".pyd", ".dll", ".exe",
}

SECRET_KEY_RE = re.compile(
    r"(?i)(?:^|[_.-])(?:api[_-]?key|apikey|access[_-]?token|oauth[_-]?token|"
    r"iam[_-]?token|token|password|passwd|secret|client[_-]?secret|bearer|"
    r"folder[_-]?id)(?:$|[_.-])"
)

ASSIGNMENT_RE = re.compile(
    r"^\s*([A-Za-z0-9_.-]+)\s*[:=]\s*(.*?)\s*$"
)

BEARER_RE = re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+\-/=]{12,})")
URL_SECRET_RE = re.compile(
    r"(?i)(?:api[_-]?key|apikey|token|secret|password)=([^&\s'\"]{6,})"
)

PLACEHOLDER_WORDS = {
    "", "none", "null", "false", "true", "example", "placeholder", "changeme",
    "replace_me", "insert_here", "your_key", "your_token", "your_secret",
    "ваш_ключ", "ваш_токен", "ваш_секрет", "xxx", "xxxx", "...",
}

CODE_VALUE_RE = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_.]*|[A-Za-z_][A-Za-z0-9_.]*\(.*\)|"
    r"os\.getenv\(.*\)|get_secret\(.*\)|cfg\.get\(.*\)|config\.get\(.*\))$"
)


@dataclass
class FileEntry:
    path: str
    size: int
    data: bytes | None


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "cp866"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def iter_directory(root: Path) -> Iterator[FileEntry]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        data = None
        if size <= 5 * 1024 * 1024 and path.suffix.lower() in TEXT_EXTENSIONS:
            try:
                data = path.read_bytes()
            except OSError:
                data = None
        yield FileEntry(rel, size, data)


def iter_zip(path: Path) -> Iterator[FileEntry]:
    with zipfile.ZipFile(path) as archive:
        files = [item for item in archive.infolist() if not item.is_dir()]
        root_prefix = ""
        roots = {item.filename.split("/", 1)[0] for item in files if "/" in item.filename}
        if len(roots) == 1:
            root_prefix = next(iter(roots)) + "/"
        for item in files:
            rel = item.filename[len(root_prefix):] if item.filename.startswith(root_prefix) else item.filename
            data = None
            suffix = PurePosixPath(rel).suffix.lower()
            if item.file_size <= 5 * 1024 * 1024 and suffix in TEXT_EXTENSIONS:
                try:
                    data = archive.read(item)
                except Exception:
                    data = None
            yield FileEntry(rel, item.file_size, data)


def value_is_placeholder_or_code(raw_value: str) -> bool:
    value = raw_value.strip().strip("'\"")
    lower = value.lower()
    if lower in PLACEHOLDER_WORDS:
        return True
    if any(token in lower for token in ("${", "%", "<", ">", "{", "}", "placeholder", "example", "your_", "ваш_")):
        return True
    if value.startswith(("secrets/", "secrets\\")):
        return True
    if CODE_VALUE_RE.fullmatch(value):
        return True
    if set(value) <= {"*", "x", "X", ".", "-", "_"}:
        return True
    return False


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:12]


def skip_secret_scan(path: str) -> bool:
    parts = [part.lower() for part in PurePosixPath(path.replace("\\", "/")).parts]
    if any(part in SECRET_SCAN_SKIP_DIRS for part in parts):
        return True
    return bool(parts and parts[0] == "spark")


def scan_text(path: str, text: str) -> list[dict]:
    findings: list[dict] = []
    suffix = PurePosixPath(path).suffix.lower()
    python_assignment = re.compile(
        r"^\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*=\s*(['\"])(.*?)\2\s*(?:#.*)?$"
    )
    for line_no, line in enumerate(text.splitlines(), start=1):
        match = python_assignment.match(line) if suffix == ".py" else ASSIGNMENT_RE.match(line)
        if match and SECRET_KEY_RE.search(match.group(1)):
            if suffix == ".py":
                key, value = match.group(1), match.group(3).strip()
            else:
                key, raw_value = match.group(1), match.group(2)
                value = raw_value.split("#", 1)[0].split(";", 1)[0].strip().strip("'\"")
            if value and not value_is_placeholder_or_code(value):
                findings.append({
                    "path": path,
                    "line": line_no,
                    "kind": "credential_assignment",
                    "key": key,
                    "value_length": len(value),
                    "value_sha256_prefix": fingerprint(value),
                })
        for regex, kind in ((BEARER_RE, "bearer_token"), (URL_SECRET_RE, "url_credential")):
            for secret_match in regex.finditer(line):
                value = secret_match.group(1).rstrip(",);]}")
                if not value_is_placeholder_or_code(value):
                    findings.append({
                        "path": path,
                        "line": line_no,
                        "kind": kind,
                        "key": kind,
                        "value_length": len(value),
                        "value_sha256_prefix": fingerprint(value),
                    })
    unique = []
    seen = set()
    for finding in findings:
        key = tuple(finding.items())
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return unique

def is_blocked_path(path: str) -> bool:
    parts = [part.lower() for part in PurePosixPath(path.replace("\\", "/")).parts]
    if any(part in BLOCKED_DIR_NAMES for part in parts):
        return True
    low = path.replace("\\", "/").lower()
    return low.startswith("spark/incoming/") or low.startswith("spark/unpacked/")


def make_markdown(report: dict) -> str:
    lines = [
        "# Repository safety scan",
        "",
        f"- Target: `{report['target']}`",
        f"- Files scanned: **{report['summary']['files_scanned']}**",
        f"- Total size: **{report['summary']['total_size_mb']:.2f} MB**",
        f"- Credential-like findings: **{report['summary']['credential_findings']}**",
        f"- Blocked/working paths: **{report['summary']['blocked_paths']}**",
        f"- Raw/cache/binary file types: **{report['summary']['blocked_suffixes']}**",
        f"- Large files: **{report['summary']['large_files']}**",
        "",
        "The report intentionally does not print credential values.",
        "",
    ]
    if report["credential_findings"]:
        lines += ["## Credential-like findings", "", "| File | Line | Key | Length | Fingerprint |", "|---|---:|---|---:|---|"]
        for item in report["credential_findings"]:
            lines.append(
                f"| `{item['path']}` | {item['line']} | `{item['key']}` | "
                f"{item['value_length']} | `{item['value_sha256_prefix']}` |"
            )
        lines.append("")
    for title, key in (
        ("Blocked or working-data paths", "blocked_paths"),
        ("Raw/cache/binary file types", "blocked_suffixes"),
        ("Large files", "large_files"),
    ):
        items = report[key]
        lines += [f"## {title}", ""]
        if not items:
            lines += ["None.", ""]
            continue
        lines += ["| File | Size MB |", "|---|---:|"]
        limit = 200
        for item in items[:limit]:
            lines.append(f"| `{item['path']}` | {item['size'] / 1024 / 1024:.2f} |")
        if len(items) > limit:
            lines.append(f"| `... {len(items) - limit} additional items in JSON report` |  |")
        lines.append("")
    verdict = "FAIL: review credential-like findings before publication." if report["credential_findings"] else "PASS for credential values; publication exclusions still require review."
    lines += ["## Verdict", "", f"**{verdict}**", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a directory or ZIP before GitHub publication.")
    parser.add_argument("target", help="Directory or ZIP archive to scan")
    parser.add_argument("--large-mb", type=float, default=10.0, help="Large-file threshold in MB (default: 10)")
    parser.add_argument("--out", default="safety_report", help="Output basename without extension")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    if not target.exists():
        print(f"ERROR: target does not exist: {target}", file=sys.stderr)
        return 1

    try:
        entries: Iterable[FileEntry]
        if target.is_dir():
            entries = iter_directory(target)
        elif zipfile.is_zipfile(target):
            entries = iter_zip(target)
        else:
            print("ERROR: target must be a directory or ZIP archive", file=sys.stderr)
            return 1

        blocked_paths = []
        blocked_suffixes = []
        large_files = []
        credential_findings = []
        files_scanned = 0
        total_size = 0
        threshold = int(args.large_mb * 1024 * 1024)

        for entry in entries:
            files_scanned += 1
            total_size += entry.size
            if is_blocked_path(entry.path):
                blocked_paths.append({"path": entry.path, "size": entry.size})
            if PurePosixPath(entry.path).suffix.lower() in BLOCKED_SUFFIXES:
                blocked_suffixes.append({"path": entry.path, "size": entry.size})
            if entry.size >= threshold:
                large_files.append({"path": entry.path, "size": entry.size})
            if entry.data is not None and not skip_secret_scan(entry.path):
                credential_findings.extend(scan_text(entry.path, decode_text(entry.data)))

        key_fn = lambda item: (-item["size"], item["path"].lower())
        blocked_paths.sort(key=key_fn)
        blocked_suffixes.sort(key=key_fn)
        large_files.sort(key=key_fn)
        credential_findings.sort(key=lambda item: (item["path"].lower(), item["line"], item["key"].lower()))

        report = {
            "target": str(target),
            "summary": {
                "files_scanned": files_scanned,
                "total_size_mb": total_size / 1024 / 1024,
                "credential_findings": len(credential_findings),
                "blocked_paths": len(blocked_paths),
                "blocked_suffixes": len(blocked_suffixes),
                "large_files": len(large_files),
            },
            "credential_findings": credential_findings,
            "blocked_paths": blocked_paths,
            "blocked_suffixes": blocked_suffixes,
            "large_files": large_files,
        }

        out_base = Path(args.out)
        out_base.parent.mkdir(parents=True, exist_ok=True)
        json_path = out_base.with_suffix(".json")
        md_path = out_base.with_suffix(".md")
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(make_markdown(report), encoding="utf-8")

        print(f"Files scanned: {files_scanned}")
        print(f"Credential-like findings: {len(credential_findings)}")
        print(f"Blocked/working paths: {len(blocked_paths)}")
        print(f"Raw/cache/binary files: {len(blocked_suffixes)}")
        print(f"Large files: {len(large_files)}")
        print(f"Report: {md_path.resolve()}")
        print(f"JSON:   {json_path.resolve()}")
        return 2 if credential_findings else 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
