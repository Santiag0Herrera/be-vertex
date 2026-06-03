from .ErrorService import ErrorService
from .SuccessService import SuccessService
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.models import Logs


class LogsService:
    def __init__(self, db: Session, req_user: dict):
        self.db = db
        self.req_user = req_user
        self.error = ErrorService()
        self.success = SuccessService()

    def get_all(self):
        """Returns the 20 most recent logs for the requesting user's entity."""
        logs = self.db.query(Logs).order_by(desc(Logs.datetime)).limit(20).all()
        return self.success.response(list(reversed(logs)))
