from __future__ import annotations

from datetime import datetime, time as dt_time
import re
from typing import Optional

from app.services.extractor.normalizer import normalize_key


SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

SHORT_MONTHS = {
    "ene": 1, "jan": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4, "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8, "aug": 8,
    "sep": 9, "set": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12, "dec": 12,
}

DATE_FORMATS = [
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%y %H:%M:%S",
    "%d/%m/%y %H:%M",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
]


def extract_digits(raw: str) -> str:
    return re.sub(r"\D", "", str(raw or ""))


def extract_cbu(raw: str) -> Optional[str]:
    digits = extract_digits(raw)
    return digits if len(digits) == 22 else None


def parse_amount(raw: str) -> float:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("empty amount")

    value = value.upper()
    value = value.replace("ARS", "")
    value = value.replace("AR$", "")
    value = value.replace("USD", "")
    value = value.replace("U$S", "")
    value = value.replace("$", "")
    value = re.sub(r"\s+", "", value)

    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(".", "").replace(",", ".")
    elif value.count(".") > 1:
        value = value.replace(".", "")

    return float(value)


def parse_date(raw: str) -> datetime:
    if raw is None:
        raise ValueError("date is None")

    value = str(raw).strip().lower()
    value = re.sub(r"\s+", " ", value)

    long_match = re.search(
        r"(\d{1,2}) de ([a-záéíóú]+) de (\d{4})(?:\s*(?:-|a|a las|las)?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?)?",
        value,
    )
    if long_match:
        day = int(long_match.group(1))
        month = SPANISH_MONTHS.get(normalize_key(long_match.group(2)))
        year = int(long_match.group(3))
        hour = int(long_match.group(4) or 0)
        minute = int(long_match.group(5) or 0)
        second = int(long_match.group(6) or 0)

        if month:
            return datetime(year, month, day, hour, minute, second)

    short_match = re.search(
        r"(\d{1,2})[/-]([a-záéíóú]{3,})[/-](\d{2,4})(?:\s*[-]?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*h?s?)?",
        value,
    )
    if short_match:
        day = int(short_match.group(1))
        month = SHORT_MONTHS.get(normalize_key(short_match.group(2))[:3])
        year = int(short_match.group(3))
        hour = int(short_match.group(4) or 0)
        minute = int(short_match.group(5) or 0)
        second = int(short_match.group(6) or 0)

        if year < 100:
            year += 2000
        if month:
            return datetime(year, month, day, hour, minute, second)

    cleaned = re.sub(r"(lunes|martes|miercoles|miércoles|jueves|viernes|sabado|sábado|domingo),?", "", value)
    cleaned = re.sub(r"\ba las\b", "", cleaned)
    cleaned = re.sub(r"\bhs?\b", "", cleaned)
    cleaned = cleaned.strip()

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(cleaned)
    except Exception as exc:
        raise ValueError(f"Unsupported date format: '{raw}'") from exc


def parse_time(raw: str) -> dt_time:
    if raw is None:
        raise ValueError("time is None")

    value = str(raw).strip().lower()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\bhs?\b", "", value).strip()
    value = value.replace(".", "")

    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p"):
        try:
            return datetime.strptime(value.upper(), fmt).time()
        except ValueError:
            continue

    raise ValueError(f"Unsupported time format: '{raw}'")
