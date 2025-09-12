from .ErrorService import ErrorService
from .SuccessService import SuccessService
from app.schemas.transactions import UploadDocumentRequest
import requests
import os

class N8NService:
  def __init__(self):
    self.client = requests
    self.n8n_url = "https://sherrera.app.n8n.cloud/webhook/extract_data_from_document"
    self.headers = {
      'Content-Type': 'application/json'
    }
    self.raise_error = ErrorService()
    self.success = SuccessService()
  
  async def ai_extract_info(self, upload_document_request: UploadDocumentRequest):
    response = self.client.request("POST", self.n8n_url, headers=self.headers, json=upload_document_request.model_dump_json())
    result = response.json()
    return result