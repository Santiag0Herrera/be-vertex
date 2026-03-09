from __future__ import annotations

from datetime import date, datetime, time as dt_time
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
from fastapi.concurrency import run_in_threadpool
from io import BytesIO
import fitz

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

KEY_ALIASES_RAW = {
    "envio de dinero a": "receptor_name",
    "envío de dinero a": "receptor_name",
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
    "hora operacion": "time",
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
    "cvu": "receptor_cbu",
    "cuit cuil": "receptor_cuit",
    "cuitcuil": "receptor_cuit",
    "cuit": "receptor_cuit",
    "cuil": "receptor_cuit",
    "dni": "receptor_cuit",
    "documento": "receptor_cuit",

    # --- AMOUNT (monto) ---
    "importe transferencia": "amount",
    "importe acreditado": "amount",
    "importe debitado": "amount",
    "importe transferido": "amount",
    "monto acreditado": "amount",
    "monto debitado": "amount",
    "monto transferido": "amount",
    "total transferencia": "amount",
    "importe operacion": "amount",
    "importe operado": "amount",

    # --- TRX ID (identificador de operación) ---
    "numero operacion": "trx_id",
    "nro de operacion": "trx_id",
    "numero de operacion": "trx_id",
    "id transferencia": "trx_id",
    "codigo transferencia": "trx_id",
    "referencia transferencia": "trx_id",
    "nro referencia": "trx_id",
    "numero referencia operacion": "trx_id",

    # --- DATE (fecha) ---
    "fecha transferencia": "date",
    "fecha acreditacion": "date",
    "fecha debito": "date",
    "hora": "time",
    "hora operación": "time",
    "hora transferencia": "time",
    "hora transaccion": "time",
    "hora transacción": "time",
    "fecha archivo": "date",
    "filename datetime": "date",

    # --- EMISOR (originante) ---
    "titular origen": "emisor_name",
    "cuenta origen titular": "emisor_name",
    "propietario cuenta origen": "emisor_name",

    # documento emisor
    "cuit ordenante": "emisor_cuit",
    "cuil ordenante": "emisor_cuit",
    "dni ordenante": "emisor_cuit",
    "documento ordenante": "emisor_cuit",

    # cuenta emisor
    "cbu cuenta origen": "emisor_cbu",
    "numero cuenta origen": "emisor_cbu",
    "cuenta bancaria origen": "emisor_cbu",

    # --- RECEPTOR (destinatario) ---
    "titular destino": "receptor_name",
    "propietario cuenta destino": "receptor_name",

    # documento receptor
    "cuit beneficiario": "receptor_cuit",
    "dni beneficiario": "receptor_cuit",

    # cuenta receptor
    "cbu cuenta destino": "receptor_cbu",
    "numero cuenta destino": "receptor_cbu",
    "cuenta bancaria destino": "receptor_cbu",

    # --- WALLET / CVU ---
    "alias": "wallet_cvu",
    "alias cvu": "wallet_cvu",
    "cvu cuenta": "wallet_cvu",
    "cvu destino": "wallet_cvu",

    "cuit cuil titular": "wallet_cuit",
    "documento titular": "wallet_cuit",
    "documento usuario": "wallet_cuit",

    # --- OTROS CAMPOS FRECUENTES EN TRANSFERENCIAS ---
    "tipo transferencia": "trx_id",
    "concepto": "trx_id",
    "motivo": "trx_id",
}

KEY_ALIASES = {normalize_key(k): v for k, v in KEY_ALIASES_RAW.items()}

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

def extract_digits(raw: str) -> str:
    return re.sub(r"\D", "", str(raw or ""))

AMOUNT_REGEX = re.compile(
    r"(?:ar\$|\$|ars)?\s*[+-]?\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|(?:ar\$|\$|ars)?\s*[+-]?\d+(?:[.,]\d{2})",
    re.IGNORECASE,
)
CUIT_REGEX = re.compile(r"\b\d{2}[-\s]?\d{8}[-\s]?\d\b")
CBU_OR_CVU_REGEX = re.compile(r"\b\d{22}\b")
TRX_REGEX = re.compile(r"\b[A-Z0-9]{6,}\b", re.IGNORECASE)
DATE_TEXT_REGEX = re.compile(
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\s+de\s+[a-záéíóú]+\s+de\s+\d{4}|\d{1,2}[/-][a-záéíóú]{3,}[/-]\d{2,4}",
    re.IGNORECASE,
)
TIME_TEXT_REGEX = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:\s*[ap]\.?m\.?)?\b", re.IGNORECASE)

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

def parse_date(raw: str) -> datetime:
    """
    Parser robusto para fechas de comprobantes bancarios / billeteras.
    Soporta:
    - 27/03/2025
    - 27/03/2025 22:36
    - 2025-03-27
    - 2025-03-27T22:36:10
    - 2 de agosto de 2024
    - 2 de agosto de 2024 - 11:53
    - Jueves, 27 de marzo de 2025 a las 22:36 hs
    """
    if raw is None:
        raise ValueError("date is None")
    s = str(raw).strip().lower()
    s = re.sub(r"\s+", " ", s)
    spanish_months = {
        "enero": 1,
        "febrero": 2,
        "marzo": 3,
        "abril": 4,
        "mayo": 5,
        "junio": 6,
        "julio": 7,
        "agosto": 8,
        "septiembre": 9,
        "octubre": 10,
        "noviembre": 11,
        "diciembre": 12,
    }
    match = re.search(
        r"(\d{1,2}) de ([a-záéíóú]+) de (\d{4})(?:\s*[-a]\s*(?:las\s*)?(\d{1,2}):(\d{2}))?",
        s
    )
    if match:
        day = int(match.group(1))
        month_name = normalize_key(match.group(2))
        year = int(match.group(3))
        hour = int(match.group(4) or 0)
        minute = int(match.group(5) or 0)

        month = spanish_months.get(month_name)
        if month:
            return datetime(year, month, day, hour, minute)

    # Formato tipo: 25/JUL/2024 - 12:59 h
    short_months = {
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
    short_match = re.search(
        r"(\d{1,2})[/-]([a-záéíóú]{3,})[/-](\d{2,4})(?:\s*[-]\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*h?s?)?",
        s,
    )
    if short_match:
        day = int(short_match.group(1))
        month_name = normalize_key(short_match.group(2))[:3]
        year = int(short_match.group(3))
        if year < 100:
            year += 2000
        hour = int(short_match.group(4) or 0)
        minute = int(short_match.group(5) or 0)
        second = int(short_match.group(6) or 0)
        month = short_months.get(month_name)
        if month:
            return datetime(year, month, day, hour, minute, second)
    s_clean = re.sub(r"(lunes|martes|miercoles|miércoles|jueves|viernes|sabado|sábado|domingo),?", "", s)
    s_clean = re.sub(r"a las", "", s_clean)
    s_clean = re.sub(r"hs", "", s_clean)
    s_clean = s_clean.strip()
    patterns = [
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
    for fmt in patterns:
        try:
            return datetime.strptime(s_clean, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s_clean)
    except Exception:
        raise ValueError(f"Unsupported date format: '{raw}'")

def parse_time(raw: str) -> dt_time:
    if raw is None:
        raise ValueError("time is None")
    s = str(raw).strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\bhs\b", "", s).strip()
    s = s.replace(".", "")

    # 24h
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            pass

    # 12h am/pm
    for fmt in ("%I:%M:%S %p", "%I:%M %p"):
        try:
            return datetime.strptime(s.upper(), fmt).time()
        except ValueError:
            pass
    raise ValueError(f"Unsupported time format: '{raw}'")

def _extract_datetime_from_filename(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    base = os.path.basename(filename)
    stem = os.path.splitext(base)[0]
    s = stem.lower()

    # dd-mm-yyyy_hh-mm-ss or dd-mm-yy_hh-mm(-ss)
    m = re.search(r"(\d{1,2})-(\d{1,2})-(\d{2,4})[_\s-](\d{1,2})-(\d{2})(?:-(\d{2}))?", s)
    if m:
        d, mo, y, hh, mm, ss = m.groups()
        year = int(y)
        if year < 100:
            year += 2000
        return f"{int(d):02d}/{int(mo):02d}/{year:04d} {int(hh):02d}:{int(mm):02d}:{int(ss or 0):02d}"

    # yyyy-mm-ddThhmmss(.sss)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})t(\d{2})(\d{2})(\d{2})", s)
    if m:
        y, mo, d, hh, mm, ss = m.groups()
        return f"{int(d):02d}/{int(mo):02d}/{int(y):04d} {int(hh):02d}:{int(mm):02d}:{int(ss):02d}"

    # yymmdd_hhmmss (e.g. transferencia-1_250630_164352)
    m = re.search(r"(\d{2})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})", s)
    if m:
        y, mo, d, hh, mm, ss = m.groups()
        return f"{int(d):02d}/{int(mo):02d}/{2000 + int(y):04d} {int(hh):02d}:{int(mm):02d}:{int(ss):02d}"

    return None

def _clean_value_text(value: str) -> str:
    v = str(value or "").strip()
    v = re.sub(r"\s+", " ", v)
    return v.strip(":- \t")

def _field_score(field_key: str, field_value: str, confidence: Optional[float]) -> float:
    score = float(confidence or 0)
    key_norm = normalize_key(field_key)
    val_norm = normalize_key(field_value)
    if key_norm in KEY_ALIASES:
        score += 10
    if len(val_norm) >= 4:
        score += 1
    if looks_like_value(field_value):
        score += 2
    return score

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

    results: List[ExtractedField] = []
    texts = [re.sub(r"\s+", " ", b["Text"]).strip() for b in lines]

    for text in texts:
        # Caso "Key: Value"
        if ":" in text:
            left, right = text.split(":", 1)
            key = _clean_value_text(left)
            value = _clean_value_text(right)
            if key and value:
                results.append(ExtractedField(key=key, value=value))
                continue

        # Caso "Key - Value"
        for sep in (" - ", " – ", " — ", " = "):
            if sep in text:
                left, right = text.split(sep, 1)
                key = _clean_value_text(left)
                value = _clean_value_text(right)
                if key and value and not key.isdigit():
                    results.append(ExtractedField(key=key, value=value))
                    break

    # Caso "Key:" en una linea y "Value" en la siguiente
    i = 0
    while i < len(texts) - 1:
        current = texts[i]
        nxt = texts[i + 1]
        if current.endswith(":"):
            key = _clean_value_text(current[:-1])
            value = _clean_value_text(nxt)
            if key and value and not value.endswith(":"):
                results.append(ExtractedField(key=key, value=value))
                i += 2
                continue
        i += 1

    for r in results:
        r.key = re.sub(r"\s+", " ", r.key).strip()
        r.value = re.sub(r"\s+", " ", r.value).strip()

    return results

def _extract_fields_from_lines_wallet(response: Dict[str, Any]) -> List[ExtractedField]:
    """
    Fallback extractor para comprobantes tipo billetera (Mercado Pago, Ualá, etc)
    donde Textract no genera KEY_VALUE_SET confiable.
    """
    blocks = response.get("Blocks", []) or []
    lines = [b.get("Text", "").strip() for b in blocks if b.get("BlockType") == "LINE"]
    results: List[ExtractedField] = []
    datetime_regex = re.compile(
        r"\d{1,2} de [a-záéíóú]+ de \d{4}(?:\s*-\s*\d{1,2}:\d{2})?",
        re.IGNORECASE,
    )
    datetime_short_month_regex = re.compile(
        r"\d{1,2}[/-][A-Za-záéíóú]{3,}[/-]\d{2,4}(?:\s*-\s*\d{1,2}:\d{2}(?::\d{2})?\s*h?)?",
        re.IGNORECASE,
    )
    for line in lines:
        normalized_line = normalize_key(line)
        # monto
        m = AMOUNT_REGEX.search(line)
        if m:
            results.append(ExtractedField(key="monto", value=m.group()))
        # fecha con o sin hora
        d = datetime_regex.search(line)
        if d:
            results.append(ExtractedField(key="fecha", value=d.group()))
        d2 = datetime_short_month_regex.search(line)
        if d2:
            results.append(ExtractedField(key="fecha", value=d2.group()))
        # CVU
        if "cvu" in normalized_line:
            cvu = CBU_OR_CVU_REGEX.search(line)
            if cvu:
                results.append(ExtractedField(key="cvu", value=cvu.group()))
            else:
                results.append(ExtractedField(key="cvu", value=line))
        if "cuit cuil" in normalized_line or "cuit" in normalized_line or "dni" in normalized_line:
            cuit = CUIT_REGEX.search(line)
            if cuit:
                results.append(ExtractedField(key="cuit cuil", value=cuit.group()))
    return results

def looks_like_value(text: str) -> bool:
    t = text.lower()
    # fecha tipo "2 de agosto de 2024"
    if re.search(r"\d{1,2} de [a-záéíóú]+ de \d{4}", t):
        return True
    # hora
    if re.search(r"\d{1,2}:\d{2}", t):
        return True
    # monto
    if AMOUNT_REGEX.search(t):
        return True
    if CUIT_REGEX.search(t) or CBU_OR_CVU_REGEX.search(t):
        return True
    if DATE_TEXT_REGEX.search(t):
        return True
    if TIME_TEXT_REGEX.search(t):
        return True
    return False

def _extract_semantic_candidates(fields: List[ExtractedField]) -> Dict[str, str]:
    best: Dict[str, tuple[str, float]] = {}

    def consider(alias: str, value: str, score: float) -> None:
        cleaned = _clean_value_text(value)
        if not cleaned:
            return
        current = best.get(alias)
        if current is None or score > current[1]:
            best[alias] = (cleaned, score)

    for f in fields:
        key_norm = normalize_key(f.key)
        value = _clean_value_text(f.value)
        base_score = _field_score(f.key, value, f.confidence)

        alias = KEY_ALIASES.get(key_norm)
        if alias:
            consider(alias, value, base_score + 3)

        if AMOUNT_REGEX.search(value):
            consider("amount", AMOUNT_REGEX.search(value).group(), base_score)

        maybe_cuit = CUIT_REGEX.search(value)
        if maybe_cuit:
            # Si no sabemos rol, priorizamos receptor (comportamiento previo en wallets)
            if "emisor" in key_norm or "origin" in key_norm or "ordenante" in key_norm:
                consider("emisor_cuit", maybe_cuit.group(), base_score)
            elif "receptor" in key_norm or "destinat" in key_norm or "benefici" in key_norm:
                consider("receptor_cuit", maybe_cuit.group(), base_score)
            else:
                consider("receptor_cuit", maybe_cuit.group(), base_score - 0.5)

        maybe_cbu = CBU_OR_CVU_REGEX.search(value)
        if maybe_cbu:
            if "emisor" in key_norm or "origin" in key_norm:
                consider("emisor_cbu", maybe_cbu.group(), base_score)
            elif "receptor" in key_norm or "destinat" in key_norm:
                consider("receptor_cbu", maybe_cbu.group(), base_score)
            elif "cvu" in key_norm:
                consider("wallet_cvu", maybe_cbu.group(), base_score)
            else:
                consider("receptor_cbu", maybe_cbu.group(), base_score - 0.5)

        if DATE_TEXT_REGEX.search(value):
            date_score = base_score + (5 if TIME_TEXT_REGEX.search(value) else 0)
            consider("date", value, date_score)
        if TIME_TEXT_REGEX.search(value):
            time_match = TIME_TEXT_REGEX.search(value)
            if time_match:
                consider("time", time_match.group(), base_score)

        if ("operacion" in key_norm or "transaccion" in key_norm or "referencia" in key_norm or "comprobante" in key_norm):
            trx = TRX_REGEX.search(value)
            if trx:
                consider("trx_id", trx.group(), base_score)
            else:
                consider("trx_id", value, base_score - 0.5)

    return {k: v for k, (v, _) in best.items()}

def _merge_and_dedup_fields(*groups: List[ExtractedField]) -> List[ExtractedField]:
    merged: List[ExtractedField] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for f in group:
            k = normalize_key(f.key)
            v = _clean_value_text(f.value)
            if not k or not v:
                continue
            key = (k, v.lower())
            if key in seen:
                continue
            seen.add(key)
            merged.append(ExtractedField(key=f.key.strip(), value=v, confidence=f.confidence))
    return merged

def build_document_response(fields: List[ExtractedField]) -> DocumentExtractResponse:
    normalized: Dict[str, str] = _extract_semantic_candidates(fields)

    # Completa con aliases directos si algo no fue detectado semánticamente.
    for f in fields:
        key = normalize_key(f.key)
        alias = KEY_ALIASES.get(key)
        if alias and f.value:
            if alias not in normalized:
                normalized[alias] = _clean_value_text(f.value)

        # Si una línea completa es una fecha, úsala como fallback.
        if "date" not in normalized and not looks_like_value(f.key):
            try:
                parse_date(f.key)
                normalized["date"] = f.key.strip()
            except Exception:
                pass
    partial: Dict[str, Any] = {}
    missing: List[str] = []
    errors: List[ParseIssue] = []
    # ----------------------------------------
    # Wallet data
    # ----------------------------------------
    wallet_cvu = normalized.get("wallet_cvu")
    if wallet_cvu:
        partial["wallet_cvu"] = extract_digits(wallet_cvu)
    wallet_cuit = normalized.get("wallet_cuit")
    if wallet_cuit:
        partial["wallet_cuit"] = extract_digits(wallet_cuit)
    # ----------------------------------------
    # Amount
    # ----------------------------------------
    raw_amount = normalized.get("amount")
    if raw_amount:
        try:
            partial["amount"] = parse_amount(raw_amount)
        except Exception as e:
            errors.append(ParseIssue(field="amount", message=f"Invalid amount '{raw_amount}': {e}"))
    else:
        missing.append("amount")
    # ----------------------------------------
    # trx_id
    # ----------------------------------------
    trx_id = normalized.get("trx_id")
    if trx_id:
        partial["trx_id"] = trx_id
    else:
        missing.append("trx_id")
    # ----------------------------------------
    # emisor
    # ----------------------------------------
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
    # ----------------------------------------
    # receptor
    # ----------------------------------------
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
    # ----------------------------------------
    # date
    # ----------------------------------------
    raw_date = normalized.get("date")
    raw_time = normalized.get("time")
    if raw_date:
        try:
            parsed_date = parse_date(raw_date)

            # Si fecha no trae hora/minuto, intenta completar con un campo de hora separado.
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
        except Exception as e:
            errors.append(ParseIssue(field="date", message=f"Invalid date '{raw_date}': {e}"))
    elif raw_time:
        # fallback: a veces llega fecha+hora dentro del campo de hora
        try:
            partial["date"] = parse_date(raw_time)
        except Exception:
            missing.append("date")
    else:
        missing.append("date")
    # ----------------------------------------
    # Wallet heuristic
    # ----------------------------------------
    wallet = is_wallet_document(fields)
    if wallet:
        missing = [
            m for m in missing
            if m not in {"emisor_name", "receptor_name", "receptor_cuit"}
        ]
    # ----------------------------------------
    # Validación final
    # ----------------------------------------
    REQUIRED_FOR_DOCUMENT = {
        "amount",
        "trx_id",
        "emisor_name",
        "emisor_cuit",
        "receptor_name",
        "receptor_cuit",
        "date",
    }
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
    doc_payload = {
        k: v for k, v in partial.items()
        if k in DocumentRequest.model_fields
    }
    doc = DocumentRequest(**doc_payload)
    return DocumentExtractResponse(
        ok=True,
        document=doc,
        partial=partial,
        missing=missing,
        errors=errors,
        raw_fields=fields,
    )

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
    # Convertir PDF → imagen (Textract funciona mucho mejor así)
    if file.content_type == "application/pdf":
      try:
          doc = fitz.open(stream=data, filetype="pdf")
          page = doc.load_page(0)
          pix = page.get_pixmap(dpi=300)
          img_buffer = BytesIO(pix.tobytes("png"))
          data = img_buffer.getvalue()
      except Exception as e:
          raise HTTPException(
              status_code=422,
              detail=f"PDF conversion failed: {str(e)}"
          )
    # Llamada a Textract
    try:
        aws_resp = await run_in_threadpool(
          _textract.analyze_document,
          Document={"Bytes": data},
          FeatureTypes=["FORMS"],
        )
    except (BotoCoreError, ClientError) as e:
        raise HTTPException(status_code=502, detail=f"Textract error: {str(e)}")

    # Parseo de varias formas: key-value / inline / wallets
    fields = _merge_and_dedup_fields(
        _extract_kv_pairs_from_forms(aws_resp),
        _extract_pairs_from_lines_by_colon(aws_resp),
        _extract_fields_from_lines_wallet(aws_resp),
    )
    filename_dt = _extract_datetime_from_filename(file.filename)
    if filename_dt:
        fields.append(
            ExtractedField(
                key="fecha archivo",
                value=filename_dt,
                confidence=999.0,  # fallback fuerte para comprobantes con timestamp en filename
            )
        )

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
