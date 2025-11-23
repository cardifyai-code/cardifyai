from typing import Optional
from PyPDF2 import PdfReader


def extract_text_from_pdf(file_stream) -> Optional[str]:
    """Extract text from a PDF file-like object using PyPDF2."""
    try:
        reader = PdfReader(file_stream)
        texts = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            texts.append(page_text)
        return "\n".join(texts)
    except Exception:
        return None
