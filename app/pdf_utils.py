# app/pdf_utils.py

from io import BytesIO
from typing import Optional

import fitz  # PyMuPDF


def extract_text_from_pdf(pdf_bytes: BytesIO) -> str:
    """
    Extract text from a PDF file (given as bytes) using PyMuPDF.
    """
    pdf_bytes.seek(0)
    doc = fitz.open(stream=pdf_bytes.read(), filetype="pdf")
    texts = []
    for page in doc:
        texts.append(page.get_text("text"))
    doc.close()
    return "\n\n".join(texts)
