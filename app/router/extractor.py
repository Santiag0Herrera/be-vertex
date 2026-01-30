from __future__ import annotations
from datetime import date, datetime
import os
import re
from typing import Annotated, Any, Dict, List, Optional
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from app.services.auth_service import get_current_user
from app.schemas.transactions import DocumentRequest
from pydantic import ValidationError

import re
import unicodedata

def normalize_key(key: str) -> str:
    """
    Strong normalization for OCR / Textract keys.
    - lowercases
    - removes accents (áéíóú → aeiou)
    - removes punctuation (:.-_/)
    - collapses multiple spaces
    - trims
    """
    if not key:
        return ""

    # Lowercase
    k = key.lower()

    # Remove accents (NFD unicode normalization)
    k = unicodedata.normalize("NFD", k)
    k = "".join(c for c in k if unicodedata.category(c) != "Mn")

    # Replace separators with spaces
    k = re.sub(r"[_\-\/]+", " ", k)

    # Remove punctuation
    k = re.sub(r"[^\w\s]", "", k)

    # Collapse multiple spaces
    k = re.sub(r"\s+", " ", k)

    return k.strip()

class ParseIssue(BaseModel):
    field: str
    message: str

class DocumentExtractResponse(BaseModel):
    ok: bool
    document: Optional[DocumentRequest] = None   # cuando valida completo
    partial: Dict[str, Any] = Field(default_factory=dict)  # lo que haya salido
    missing: List[str] = Field(default_factory=list)
    errors: List[ParseIssue] = Field(default_factory=list)
    raw_fields: List[ExtractedField] = Field(default_factory=list)  # opcional, por si querés debug

user_dependency = Annotated[dict, Depends(get_current_user)]

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

class ExtractedField(BaseModel):
    key: str
    value: str
    confidence: Optional[float] = None


class TextractParsedResponse(BaseModel):
    # Campos sueltos (KV) normalizados
    fields: List[ExtractedField] = Field(default_factory=list)

    # Para debug / trazabilidad
    document_pages: Optional[int] = None
    raw_request_id: Optional[str] = None

def _index_blocks_by_id(blocks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {b["Id"]: b for b in blocks if "Id" in b}


def _get_text_for_block(block: Dict[str, Any], blocks_by_id: Dict[str, Dict[str, Any]]) -> str:
    """
    Para KEY_VALUE_SET, KEY, VALUE, LINE, WORD.
    """
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
                # Selection elements (checkbox) si aparece
                if child.get("BlockType") == "SELECTION_ELEMENT":
                    if child.get("SelectionStatus") == "SELECTED":
                        text_parts.append("[X]")
    return " ".join([t for t in text_parts if t]).strip()


def _extract_kv_pairs_from_forms(response: Dict[str, Any]) -> List[ExtractedField]:
    """
    Parsea pares Key/Value reales de AnalyzeDocument(FORMS).
    """
    blocks = response.get("Blocks", []) or []
    if not blocks:
        return []

    blocks_by_id = _index_blocks_by_id(blocks)

    # Map KEY block -> VALUE block ids
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
            # Confidence: Textract suele traer confidence por block
            conf = None
            if isinstance(value_block.get("Confidence"), (int, float)):
                conf = float(value_block["Confidence"])
            results.append(ExtractedField(key=key_text, value=value_text, confidence=conf))

    # Deduplicar claves repetidas (conserva la primera)
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
    """
    Fallback: si solo tenés LINEs (como tu ejemplo), arma pares cuando ve 'Algo:' y el próximo LINE parece el valor.
    """
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
            # Evitar casos donde el "valor" también sea una key
            if not value.endswith(":"):
                results.append(ExtractedField(key=key, value=value))
                i += 2
                continue
        i += 1

    # Mini-normalización (opcional): limpiar dobles espacios
    for r in results:
        r.key = re.sub(r"\s+", " ", r.key).strip()
        r.value = re.sub(r"\s+", " ", r.value).strip()

    return results


def parse_textract_response(response: Dict[str, Any]) -> DocumentRequest:
    fields = _extract_kv_pairs_from_forms(response)
    if not fields:
        fields = _extract_pairs_from_lines_by_colon(response)
    if not fields:
        raise ValueError("No fields extracted from Textract response")
    return build_document_request(fields)


def build_document_response(fields: List[ExtractedField]) -> DocumentExtractResponse:
    normalized: dict[str, str] = {}
    for f in fields:
        key = normalize_key(f.key)
        alias = KEY_ALIASES.get(key)
        if alias and f.value:
            normalized[alias] = f.value.strip()

    partial: Dict[str, Any] = {}
    missing: List[str] = []
    errors: List[ParseIssue] = []
    raw_amount = normalized.get("amount")
    if raw_amount:
        try:
            partial["amount"] = parse_amount(raw_amount)
        except Exception as e:
            errors.append(ParseIssue(field="amount", message=f"Invalid amount '{raw_amount}': {e}"))
    else:
        missing.append("amount")
    trx_id = normalized.get("trx_id")
    if trx_id:
        partial["trx_id"] = trx_id
    else:
        missing.append("trx_id")
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

    raw_date = normalized.get("date")
    if raw_date:
        try:
            partial["date"] = parse_date(raw_date)
        except Exception as e:
            errors.append(ParseIssue(field="date", message=f"Invalid date '{raw_date}': {e}"))
    else:
        missing.append("date")
    try:
        doc = DocumentRequest(**partial)
        return DocumentExtractResponse(
            ok=True,
            document=doc,
            partial=partial,
            missing=missing,
            errors=errors,
            raw_fields=fields,
        )
    except ValidationError as e:
        errors.append(ParseIssue(field="document", message=str(e)))
        return DocumentExtractResponse(
            ok=False,
            document=None,
            partial=partial,
            missing=missing,
            errors=errors,
            raw_fields=fields,
        )
    

router = APIRouter(prefix="/extractor", tags=["textract"])
@router.post("/aws-extract", response_model=DocumentExtractResponse)
async def analyze_document(
    user: user_dependency,
    file: UploadFile = File(...)
) -> DocumentExtractResponse:
    # --- Validaciones básicas de archivo ---
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
    # Textract sync limit
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="File too large for synchronous Textract (max 10MB)",
        )
    # --- Llamada a AWS Textract ---
    try:
        aws_resp = _textract.analyze_document(
            Document={"Bytes": data},
            FeatureTypes=["FORMS"],
        )
    except (BotoCoreError, ClientError) as e:
        # Error real de infraestructura
        raise HTTPException(
            status_code=502,
            detail=f"Textract error: {str(e)}",
        )

    # --- Extracción de campos ---
    fields = _extract_kv_pairs_from_forms(aws_resp)
    if not fields:
        fields = _extract_pairs_from_lines_by_colon(aws_resp)

    if not fields:
        # No hay nada parseable, pero NO rompemos el FE
        return DocumentExtractResponse(
            ok=False,
            document=None,
            partial={},
            missing=[],
            errors=[
                ParseIssue(
                    field="*",
                    message="No fields extracted from Textract response",
                )
            ],
            raw_fields=[],
        )
    # --- Construcción tolerante del documento ---
    # Esto NO lanza excepciones
    return build_document_response(fields)


def normalize_key(key: str) -> str:
    return (
        key.lower()
        .replace(":", "")
        .strip()
    )

def parse_amount(raw: str) -> float:
    raw = raw.replace("$", "").replace(".", "").replace(",", ".")
    return float(raw.strip())


def parse_date(raw: str) -> date:
    # "24/07/20 12:35:00"
    return datetime.strptime(raw.strip(), "%d/%m/%y %H:%M:%S").date()


def extract_digits(raw: str) -> str:
    return re.sub(r"\D", "", raw)


def extract_cbu(raw: str) -> str | None:
    digits = extract_digits(raw)
    return digits if len(digits) == 22 else None


def build_document_request(fields: List[ExtractedField]) -> DocumentRequest:
    normalized: dict[str, str] = {}
    for f in fields:
        key = normalize_key(f.key)
        if key in KEY_ALIASES and f.value:
            normalized[KEY_ALIASES[key]] = f.value.strip()
    try:
        return DocumentRequest(
            amount=parse_amount(normalized["amount"]),
            trx_id=normalized["trx_id"],
            emisor_name=normalized["emisor_name"],
            emisor_cuit=extract_digits(normalized["emisor_cuit"]),
            emisor_cbu=extract_cbu(normalized.get("emisor_cbu", "")),
            receptor_name=normalized["receptor_name"],
            receptor_cuit=extract_digits(normalized["receptor_cuit"]),
            receptor_cbu=extract_cbu(normalized.get("receptor_cbu", "")),
            date=parse_date(normalized["date"]),
        )
    except KeyError as e:
        raise ValueError(f"Missing required field from Textract: {e}")
    

KEY_ALIASES = {
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
    }