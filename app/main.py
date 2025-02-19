from fastapi import FastAPI, UploadFile, File
import shutil
from app.services.image_reader import read_image
from app.services.pdf_reader import read_pdf

app = FastAPI(title="Vertex")

@app.post("/upload/image")
async def upload_image(file: UploadFile = File(...)):
    file_path = f"temp_{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    extracted_data = read_image(file_path)
    return {"extracted_data": extracted_data}

@app.post("/upload/pdf")
async def upload_pdf(file: UploadFile = File(...)):
    file_path = f"temp_{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    extracted_data = read_pdf(file_path)
    return {"extracted_data": extracted_data}
