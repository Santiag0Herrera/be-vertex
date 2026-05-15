from __future__ import annotations

import re


AMOUNT_PATTERNS = [
    re.compile(r"(?:ar\$|ars|\$|u\$s|usd)?\s*[+-]?\d{1,3}(?:[.\s]\d{3})+(?:,\d{2})", re.IGNORECASE),
    re.compile(r"(?:ar\$|ars|\$|u\$s|usd)?\s*[+-]?\d{1,3}(?:,\d{3})+(?:\.\d{2})", re.IGNORECASE),
    re.compile(r"(?:ar\$|ars|\$|u\$s|usd)?\s*[+-]?\d+(?:[.,]\d{2})", re.IGNORECASE),
    re.compile(r"(?:ar\$|ars|\$|u\$s|usd)\s*[+-]?\d+", re.IGNORECASE),
]

CUIT_REGEX = re.compile(r"\b\d{2}[-\s]?\d{8}[-\s]?\d\b")
CBU_OR_CVU_REGEX = re.compile(r"\b\d{22}\b")
TRX_REGEX = re.compile(r"\b[A-Z0-9][A-Z0-9\-]{5,}\b", re.IGNORECASE)

DATE_TEXT_REGEX = re.compile(
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|\d{4}-\d{1,2}-\d{1,2}"
    r"|\d{1,2}\s+de\s+[a-záéíóú]+\s+de\s+\d{4}"
    r"|\d{1,2}[/-][a-záéíóú]{3,}[/-]\d{2,4}",
    re.IGNORECASE,
)

TIME_TEXT_REGEX = re.compile(
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:\s*[ap]\.?m\.?)?\b",
    re.IGNORECASE,
)
