import fitz
from typing import List, Tuple
from servers.converters import register

class PDFConverter:
    name: str = "pymupdf"

    def supported(self) -> List[Tuple[str, str]]:
        return [
            ("pdf", "text"),
            ("pdf", "markdown")
        ]

    def convert(self, data: bytes, from_fmt: str, to_fmt: str) -> bytes:
        # Load PDF from in-memory stream
        doc = fitz.open(stream=data, filetype="pdf")
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        
        # Combine extracted pages into a single UTF-8 encoded text stream
        full_text = "\n".join(text_parts)
        return full_text.encode("utf-8")

# Register the converter instance
register(PDFConverter())
