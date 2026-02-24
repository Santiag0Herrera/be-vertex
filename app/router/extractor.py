from __future__ import annotations

from datetime import date, datetime
import os
import re
import unicodedata
from typing import Annotated, Any, Dict, List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.services.auth_service import get_current_user
from app.schemas.transactions import DocumentRequest


# ---------------------------
# Normalización de keys
# ---------------------------
def normalize_key(key: str) -> str:
    if not key:
        return ""
    k = key.lower()
    k = unicodedata.normalize("NFD", k)
    k = "".join(c for c in k if unicodedata.category(c) != "Mn")  # saca acentos
    k = re.sub(r"[_\-\/]+", " ", k)          # _, -, / -> espacio
    k = re.sub(r"[^\w\s]", "", k)            # saca puntuación
    k = re.sub(r"\s+", " ", k).strip()       # espacios dobles
    return k


# ---------------------------
# Aliases
# ---------------------------
KEY_ALIASES_RAW = {
    "importe": "amount",
    "monto": "amount",
    "monto total": "amount",
    "numero de transaccion": "trx_id",
    "nro operacion": "trx_id",
    "operacion": "trx_id",
    "referencia": "trx_id",
    "nombre originante": "emisor_name",
    "ordenante": "emisor_name",
    "remitente": "emisor_name",
    "documento originante": "emisor_cuit",
    "cuit originante": "emisor_cuit",
    "dni originante": "emisor_cuit",
    "cuenta origen": "emisor_cbu",
    "cbu origen": "emisor_cbu",
    "cvu origen": "emisor_cbu",
    "alias origen": "emisor_cbu",
    "nombre destinatario": "receptor_name",
    "beneficiario": "receptor_name",
    "documento destinatario": "receptor_cuit",
    "cuit destinatario": "receptor_cuit",
    "dni destinatario": "receptor_cuit",
    "cuenta destino": "receptor_cbu",
    "cbu destino": "receptor_cbu",
    "cvu destino": "receptor_cbu",
    "alias destino": "receptor_cbu",
    "fecha y hora": "date",
    "fecha operacion": "date",
    "fecha": "date",
    "importe total": "amount",
    "valor": "amount",
    "total": "amount",
    "id operacion": "trx_id",
    "id transaccion": "trx_id",
    "numero operacion": "trx_id",
    "comprobante": "trx_id",
    "numero comprobante": "trx_id",
    "pagador": "emisor_name",
    "deudor": "emisor_name",
    "girador": "emisor_name",
    "acreedor": "emisor_name",
    "cuil originante": "emisor_cuit",
    "documento remitente": "emisor_cuit",
    "cuil remitente": "emisor_cuit",
    "banco origen": "emisor_cbu",
    "cuenta origen cbu": "emisor_cbu",
    "cta origen": "emisor_cbu",
    "acreedor": "receptor_name",
    "pagador": "receptor_name",
    "destinatario final": "receptor_name",
    "receptor": "receptor_name",
    "cuil destinatario": "receptor_cuit",
    "documento beneficiario": "receptor_cuit",
    "cuil beneficiario": "receptor_cuit",
    "documento acreedor": "receptor_cuit",
    "banco destino": "receptor_cbu",
    "cuenta destino cbu": "receptor_cbu",
    "cta destino": "receptor_cbu",
    "cuenta credito": "receptor_cbu",
    "fecha hora operacion": "date",
    "fecha hora": "date",
    "timestamp": "date",
    "hora operacion": "date",
    "fecha procesamiento": "date",
    "fecha transaccion": "date",
    "fecha movimiento": "date",
    "fecha efectiva": "date",
    "fecha liquidacion": "date",
    "fecha contable": "date",
    "dinero": "amount",
    "suma": "amount",
    "cantidad": "amount",
    "precio": "amount",
    "costo": "amount",
    "gasto": "amount",
    "deposito": "amount",
    "extraccion": "amount",
    "retiro": "amount",
    "transferencia": "amount",
    "pago": "amount",
    "cobro": "amount",
    "saldo": "amount",
    "debe": "amount",
    "haber": "amount",
    "codigo operacion": "trx_id",
    "codigo transaccion": "trx_id",
    "codigo movimiento": "trx_id",
    "referencia operacion": "trx_id",
    "referencia transaccion": "trx_id",
    "numero referencia": "trx_id",
    "codigo comprobante": "trx_id",
    "ticket": "trx_id",
    "recibo": "trx_id",
    "voucher": "trx_id",
    "comprobante numero": "trx_id",
    "referencia numero": "trx_id",
    "transaccion id": "trx_id",
    "transaccion numero": "trx_id",
    "emisor": "emisor_name",
    "origen": "emisor_name",
    "remitente nombre": "emisor_name",
    "nombre remitente": "emisor_name",
    "cliente origen": "emisor_name",
    "solicitante": "emisor_name",
    "oferente": "emisor_name",
    "cuit emisor": "emisor_cuit",
    "dni emisor": "emisor_cuit",
    "cuil emisor": "emisor_cuit",
    "documento emisor": "emisor_cuit",
    "numero documento emisor": "emisor_cuit",
    "numero dni emisor": "emisor_cuit",
    "numero cuit emisor": "emisor_cuit",
    "numero cuil emisor": "emisor_cuit",
    "rut origen": "emisor_cuit",
    "numero rut origen": "emisor_cuit",
    "id documento origen": "emisor_cuit",
    "cbu emisor": "emisor_cbu",
    "cvu emisor": "emisor_cbu",
    "alias emisor": "emisor_cbu",
    "cuenta emisor": "emisor_cbu",
    "numero cuenta emisor": "emisor_cbu",
    "banco emisor": "emisor_cbu",
    "numero banco emisor": "emisor_cbu",
    "iban origen": "emisor_cbu",
    "swift origen": "emisor_cbu",
    "cuenta corriente origen": "emisor_cbu",
    "caja ahorros origen": "emisor_cbu",
    "receptor final": "receptor_name",
    "destino": "receptor_name",
    "beneficiario nombre": "receptor_name",
    "nombre beneficiario": "receptor_name",
    "cliente destino": "receptor_name",
    "deudor nombre": "receptor_name",
    "nombre deudor": "receptor_name",
    "vendedor": "receptor_name",
    "proveedor": "receptor_name",
    "cuit receptor": "receptor_cuit",
    "dni receptor": "receptor_cuit",
    "cuil receptor": "receptor_cuit",
    "documento receptor": "receptor_cuit",
    "numero documento receptor": "receptor_cuit",
    "numero dni receptor": "receptor_cuit",
    "numero cuit receptor": "receptor_cuit",
    "numero cuil receptor": "receptor_cuit",
    "rut destino": "receptor_cuit",
    "numero rut destino": "receptor_cuit",
    "id documento destino": "receptor_cuit",
    "cbu receptor": "receptor_cbu",
    "cvu receptor": "receptor_cbu",
    "alias receptor": "receptor_cbu",
    "cuenta receptor": "receptor_cbu",
    "numero cuenta receptor": "receptor_cbu",
    "banco receptor": "receptor_cbu",
    "numero banco receptor": "receptor_cbu",
    "iban destino": "receptor_cbu",
    "swift destino": "receptor_cbu",
    "cuenta corriente destino": "receptor_cbu",
    "caja ahorros destino": "receptor_cbu",
    "numero de operacion de mercado pago": "trx_id",

    # --- Mercado Pago / billeteras ---
    "cvu": "wallet_cvu",
    "cuit cuil": "wallet_cuit",
    "cuitcuil": "wallet_cuit",
    "cuit": "wallet_cuit",
    "cuil": "wallet_cuit",
    "dni": "wallet_cuit",
    "documento": "wallet_cuit",
}

KEY_ALIASES = {normalize_key(k): v for k, v in KEY_ALIASES_RAW.items()}


# ---------------------------
# Models de respuesta
# ---------------------------
class ExtractedField(BaseModel):
    key: str
    value: str
    confidence: Optional[float] = None


class ParseIssue(BaseModel):
    field: str
    message: str


class DocumentExtractResponse(BaseModel):
    ok: bool
    document: Optional[DocumentRequest] = None
    partial: Dict[str, Any] = Field(default_factory=dict)
    missing: List[str] = Field(default_factory=list)
    errors: List[ParseIssue] = Field(default_factory=list)
    raw_fields: List[ExtractedField] = Field(default_factory=list)


user_dependency = Annotated[dict, Depends(get_current_user)]


# ---------------------------
# AWS Textract client
# ---------------------------
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
_textract = boto3.client(
    "textract",
    region_name=AWS_REGION,
    config=Config(
        retries={"max_attempts": 3, "mode": "standard"},
        connect_timeout=10,
        read_timeout=60,
    ),
)


# ---------------------------
# Helpers de parsing de texto
# ---------------------------
def extract_digits(raw: str) -> str:
    return re.sub(r"\D", "", str(raw or ""))


def extract_cbu(raw: str) -> Optional[str]:
    digits = extract_digits(raw)
    return digits if len(digits) == 22 else None


def parse_amount(raw: str) -> float:
    """
    Soporta cosas tipo:
    - "$ 1.234,56"
    - "1.234,56"
    - "1234.56"
    - "1,234.56" (a veces viene así)
    """
    s = str(raw or "").strip()
    if not s:
        raise ValueError("empty amount")

    s = s.replace("$", "").replace("ARS", "").replace("AR$", "").strip()
    s = re.sub(r"\s+", "", s)

    # Si tiene coma y punto, decidimos qué es decimal por la última aparición
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            # "1.234,56" => "." miles, "," decimal
            s = s.replace(".", "").replace(",", ".")
        else:
            # "1,234.56" => "," miles, "." decimal
            s = s.replace(",", "")
    else:
        # Si solo tiene coma, la tratamos como decimal
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        # Si solo tiene punto, lo dejamos como decimal (y removemos separadores raros)
        # no tocamos

    return float(s)


def parse_date(raw: str) -> date:
    """
    Intenta parsear formatos típicos que aparecen en comprobantes.
    Devuelve date (sin hora).
    """
    if raw is None:
        raise ValueError("date is None")

    s = str(raw).strip()
    s = re.sub(r"\s+", " ", s)

    patterns = [
        "%d/%m/%y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%y %H:%M",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%d/%m/%y",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ]

    for fmt in patterns:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass

    # Último intento con ISO flexible
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        raise ValueError(f"Unsupported date format: '{raw}'")


def is_wallet_document(fields: List[ExtractedField]) -> bool:
    """
    Heurística: si parece comprobante de billetera (Mercado Pago / CVU),
    relajamos los campos que suelen no venir como en transferencia bancaria.
    """
    key_text = " ".join(normalize_key(f.key) for f in fields if f.key)
    value_text = " ".join(normalize_key(str(f.value)) for f in fields if f.value)

    if "mercado pago" in key_text or "mercado pago" in value_text:
        return True

    wallet_terms = {"cvu", "cuit cuil", "cuitcuil"}
    has_wallet_terms = any(t in key_text for t in wallet_terms)

    bank_terms = {"cbu", "transferencia", "comprobante", "cbu origen", "cbu destino"}
    looks_bank = any(t in key_text for t in bank_terms)

    return has_wallet_terms and not looks_bank


# ---------------------------
# Textract parsing
# ---------------------------
def _index_blocks_by_id(blocks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {b["Id"]: b for b in blocks if "Id" in b}


def _get_text_for_block(block: Dict[str, Any], blocks_by_id: Dict[str, Dict[str, Any]]) -> str:
    if block.get("BlockType") in ("LINE", "WORD"):
        return block.get("Text", "").strip()

    text_parts: List[str] = []
    for rel in block.get("Relationships", []) or []:
        if rel.get("Type") == "CHILD":
            for cid in rel.get("Ids", []) or []:
                child = blocks_by_id.get(cid)
                if not child:
                    continue
                if child.get("BlockType") == "WORD":
                    text_parts.append(child.get("Text", ""))
                if child.get("BlockType") == "SELECTION_ELEMENT":
                    if child.get("SelectionStatus") == "SELECTED":
                        text_parts.append("[X]")
    return " ".join([t for t in text_parts if t]).strip()


def _extract_kv_pairs_from_forms(response: Dict[str, Any]) -> List[ExtractedField]:
    blocks = response.get("Blocks", []) or []
    if not blocks:
        return []

    blocks_by_id = _index_blocks_by_id(blocks)

    key_map: Dict[str, str] = {}

    for b in blocks:
        if b.get("BlockType") != "KEY_VALUE_SET":
            continue
        entity_types = b.get("EntityTypes", []) or []
        if "KEY" not in entity_types:
            continue

        key_id = b["Id"]
        value_id = None

        for rel in b.get("Relationships", []) or []:
            if rel.get("Type") == "VALUE":
                ids = rel.get("Ids", []) or []
                if ids:
                    value_id = ids[0]
                    break

        if value_id:
            key_map[key_id] = value_id

    results: List[ExtractedField] = []
    for key_block_id, value_block_id in key_map.items():
        key_block = blocks_by_id.get(key_block_id)
        value_block = blocks_by_id.get(value_block_id)
        if not key_block or not value_block:
            continue

        key_text = _get_text_for_block(key_block, blocks_by_id)
        value_text = _get_text_for_block(value_block, blocks_by_id)

        if key_text and value_text:
            conf = None
            if isinstance(value_block.get("Confidence"), (int, float)):
                conf = float(value_block["Confidence"])
            results.append(ExtractedField(key=key_text, value=value_text, confidence=conf))

    # Dedup por key
    seen = set()
    deduped: List[ExtractedField] = []
    for f in results:
        k = f.key.strip().lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append(f)

    return deduped


def _extract_pairs_from_lines_by_colon(response: Dict[str, Any]) -> List[ExtractedField]:
    blocks = response.get("Blocks", []) or []
    lines = [b for b in blocks if b.get("BlockType") == "LINE" and b.get("Text")]
    texts = [b["Text"].strip() for b in lines]

    results: List[ExtractedField] = []
    i = 0
    while i < len(texts) - 1:
        t = texts[i]
        if t.endswith(":"):
            key = t[:-1].strip()
            value = texts[i + 1].strip()
            if not value.endswith(":"):
                results.append(ExtractedField(key=key, value=value))
                i += 2
                continue
        i += 1

    for r in results:
        r.key = re.sub(r"\s+", " ", r.key).strip()
        r.value = re.sub(r"\s+", " ", r.value).strip()

    return results


# ---------------------------
# Builder tolerante (para FE)
# ---------------------------
def build_document_response(fields: List[ExtractedField]) -> DocumentExtractResponse:
    normalized: Dict[str, str] = {}
    for f in fields:
        key = normalize_key(f.key)
        alias = KEY_ALIASES.get(key)
        if alias and f.value:
            normalized[alias] = f.value.strip()

    partial: Dict[str, Any] = {}
    missing: List[str] = []
    errors: List[ParseIssue] = []

    # Wallet data
    wallet_cvu = normalized.get("wallet_cvu")
    if wallet_cvu:
        digits = extract_digits(wallet_cvu)
        partial["wallet_cvu"] = digits  # si querés validar len==22, hacelo acá

    wallet_cuit = normalized.get("wallet_cuit")
    if wallet_cuit:
        partial["wallet_cuit"] = extract_digits(wallet_cuit)

    # amount
    raw_amount = normalized.get("amount")
    if raw_amount:
        try:
            partial["amount"] = parse_amount(raw_amount)
        except Exception as e:
            errors.append(ParseIssue(field="amount", message=f"Invalid amount '{raw_amount}': {e}"))
    else:
        missing.append("amount")

    # trx_id
    trx_id = normalized.get("trx_id")
    if trx_id:
        partial["trx_id"] = trx_id
    else:
        missing.append("trx_id")

    # emisor
    emisor_name = normalized.get("emisor_name")
    if emisor_name:
        partial["emisor_name"] = emisor_name
    else:
        missing.append("emisor_name")

    emisor_cuit = normalized.get("emisor_cuit")
    if emisor_cuit:
        partial["emisor_cuit"] = extract_digits(emisor_cuit)
    else:
        missing.append("emisor_cuit")

    emisor_cbu = normalized.get("emisor_cbu")
    if emisor_cbu:
        partial["emisor_cbu"] = extract_cbu(emisor_cbu)

    # receptor
    receptor_name = normalized.get("receptor_name")
    if receptor_name:
        partial["receptor_name"] = receptor_name
    else:
        missing.append("receptor_name")

    receptor_cuit = normalized.get("receptor_cuit")
    if receptor_cuit:
        partial["receptor_cuit"] = extract_digits(receptor_cuit)
    else:
        missing.append("receptor_cuit")

    receptor_cbu = normalized.get("receptor_cbu")
    if receptor_cbu:
        partial["receptor_cbu"] = extract_cbu(receptor_cbu)

    # date
    raw_date = normalized.get("date")
    if raw_date:
        try:
            partial["date"] = parse_date(raw_date)
        except Exception as e:
            errors.append(ParseIssue(field="date", message=f"Invalid date '{raw_date}': {e}"))
    else:
        missing.append("date")

    # Relax rules for wallet docs
    wallet = is_wallet_document(fields)
    if wallet:
        missing = [m for m in missing if m not in {"emisor_name", "receptor_name", "receptor_cuit"}]

    REQUIRED_FOR_DOCUMENT = {"amount", "trx_id", "emisor_name", "emisor_cuit", "receptor_name", "receptor_cuit", "date"}
    has_all_required = REQUIRED_FOR_DOCUMENT.issubset(partial.keys())

    if not has_all_required:
        return DocumentExtractResponse(
            ok=False,
            document=None,
            partial=partial,
            missing=missing,
            errors=errors,
            raw_fields=fields,
        )

    # Validación final con tu schema
    doc_payload = {k: v for k, v in partial.items() if k in DocumentRequest.model_fields}
    doc = DocumentRequest(**doc_payload)

    return DocumentExtractResponse(
        ok=True,
        document=doc,
        partial=partial,
        missing=missing,
        errors=errors,
        raw_fields=fields,
    )


# ---------------------------
# Router / endpoint
# ---------------------------
router = APIRouter(prefix="/extractor", tags=["textract"])


@router.post("/aws-extract", response_model=DocumentExtractResponse)
async def analyze_document(
    user: user_dependency,
    file: UploadFile = File(...),
) -> DocumentExtractResponse:
    # Validaciones
    if not file.content_type:
        raise HTTPException(status_code=400, detail="Missing content_type")

    allowed = {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/tiff",
    }
    if file.content_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported content_type '{file.content_type}'. Allowed: {sorted(allowed)}",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="File too large for synchronous Textract (max 10MB)",
        )

    # Llamada a Textract
    try:
        aws_resp = _textract.analyze_document(
            Document={"Bytes": data},
            FeatureTypes=["FORMS"],
        )
    except (BotoCoreError, ClientError) as e:
        raise HTTPException(status_code=502, detail=f"Textract error: {str(e)}")

    # Parseo
    fields = _extract_kv_pairs_from_forms(aws_resp)
    if not fields:
        fields = _extract_pairs_from_lines_by_colon(aws_resp)

    if not fields:
        return DocumentExtractResponse(
            ok=False,
            document=None,
            partial={},
            missing=[],
            errors=[ParseIssue(field="*", message="No fields extracted from Textract response")],
            raw_fields=[],
        )

    # Construcción tolerante (no rompe FE)
    return build_document_response(fields)