"""Safe names for cross-platform folders/files.

CSV content may remain in Russian, but filesystem names should be stable on
Windows, macOS and Linux. The helpers below transliterate Cyrillic characters,
remove forbidden filesystem characters and keep names short enough for nested
exports.
"""
from __future__ import annotations

import re
import unicodedata

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
_TRANSLIT.update({k.upper(): v.capitalize() for k, v in list(_TRANSLIT.items())})

_RESERVED = {
    "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))
}


def transliterate(text: str) -> str:
    return "".join(_TRANSLIT.get(ch, ch) for ch in str(text or ""))


def safe_filename(text: object, default: str = "__MISSING__", max_len: int = 120, ext: str = "") -> str:
    """Return a portable file/folder name.

    The function is intentionally conservative: it removes diacritics, replaces
    spaces by underscores and rejects Windows-reserved characters/names.
    """
    raw = str(text or "").strip()
    if not raw:
        raw = default
    technical = raw.startswith("__") and raw.endswith("__")
    raw = transliterate(raw)
    raw = unicodedata.normalize("NFKD", raw)
    raw = raw.encode("ascii", "ignore").decode("ascii")
    raw = re.sub(r"[\\/:*?\"<>|]+", "_", raw)
    raw = re.sub(r"\s+", "_", raw)
    if not technical:
        raw = re.sub(r"_+", "_", raw)
    raw = raw.strip(" .") if technical else raw.strip(" ._")
    if not raw:
        raw = default
    if raw.upper() in _RESERVED:
        raw = f"_{raw}"
    ext = ext or ""
    if ext and not ext.startswith("."):
        ext = "." + ext
    max_body = max(1, max_len - len(ext))
    if len(raw) > max_body:
        raw = raw[:max_body].rstrip(" ._")
    return raw + ext


def safe_stem_from_path(path) -> str:
    from pathlib import Path
    return safe_filename(Path(path).stem, default="file", max_len=80)
