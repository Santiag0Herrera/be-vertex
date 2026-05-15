from __future__ import annotations

import re
import unicodedata


def normalize_key(key: str) -> str:
    if not key:
        return ""

    normalized = key.lower()
    normalized = unicodedata.normalize("NFD", normalized)
    normalized = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    normalized = re.sub(r"[_\-\/]+", " ", normalized)
    normalized = re.sub(r"[^\w\s]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)

    return normalized.strip()


def clean_value(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(":- \t")
