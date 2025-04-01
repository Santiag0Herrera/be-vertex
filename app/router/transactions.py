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
  base64: str = Field(min_length=10)
  type: str
  bank: str

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


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_new_document(db: db_dependency, user: user_dependency, document_request: DocumentRequest):
  validate_user(user=user)
  document_data = {'No base64 data extracted'}
  if document_request is None:
    raise HTTPException(status_code=status.HTTP_406_NOT_ACCEPTABLE, detail="File format not acceptable")
  
  if document_request.type == 'pdf':
    if document_request.bank == 'mp':
      document_data = extract_info_from_pdf_base64(document_request.base64)
      entity_cuit = document_data.get('receptor_cuit')

      cbu_model = db.query(CBU).filter(CBU.cuit == entity_cuit).first()
      if cbu_model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No entity found with the provided CBU and CUIT combination")
      
      entity_model = db.query(Entity).filter(Entity.cbu_id == cbu_model.id).first()

      if entity_model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entity not found with cuit: {entity_cuit}")
      
      create_user_model = Trx(
        emisor_cbu=document_data.get('emisor_cbu'),
        emisor_name=document_data.get('emisor_name'),
        emisor_cuit=document_data.get('emisor_cuit'),
        receptor_cbu=cbu_model.nro,
        entity_id=entity_model.id,
        amount=document_data.get('amount'),
        date=document_data.get('date')
      )
      db.add(create_user_model)
      db.commit()
      
  return {
    'message': 'Transaction registered!',
    'document_info': document_data
  }