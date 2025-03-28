from typing import Annotated
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from db.database import SessionLocal
from starlette import status
from .auth import get_current_user
from models import Entity, Users, Trx
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


@router.get("", status_code=status.HTTP_200_OK)
async def get_all_transactions(db: db_dependency, user: user_dependency):
  validate_user(user=user)
  user_model = db.query(Users).filter(Users.id == user.get('id')).first()
  return db.query(Trx.entityId == user_model.entity_id).all()


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_new_document(db: db_dependency, user: user_dependency, document_request: DocumentRequest):
  validate_user(user=user)
  document_data = {'No base64 data extracted'}
  if document_request is None:
    raise HTTPException(status_code=status.HTTP_406_NOT_ACCEPTABLE, detail="File format not acceptable")
  
  if document_request.type == 'pdf':
    if document_request.bank == 'mp':
      document_data = extract_info_from_pdf_base64(document_request.base64)
      entity_cbu = document_data.get('receptor_cbu')

      if document_data.get('receptor_cbu') is None:
        print(document_data)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unable to detect cbu or invalid cbu found.")

      entity_model = db.query(Entity).filter(Entity.cbu.has(nro=entity_cbu)).first()

      print(f"receptor: {document_data.get('receptor_cbu')} ------- emisor: {document_data.get('emisor_cbu')}")

      if entity_model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entity not found with cbu: {entity_cbu}")
      
      create_user_model = Trx(
        emisorCBU=document_data.get('emisor_cbu'),
        emisorName=document_data.get('emisor_name'),
        emisorCUIT=document_data.get('emisor_cuit'),
        receptorCBU=document_data.get('receptor_cbu'),
        entityId=entity_model.id,
        amount=document_data.get('amount'),
        date=document_data.get('date')
      )
      db.add(create_user_model)
      db.commit()
      
  return {
    'message': 'Transaction registered!',
    'document_info': document_data
  }