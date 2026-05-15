from __future__ import annotations

from typing import Any, Dict, List

from pydantic import ValidationError

from app.schemas.transactions import DocumentRequest
from app.services.extractor.aliases import KEY_ALIASES
from app.services.extractor.heuristics import is_wallet_document
from app.services.extractor.models import DocumentExtractResponse, ExtractedField, ParseIssue
from app.services.extractor.normalizer import clean_value, normalize_key
from app.services.extractor.parsers import extract_cbu, extract_digits, parse_amount, parse_date, parse_time
from app.services.extractor.scoring import extract_semantic_candidates


REQUIRED_FOR_DOCUMENT = {
    "amount",
    "trx_id",
    "emisor_name",
    "emisor_cuit",
    "receptor_name",
    "receptor_cuit",
    "date",
}


def build_document_response(fields: List[ExtractedField]) -> DocumentExtractResponse:
    normalized = extract_semantic_candidates(fields)
    wallet = is_wallet_document(fields)

    for field in fields:
        key = normalize_key(field.key)
        alias = KEY_ALIASES.get(key)
        if alias and alias not in normalized and field.value:
            normalized[alias] = clean_value(field.value)

    partial: Dict[str, Any] = {}
    missing: List[str] = []
    errors: List[ParseIssue] = []

    assign_amount(normalized, partial, missing, errors)
    assign_raw_field(normalized, partial, missing, "trx_id")
    assign_raw_field(normalized, partial, missing, "emisor_name")
    assign_digits_field(normalized, partial, missing, "emisor_cuit")
    assign_cbu_field(normalized, partial, "emisor_cbu")
    assign_raw_field(normalized, partial, missing, "receptor_name")
    assign_digits_field(normalized, partial, missing, "receptor_cuit")
    assign_cbu_field(normalized, partial, "receptor_cbu")
    assign_wallet_fields(normalized, partial)
    assign_date(normalized, partial, missing, errors)

    if wallet:
        missing = [
            field for field in missing
            if field not in {"emisor_name", "receptor_name", "receptor_cuit"}
        ]

    if not REQUIRED_FOR_DOCUMENT.issubset(partial.keys()):
        return DocumentExtractResponse(
            ok=False,
            document=None,
            partial=partial,
            missing=missing,
            errors=errors,
            raw_fields=fields,
        )

    try:
        document_payload = {
            key: value
            for key, value in partial.items()
            if key in DocumentRequest.model_fields
        }
        document = DocumentRequest(**document_payload)
    except ValidationError as exc:
        errors.append(ParseIssue(field="document", message=str(exc)))
        return DocumentExtractResponse(
            ok=False,
            document=None,
            partial=partial,
            missing=missing,
            errors=errors,
            raw_fields=fields,
        )

    return DocumentExtractResponse(
        ok=True,
        document=document,
        partial=partial,
        missing=missing,
        errors=errors,
        raw_fields=fields,
    )


def assign_amount(normalized: Dict[str, str], partial: Dict[str, Any], missing: List[str], errors: List[ParseIssue]) -> None:
    raw_amount = normalized.get("amount")
    if not raw_amount:
        missing.append("amount")
        return

    try:
        partial["amount"] = parse_amount(raw_amount)
    except Exception as exc:
        errors.append(ParseIssue(field="amount", message=f"Invalid amount '{raw_amount}': {exc}"))


def assign_raw_field(normalized: Dict[str, str], partial: Dict[str, Any], missing: List[str], field_name: str) -> None:
    value = normalized.get(field_name)
    if value:
        partial[field_name] = value
    else:
        missing.append(field_name)


def assign_digits_field(normalized: Dict[str, str], partial: Dict[str, Any], missing: List[str], field_name: str) -> None:
    value = normalized.get(field_name)
    if value:
        partial[field_name] = extract_digits(value)
    else:
        missing.append(field_name)


def assign_cbu_field(normalized: Dict[str, str], partial: Dict[str, Any], field_name: str) -> None:
    value = normalized.get(field_name)
    if value:
        partial[field_name] = extract_cbu(value)


def assign_wallet_fields(normalized: Dict[str, str], partial: Dict[str, Any]) -> None:
    wallet_cvu = normalized.get("wallet_cvu")
    if wallet_cvu:
        partial["wallet_cvu"] = extract_digits(wallet_cvu)

    wallet_cuit = normalized.get("wallet_cuit")
    if wallet_cuit:
        partial["wallet_cuit"] = extract_digits(wallet_cuit)


def assign_date(normalized: Dict[str, str], partial: Dict[str, Any], missing: List[str], errors: List[ParseIssue]) -> None:
    raw_date = normalized.get("date")
    raw_time = normalized.get("time")

    if not raw_date:
        missing.append("date")
        return

    try:
        parsed_date = parse_date(raw_date)

        if raw_time and parsed_date.hour == 0 and parsed_date.minute == 0 and parsed_date.second == 0:
            try:
                parsed_time = parse_time(raw_time)
                parsed_date = parsed_date.replace(
                    hour=parsed_time.hour,
                    minute=parsed_time.minute,
                    second=parsed_time.second,
                )
            except Exception:
                pass

        partial["date"] = parsed_date
    except Exception as exc:
        errors.append(ParseIssue(field="date", message=f"Invalid date '{raw_date}': {exc}"))
