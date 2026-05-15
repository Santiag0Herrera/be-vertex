from __future__ import annotations

import re
from typing import Any, Dict, List

from app.services.extractor.models import ExtractedField
from app.services.extractor.patterns import AMOUNT_PATTERNS, CBU_OR_CVU_REGEX, CUIT_REGEX


def index_blocks_by_id(blocks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {block["Id"]: block for block in blocks if "Id" in block}


def get_text_for_block(block: Dict[str, Any], blocks_by_id: Dict[str, Dict[str, Any]]) -> str:
    if block.get("BlockType") in ("LINE", "WORD"):
        return block.get("Text", "").strip()

    text_parts: List[str] = []

    for relationship in block.get("Relationships", []) or []:
        if relationship.get("Type") != "CHILD":
            continue

        for child_id in relationship.get("Ids", []) or []:
            child = blocks_by_id.get(child_id)
            if not child:
                continue

            if child.get("BlockType") == "WORD":
                text_parts.append(child.get("Text", ""))

            if child.get("BlockType") == "SELECTION_ELEMENT" and child.get("SelectionStatus") == "SELECTED":
                text_parts.append("[X]")

    return " ".join(part for part in text_parts if part).strip()


def extract_kv_pairs_from_forms(response: Dict[str, Any]) -> List[ExtractedField]:
    blocks = response.get("Blocks", []) or []
    if not blocks:
        return []

    blocks_by_id = index_blocks_by_id(blocks)
    key_to_value_id: Dict[str, str] = {}

    for block in blocks:
        if block.get("BlockType") != "KEY_VALUE_SET":
            continue
        if "KEY" not in (block.get("EntityTypes", []) or []):
            continue

        for relationship in block.get("Relationships", []) or []:
            if relationship.get("Type") == "VALUE" and relationship.get("Ids"):
                key_to_value_id[block["Id"]] = relationship["Ids"][0]
                break

    fields: List[ExtractedField] = []

    for key_id, value_id in key_to_value_id.items():
        key_block = blocks_by_id.get(key_id)
        value_block = blocks_by_id.get(value_id)
        if not key_block or not value_block:
            continue

        key_text = get_text_for_block(key_block, blocks_by_id)
        value_text = get_text_for_block(value_block, blocks_by_id)

        if not key_text or not value_text:
            continue

        confidence = value_block.get("Confidence")
        fields.append(
            ExtractedField(
                key=key_text,
                value=value_text,
                confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
            )
        )

    return dedup_fields(fields)


def extract_pairs_from_lines(response: Dict[str, Any]) -> List[ExtractedField]:
    blocks = response.get("Blocks", []) or []
    lines = [
        re.sub(r"\s+", " ", block["Text"]).strip()
        for block in blocks
        if block.get("BlockType") == "LINE" and block.get("Text")
    ]

    fields: List[ExtractedField] = []

    for text in lines:
        if ":" in text:
            left, right = text.split(":", 1)
            key = clean_pair_part(left)
            value = clean_pair_part(right)
            if key and value:
                fields.append(ExtractedField(key=key, value=value))
                continue

        for separator in (" - ", " – ", " — ", " = "):
            if separator not in text:
                continue

            left, right = text.split(separator, 1)
            key = clean_pair_part(left)
            value = clean_pair_part(right)

            if key and value and not key.isdigit():
                fields.append(ExtractedField(key=key, value=value))
                break

    index = 0
    while index < len(lines) - 1:
        current = lines[index]
        next_line = lines[index + 1]

        if current.endswith(":") and not next_line.endswith(":"):
            key = clean_pair_part(current[:-1])
            value = clean_pair_part(next_line)

            if key and value:
                fields.append(ExtractedField(key=key, value=value))
                index += 2
                continue

        index += 1

    return dedup_fields(fields)


def extract_fields_from_wallet_lines(response: Dict[str, Any]) -> List[ExtractedField]:
    blocks = response.get("Blocks", []) or []
    lines = [block.get("Text", "").strip() for block in blocks if block.get("BlockType") == "LINE"]

    fields: List[ExtractedField] = []

    datetime_long = re.compile(
        r"\d{1,2} de [a-záéíóú]+ de \d{4}(?:\s*-\s*\d{1,2}:\d{2})?",
        re.IGNORECASE,
    )
    datetime_short_month = re.compile(
        r"\d{1,2}[/-][A-Za-záéíóú]{3,}[/-]\d{2,4}(?:\s*-\s*\d{1,2}:\d{2}(?::\d{2})?\s*h?)?",
        re.IGNORECASE,
    )

    for line in lines:
        normalized_line = line.lower()

        for amount_pattern in AMOUNT_PATTERNS:
            amount_match = amount_pattern.search(line)
            if amount_match:
                fields.append(ExtractedField(key="monto", value=amount_match.group()))
                break

        date_match = datetime_long.search(line) or datetime_short_month.search(line)
        if date_match:
            fields.append(ExtractedField(key="fecha", value=date_match.group()))

        if "cvu" in normalized_line:
            cvu_match = CBU_OR_CVU_REGEX.search(line)
            fields.append(ExtractedField(key="cvu", value=cvu_match.group() if cvu_match else line))

        if "cuit" in normalized_line or "cuil" in normalized_line or "dni" in normalized_line:
            cuit_match = CUIT_REGEX.search(line)
            if cuit_match:
                fields.append(ExtractedField(key="cuit cuil", value=cuit_match.group()))

    return dedup_fields(fields)


def merge_and_dedup_fields(*groups: List[ExtractedField]) -> List[ExtractedField]:
    merged: List[ExtractedField] = []

    for group in groups:
        merged.extend(group)

    return dedup_fields(merged)


def dedup_fields(fields: List[ExtractedField]) -> List[ExtractedField]:
    deduped: List[ExtractedField] = []
    seen: set[tuple[str, str]] = set()

    for field in fields:
        key = re.sub(r"\s+", " ", field.key or "").strip().lower()
        value = re.sub(r"\s+", " ", field.value or "").strip().lower()
        identity = (key, value)

        if not key or not value or identity in seen:
            continue

        seen.add(identity)
        deduped.append(
            ExtractedField(
                key=field.key.strip(),
                value=field.value.strip(),
                confidence=field.confidence,
            )
        )

    return deduped


def clean_pair_part(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(":- \t")
