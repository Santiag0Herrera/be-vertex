from typing import Annotated
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from app.models import Todos
from db.database import SessionLocal
from starlette import status
from .auth import get_current_user

router = APIRouter(
  prefix='/admin',
  tags=['Admin']
)

def get_db():
  db = SessionLocal()
  try: 
    yield db
  finally:
    db.close() 

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

@router.get('/todo', status_code=status.HTTP_200_OK)
async def read_all(user: user_dependency, db: db_dependency):
  if user is None or user.get('user_role') != 'admin':
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Access denied')
  return db.query(Todos).all()

@router.delete("/todo", status_code=status.HTTP_204_NO_CONTENT)
async def delete_todo(user: user_dependency, db: db_dependency, todo_id: int = Query(gt=0)):
  if user is None or user.get('user_role') != 'admin':
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Acces denied')
  todo_model = db.query(Todos).filter(Todos.id == todo_id).first()
  if todo_model is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Todo {todo_id} does not exit")
  db.query(Todos).filter(Todos.id == todo_id).delete()
  db.commit()
