import os
import tempfile
import pypandoc
from typing import List, Tuple
from servers.converters import register

class PandocConverter:
    name: str = "pandoc"

    def supported(self) -> List[Tuple[str, str]]:
        return [
            ("markdown", "html"),
            ("html", "markdown"),
            ("docx", "markdown"),
            ("docx", "text"),
            ("rst", "markdown"),
            ("rst", "text"),
            ("markdown", "text"),
            ("html", "text")
        ]

    def convert(self, data: bytes, from_fmt: str, to_fmt: str) -> bytes:
        # Map our internal format names to pandoc format names
        to_pandoc = "plain" if to_fmt == "text" else to_fmt
        from_pandoc = "markdown" if from_fmt == "md" else from_fmt

        if from_fmt == "docx":
            # For docx (binary), we write bytes to a temp file and read via convert_file
            fd, temp_path = tempfile.mkstemp(suffix=".docx")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                # Convert the file
                out = pypandoc.convert_file(temp_path, to_pandoc, format=from_pandoc)
                return out.encode("utf-8")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
        else:
            # For text formats, we decode bytes to string and convert inline
            text_str = data.decode("utf-8", errors="ignore")
            out = pypandoc.convert_text(text_str, to_pandoc, format=from_pandoc)
            return out.encode("utf-8")

# Register the converter instance
register(PandocConverter())
