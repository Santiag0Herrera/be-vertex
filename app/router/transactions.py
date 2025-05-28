from typing import Annotated
from sqlalchemy.orm import Session
from sqlalchemy import extract
from fastapi import APIRouter, Depends, HTTPException, Query
from app.db.database import get_db
from starlette import status
from app.services.auth_service import get_current_user
from app.models import Entity, Users, Trx, CBU
from app.schemas.transactions import DocumentRequest, MultipleDocumentRequest

router = APIRouter(
  prefix='/trx',
  tags=['Transactions']
) 

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.get("/all", status_code=status.HTTP_200_OK)
async def get_all_transactions(
    db: db_dependency,
    user: user_dependency,
    month: int = Query(..., gt=0, lt=13),
    year: int = Query(..., gt=2000),
    day: int = Query(..., gt=0, lt=32)
):
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
async def upload_new_document(db: db_dependency, document_request: DocumentRequest):
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


@router.post("/multiple/new", status_code=status.HTTP_201_CREATED)
async def upload_multiple_new_document(db: db_dependency, user: user_dependency, data: MultipleDocumentRequest):
  trx_ids = [doc.trx_id for doc in data.transactions]

  entity_model = db.query(Entity).filter(Entity.cbu_id == user.get('entity_id')).first()
  if entity_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User entity not found")
  cbu_model = db.query(CBU).filter(CBU.id == entity_model.cbu_id).first()

  # Consultar los trx que ya existen
  already_exists = db.query(Trx.trx_id).filter(Trx.trx_id.in_(trx_ids)).all()
  already_exists_set = set(e[0] for e in already_exists)

  new_trx = []
  already_created = []

  for doc in data.transactions:
      if doc.trx_id in already_exists_set:
          already_created.append(doc.trx_id)
          continue

      trx_model = Trx(
        emisor_cbu=doc.emisor_cbu,
        emisor_name=doc.emisor_name,
        emisor_cuit=doc.emisor_cuit,
        receptor_cbu=cbu_model.nro,
        entity_id=entity_model.id,
        amount=doc.amount,
        date=doc.date,
        trx_id=doc.trx_id,
        status="pendiente"
      )
      new_trx.append(trx_model)
      db.add(trx_model)
      db.flush()

  db.commit()

  if len(already_created) == len(data.transactions):
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="All transactions already exists")

  return {
      "created": len(new_trx),
      "duplicates": already_created
  }
