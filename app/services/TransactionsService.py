from sqlalchemy.orm import Session
from app.models import Trx, Users, CBU, Entity
from sqlalchemy import extract
from app.schemas.transactions import DocumentRequest, MultipleDocumentRequest

from .ErrorService import ErrorService
from .SuccessService import SuccessService
from .InterBankingService import InterBankingService

class TransactionsService:
  db: Session
  req_user: dict
  error: ErrorService
  success: SuccessService

  def __init__(self, db: Session, req_user: dict):
    self.db = db
    self.req_user = req_user
    self.error = ErrorService()
    self.success = SuccessService()
    self.ib_service = InterBankingService(req_user=req_user)
  
  async def _verify_bank_movement(
    self,
    account_number: str,
    bank_number: str,
    customer_id: str
  ):
    movement_model = self.ib_service.get_movement(
      account_number=account_number,
      bank_number=bank_number,
      customer_id=customer_id
    )
    return self.error.raise_if_none(movement_model, "Movment")


  def get_all(self, day, month, year):
    user_model = self.db.query(Users).filter(
      Users.id == self.req_user.get('id')
    ).first()
    transactions_model = self.db.query(Trx).filter(
      Trx.entity_id == user_model.entity_id,
      extract('month', Trx.date) == month,
      extract('year', Trx.date) == year,
      extract('day', Trx.date) == day,
    ).all()
    day_total_amount = sum(transaction.amount for transaction in transactions_model)
    result = {
      "transactions": transactions_model,
      "total_amount": day_total_amount
    }
    return self.success.response(result)
  
  def create(self, document_request: DocumentRequest):
    cbu_model = self.db.query(CBU).filter(
      CBU.cuit == document_request.receptor_cuit
    ).first() 
    self.error.raise_if_none(cbu_model)

    trx_exists_model = self.db.query(Trx).filter(
      Trx.trx_id == document_request.trx_id
    ).first()
    self.error.raise_if_none(trx_exists_model)

    entity_model = self.db.query(Entity).filter(
      Entity.cbu_id == cbu_model.id
    ).first()
    self.error.raise_if_none(entity_model, f"Entity with cuit: {document_request.receptor_cuit}")
    
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
    self.db.add(create_user_model)
    self.db.commit()
    return self.success.response("Transaction registered!")
  
  def create_multiple(self, multiple_trx_request: MultipleDocumentRequest):
      trx_ids = [doc.trx_id for doc in multiple_trx_request.transactions]

      entity_model = self.db.query(Entity).filter(
        Entity.cbu_id == self.req_user.get('entity_id')
      ).first()
      self.error.raise_if_none(entity_model, "User entity")
      
      cbu_model = self.db.query(CBU).filter(
        CBU.id == entity_model.cbu_id
      ).first()

      # Consultar los trx que ya existen
      already_exists = self.db.query(Trx.trx_id).filter(
        Trx.trx_id.in_(trx_ids)
      ).all()
      already_exists_set = set(e[0] for e in already_exists)

      new_trx = []
      already_created = []

      for doc in multiple_trx_request.transactions:
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
          self.db.add(trx_model)
          self.db.flush()
      self.db.commit()

      if len(already_created) == len(multiple_trx_request.transactions):
        self.error.raise_conflict("All transactions already exists")

      result = {
          "created": len(new_trx),
          "duplicates": already_created
      }
      return self.success.response(result)
  