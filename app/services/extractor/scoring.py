from __future__ import annotations

from typing import Dict

from app.services.extractor.aliases import KEY_ALIASES
from app.services.extractor.heuristics import looks_like_value
from app.services.extractor.models import ExtractedField
from app.services.extractor.normalizer import clean_value, normalize_key
from app.services.extractor.patterns import AMOUNT_PATTERNS, CBU_OR_CVU_REGEX, CUIT_REGEX, DATE_TEXT_REGEX, TIME_TEXT_REGEX, TRX_REGEX


def extract_semantic_candidates(fields: list[ExtractedField]) -> Dict[str, str]:
    best: Dict[str, tuple[str, float]] = {}

    def consider(alias: str, value: str, score: float) -> None:
        cleaned = clean_value(value)
        if not cleaned:
            return

        current = best.get(alias)
        if current is None or score > current[1]:
            best[alias] = (cleaned, score)

    for field in fields:
        key_norm = normalize_key(field.key)
        value = clean_value(field.value)
        score = field_score(field)

        alias = KEY_ALIASES.get(key_norm)
        if alias:
            consider(alias, value, score + 15)

        amount_match = first_amount_match(value)
        if amount_match:
            consider("amount", amount_match, score + 4)

        cuit_match = CUIT_REGEX.search(value)
        if cuit_match:
            target = infer_document_target(key_norm)
            consider(target, cuit_match.group(), score + 3)

        cbu_match = CBU_OR_CVU_REGEX.search(value)
        if cbu_match:
            target = infer_account_target(key_norm)
            consider(target, cbu_match.group(), score + 3)

        if DATE_TEXT_REGEX.search(value):
            date_score = score + (5 if TIME_TEXT_REGEX.search(value) else 0)
            consider("date", value, date_score)

        time_match = TIME_TEXT_REGEX.search(value)
        if time_match:
            consider("time", time_match.group(), score)

        if is_transaction_key(key_norm):
            trx_match = TRX_REGEX.search(value)
            consider("trx_id", trx_match.group() if trx_match else value, score + 2)

    return {key: value for key, (value, _) in best.items()}


def field_score(field: ExtractedField) -> float:
    score = float(field.confidence or 0)
    key_norm = normalize_key(field.key)

    if key_norm in KEY_ALIASES:
        score += 10
    if len(clean_value(field.value)) >= 4:
        score += 1
    if looks_like_value(field.value):
        score += 2

    return score


def first_amount_match(value: str) -> str | None:
    for pattern in AMOUNT_PATTERNS:
        match = pattern.search(value)
        if match:
            return match.group()
    return None


def infer_document_target(key_norm: str) -> str:
    if any(token in key_norm for token in ("emisor", "origin", "ordenante", "remitente")):
        return "emisor_cuit"
    if any(token in key_norm for token in ("receptor", "destinat", "benefici", "destino")):
        return "receptor_cuit"
    return "receptor_cuit"


def infer_account_target(key_norm: str) -> str:
    if "cvu" in key_norm and not any(token in key_norm for token in ("destino", "receptor", "benefici")):
        return "wallet_cvu"
    if any(token in key_norm for token in ("emisor", "origin", "ordenante", "remitente")):
        return "emisor_cbu"
    if any(token in key_norm for token in ("receptor", "destinat", "benefici", "destino")):
        return "receptor_cbu"
    return "receptor_cbu"


def is_transaction_key(key_norm: str) -> bool:
    return any(token in key_norm for token in ("operacion", "transaccion", "referencia", "comprobante", "ticket", "voucher"))
