from __future__ import annotations

from io import BytesIO

import fitz


def convert_first_pdf_page_to_png(pdf_data: bytes, dpi: int = 200) -> bytes:
    document = fitz.open(stream=pdf_data, filetype="pdf")
    page = document.load_page(0)
    pixmap = page.get_pixmap(dpi=dpi)
    buffer = BytesIO(pixmap.tobytes("png"))

    return buffer.getvalue()
