import base64
import fitz  # PyMuPDF
import re
import io
from typing import Dict, Any
from datetime import datetime

def convert_text_to_date(text: str) -> str:
    # Map Spanish month names to their English equivalents
    spanish_to_english_months = {
      "enero": "January", "febrero": "February", "marzo": "March",
      "abril": "April", "mayo": "May", "junio": "June",
      "julio": "July", "agosto": "August", "septiembre": "September",
      "octubre": "October", "noviembre": "November", "diciembre": "December"
    }

    # Extract the relevant part (the date)
    date_part = text.split(" a las ")[0].split(", ")[1]

    # Replace Spanish month with English equivalent
    for spanish, english in spanish_to_english_months.items():
      date_part = date_part.replace(f" de {spanish} de ", f" {english} ")

    # Parse the date
    date_obj = datetime.strptime(date_part, "%d %B %Y")
    return date_obj.strftime('%Y-%m-%d')

def extract_info_from_pdf_base64(base64_string: str) -> Dict[str, Any]:
    """
    Extracts information from a Base64 encoded PDF without saving it to disk.
    Args:
        base64_string (str): The Base64 encoded PDF file.
    Returns:
        Dict[str, Any]: A dictionary containing the extracted information.
    """
    try:
        # Decode the base64 string and load it into memory (BytesIO)
        pdf_data = base64.b64decode(base64_string)
        pdf_file = io.BytesIO(pdf_data)

        # Open the PDF and extract text
        extracted_text = ""
        with fitz.open(stream=pdf_file, filetype="pdf") as doc:
            for page in doc:
                extracted_text += page.get_text() + "\n"

        # Extracting relevant information using regex patterns
        data = {
          'amount': float(re.search(r'\$\s([0-9.,]+)', extracted_text).group(1).replace('.', '').replace(',', '.')) if re.search(r'\$\s([0-9.,]+)', extracted_text) else None,
          'emisor_name': re.search(r'De\n([\w\s]+)\nCUIT', extracted_text).group(1).strip() if re.search(r'De\n([\w\s]+)\nCUIT', extracted_text) else None,
          'emisor_cuit': re.search(r'De\n[\w\s]+\nCUIT/CUIL:\s([0-9\-]+)', extracted_text).group(1) if re.search(r'De\n[\w\s]+\nCUIT/CUIL:\s([0-9\-]+)', extracted_text) else None,
          'emisor_cbu': re.findall(r'(CBU|CVU)[:\s]*([0-9]{22})', extracted_text)[0][1] if len(re.findall(r'(CBU|CVU)[:\s]*([0-9]{22})', extracted_text)) > 0 else None,
          'receptor_name': re.search(r'Para\n([\w\s]+)\nCUIT', extracted_text).group(1).strip() if re.search(r'Para\n([\w\s]+)\nCUIT', extracted_text) else None,
          'receptor_cuit': re.search(r'Para\n[\w\s]+\nCUIT/CUIL:\s([0-9\-]+)', extracted_text).group(1) if re.search(r'Para\n[\w\s]+\nCUIT/CUIL:\s([0-9\-]+)', extracted_text) else None,
          'receptor_cbu': re.findall(r'(CBU|CVU)[:\s]*([0-9]{22})', extracted_text)[1][1] if len(re.findall(r'(CBU|CVU)[:\s]*([0-9]{22})', extracted_text)) > 1 else None,
          'date': convert_text_to_date(re.search(r'\w+,\s[0-9]{1,2}\sde\s\w+\sde\s[0-9]{4}\sa\slas\s[0-9]{1,2}:[0-9]{2}\shs', extracted_text).group(0)) if re.search(r'\w+,\s[0-9]{1,2}\sde\s\w+\sde\s[0-9]{4}\sa\slas\s[0-9]{1,2}:[0-9]{2}\shs', extracted_text) else None
        }

        return data

    except Exception as e:
        return {'error': str(e)}
