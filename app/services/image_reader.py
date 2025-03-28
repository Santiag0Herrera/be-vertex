import base64
import io
from PIL import Image
import pytesseract


def extract_text_from_image_base64(base64_image: str) -> str:
    """
    Extracts text from an image file provided as a Base64 string using Tesseract OCR.
    Args:
        base64_image (str): The Base64 encoded image file.
    Returns:
        str: Extracted text from the image.
    """
    try:
        # Decoding the base64 string to bytes
        image_data = base64.b64decode(base64_image)
        image = Image.open(io.BytesIO(image_data))

        # Extracting text from the image using pytesseract
        extracted_text = pytesseract.image_to_string(image)

        return extracted_text.strip()

    except Exception as e:
        return f"Error extracting text from image: {str(e)}"


# Example usage:
# with open('sample_image.png', 'rb') as f:
#     base64_image = base64.b64encode(f.read()).decode('utf-8')
#     print(extract_text_from_image_base64(base64_image))
