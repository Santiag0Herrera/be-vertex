from __future__ import annotations

import os
import re
from typing import Optional

from app.services.extractor.models import ExtractedField
from app.services.extractor.normalizer import normalize_key
from app.services.extractor.patterns import AMOUNT_PATTERNS, CBU_OR_CVU_REGEX, CUIT_REGEX, DATE_TEXT_REGEX, TIME_TEXT_REGEX


def looks_like_value(text: str) -> bool:
    value = str(text or "").lower()

    if any(pattern.search(value) for pattern in AMOUNT_PATTERNS):
        return True
    if CUIT_REGEX.search(value) or CBU_OR_CVU_REGEX.search(value):
        return True
    if DATE_TEXT_REGEX.search(value) or TIME_TEXT_REGEX.search(value):
        return True

    return False


def is_wallet_document(fields: list[ExtractedField]) -> bool:
    keys = {normalize_key(field.key) for field in fields if field.key}
    values = {normalize_key(str(field.value)) for field in fields if field.value}
    all_text = " ".join([*keys, *values])

    if "mercado pago" in all_text:
        return True

    wallet_terms = {"cvu", "cuit cuil", "cuitcuil", "alias cvu"}
    bank_terms = {"cbu", "cbu origen", "cbu destino", "cuenta origen", "cuenta destino"}

    has_wallet_term = bool(keys.intersection(wallet_terms)) or any("cvu" == key for key in keys)
    has_bank_term = bool(keys.intersection(bank_terms))

    return has_wallet_term and not has_bank_term


def extract_datetime_from_filename(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None

    stem = os.path.splitext(os.path.basename(filename))[0].lower()

    match = re.search(r"(\d{1,2})-(\d{1,2})-(\d{2,4})[_\s-](\d{1,2})-(\d{2})(?:-(\d{2}))?", stem)
    if match:
        day, month, year, hour, minute, second = match.groups()
        full_year = int(year) + 2000 if int(year) < 100 else int(year)
        return f"{int(day):02d}/{int(month):02d}/{full_year:04d} {int(hour):02d}:{int(minute):02d}:{int(second or 0):02d}"

    match = re.search(r"(\d{4})-(\d{2})-(\d{2})t(\d{2})(\d{2})(\d{2})", stem)
    if match:
        year, month, day, hour, minute, second = match.groups()
        return f"{int(day):02d}/{int(month):02d}/{int(year):04d} {int(hour):02d}:{int(minute):02d}:{int(second):02d}"

    match = re.search(r"(?<!\d)(\d{2})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})(?!\d)", stem)
    if match:
        year, month, day, hour, minute, second = match.groups()
        return f"{int(day):02d}/{int(month):02d}/{2000 + int(year):04d} {int(hour):02d}:{int(minute):02d}:{int(second):02d}"

    return None
