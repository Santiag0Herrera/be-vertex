from .ErrorService import ErrorService
from .SuccessService import SuccessService
from app.models import Users, Entity, Product
from sqlalchemy.orm import Session

class ProductsService():
  def __init__(self, db: Session, req_user: dict):
    self.db = db
    self.req_user = req_user
    self.error = ErrorService()
    self.success = SuccessService()

  def get_all(self):
    user_model = self.db.query(Users).filter(
      Users.id == self.req_user.get('id')
    ).first()

    entity_model = self.db.query(Entity).filter(
      Entity.id == user_model.entity_id
    ).first()
    self.error.raise_if_none(entity_model, "User entity")
    
    prodcuts_model = self.db.query(Product).filter(
      Product.name == entity_model.products
    ).all() ## EN UN FUTURO CAMBIAR ESTO POR MANY TO MANY
    result = prodcuts_model
    self.error.raise_if_none(result, "Product")

    return self.success.response(result)
