from .ErrorService import ErrorService
from .SuccessService import SuccessService
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_, select
from app.models import Clients, Logs, Users


class LogsService:
    def __init__(self, db: Session, req_user: dict):
        self.db = db
        self.req_user = req_user
        self.error = ErrorService()
        self.success = SuccessService()

    def get_all(self):
        """Returns the 20 most recent logs for the requesting user's entity."""
        entity_id = self.req_user.get("entity_id")
        user_emails = select(Users.email).where(Users.entity_id == entity_id)
        client_cuits = select(Clients.cuit).where(Clients.entity_id == entity_id)
        logs = (
            self.db.query(Logs)
            .filter(or_(Logs.username.in_(user_emails), Logs.username.in_(client_cuits)))
            .order_by(desc(Logs.datetime))
            .limit(20)
            .all()
        )
        return self.success.response(list(reversed(logs)))
