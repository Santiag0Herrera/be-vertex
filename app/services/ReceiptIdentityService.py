from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Trx


REQUIRED_RECEIPT_IDENTITY_FIELDS = (
    "amount",
    "date",
)


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _value(document: Any, field: str):
    if isinstance(document, dict):
        return document.get(field)
    return getattr(document, field, None)


def _normalize_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        raw = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            parsed = datetime.combine(date.fromisoformat(raw[:10]), time.min)

    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.isoformat(timespec="seconds")


def _amount_in_cents(value: Any) -> int:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("amount is invalid") from exc
    if amount <= 0:
        raise ValueError("amount must be greater than zero")
    return int(amount * 100)


def missing_receipt_identity_fields(document: Any) -> list[str]:
    missing = []
    for field in REQUIRED_RECEIPT_IDENTITY_FIELDS:
        value = _value(document, field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def build_receipt_fingerprint(document: Any) -> str:
    missing = missing_receipt_identity_fields(document)
    if missing:
        raise ValueError(
            "Missing required receipt identity fields: " + ", ".join(missing)
        )

    payload = {
        "version": 2,
        "amount_cents": _amount_in_cents(_value(document, "amount")),
        "transaction_datetime": _normalize_datetime(_value(document, "date")),
    }

    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def find_duplicate_receipt(
    db: Session,
    *,
    entity_id: int,
    content_sha256: str | None,
    receipt_fingerprint: str | None,
    exclude_id: int | None = None,
) -> tuple[Trx | None, list[str]]:
    conditions = []
    normalized_file_hash = str(content_sha256 or "").strip().lower()
    normalized_receipt_fingerprint = str(receipt_fingerprint or "").strip().lower()
    if normalized_file_hash:
        conditions.append(Trx.file_sha256 == normalized_file_hash)
    if normalized_receipt_fingerprint:
        conditions.append(Trx.receipt_fingerprint == normalized_receipt_fingerprint)
    if not conditions:
        return None, []

    query = db.query(Trx).filter(Trx.entity_id == entity_id, or_(*conditions))
    if exclude_id is not None:
        query = query.filter(Trx.id != exclude_id)
    duplicate = query.order_by(Trx.creation_date.asc(), Trx.id.asc()).first()
    if duplicate is None:
        return None, []

    matched_by = []
    if normalized_file_hash and duplicate.file_sha256 == normalized_file_hash:
        matched_by.append("file_sha256")
    if (
        normalized_receipt_fingerprint
        and duplicate.receipt_fingerprint == normalized_receipt_fingerprint
    ):
        matched_by.append("receipt_fingerprint")
    return duplicate, matched_by


def duplicate_payload(duplicate: Trx, matched_by: list[str]) -> dict:
    duplicate_date = duplicate.date
    return {
        "code": "duplicate_receipt",
        "duplicate_of": duplicate.source_trx_id or duplicate.trx_id,
        "duplicate_internal_id": duplicate.trx_id,
        "matched_by": matched_by,
        "document_name": duplicate.document_name,
        "amount": duplicate.amount,
        "date": duplicate_date.isoformat() if duplicate_date else None,
    }
