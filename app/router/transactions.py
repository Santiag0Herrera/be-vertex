from typing import Annotated
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import extract
from fastapi import APIRouter, Depends, HTTPException, Query
from db.database import SessionLocal
from starlette import status
from .auth import get_current_user
from models import Entity, Users, Trx, CBU
from services.pdf_reader import extract_info_from_pdf_base64

router = APIRouter(
  prefix='/trx',
  tags=['Transactions']
)

class DocumentRequest(BaseModel):
  amount: float = Field(..., gt=0, description="Transaction amount, must be greater than 0")
  trx_id: str = Field(..., min_length=4, description="Unique transaction ID from the comprobante")
  emisor_name: str = Field(..., min_length=1, description="Name of the sender")
  emisor_cuit: str = Field(..., pattern=r"^\d{11}$", description="CUIT of the sender, must be 11 digits")
  emisor_cbu: str = Field(..., pattern=r"^\d{22}$", description="CBU of the sender, must be 22 digits")
  receptor_name: str = Field(..., min_length=1, description="Name of the receiver")
  receptor_cuit: str = Field(..., pattern=r"^\d{11}$", description="CUIT of the receiver, must be 11 digits")
  receptor_cbu: str = Field(..., pattern=r"^\d{22}$", description="CBU of the receiver, must be 22 digits")
  date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Transaction date in YYYY-MM-DD format")

def get_db():
  db = SessionLocal()
  try: 
    yield db
  finally:
    db.close() 

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

def validate_user(user):
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
  return True


@router.get("/all", status_code=status.HTTP_200_OK)
async def get_all_transactions(
    db: db_dependency,
    user: user_dependency,
    month: int = Query(..., gt=0, lt=13),
    year: int = Query(..., gt=2000),
    day: int = Query(..., gt=0, lt=32)
):
    validate_user(user=user)
    user_model = db.query(Users).filter(Users.id == user.get('id')).first()
    transactions_model = db.query(Trx)\
        .filter(
            Trx.entity_id == user_model.entity_id,
            extract('month', Trx.date) == month,
            extract('year', Trx.date) == year,
            extract('day', Trx.date) == day,
        ).all()
    day_total_amount = sum(transaction.amount for transaction in transactions_model)
    return {
      "transactions": transactions_model,
      "total_amount": day_total_amount
    }


@router.post("/new", status_code=status.HTTP_201_CREATED)
async def upload_new_document(db: db_dependency, user: user_dependency, document_request: DocumentRequest):
  validate_user(user=user)

  cbu_model = db.query(CBU).filter(CBU.cuit == document_request.receptor_cuit).first()
  if cbu_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No entity found with the provided CBU and CUIT combination")
  
  trx_exists_model = db.query(Trx).filter(Trx.trx_id == document_request.trx_id).first()
  if trx_exists_model is not None:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Transaction already exists")

  entity_model = db.query(Entity).filter(Entity.cbu_id == cbu_model.id).first()
  if entity_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entity not found with cuit: {document_request.receptor_cuit}")
  
  create_user_model = Trx(
    emisor_cbu=document_request.emisor_cbu,
    emisor_name=document_request.emisor_name,
    emisor_cuit=document_request.emisor_cuit,
    receptor_cbu=cbu_model.nro,
    entity_id=entity_model.id,
    amount=document_request.amount,
    date=document_request.date,
    trx_id=document_request.trx_id,
    status="pendiente"
  )
  db.add(create_user_model)
  db.commit()
      
  return {
    'message': 'Transaction registered!',
  }