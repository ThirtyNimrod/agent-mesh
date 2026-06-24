from typing import List, Tuple
from servers.converters import register

class PassthroughConverter:
    name: str = "passthrough"

    def supported(self) -> List[Tuple[str, str]]:
        return [
            ("txt", "text"),
            ("txt", "markdown"),
            ("text", "text"),
            ("markdown", "markdown")
        ]

    def convert(self, data: bytes, from_fmt: str, to_fmt: str) -> bytes:
        # Simply returns the input bytes unmodified
        return data

# Register the converter instance
register(PassthroughConverter())
