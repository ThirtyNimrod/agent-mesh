import re
from typing import List, Tuple
from servers.converters import register


class MarkdownTextConverter:
    """Pure-Python markdown -> plain-text converter. No pandoc required."""

    name: str = "markdown_native"

    def supported(self) -> List[Tuple[str, str]]:
        return [("markdown", "text")]

    def convert(self, data: bytes, from_fmt: str, to_fmt: str) -> bytes:
        if not data:
            return b""
        text = data.decode("utf-8", errors="ignore")

        # Fenced code blocks — keep the content, drop the fences
        text = re.sub(r"```[^\n]*\n(.*?)```", r"\1", text, flags=re.DOTALL)
        text = re.sub(r"~~~[^\n]*\n(.*?)~~~", r"\1", text, flags=re.DOTALL)

        # ATX headings  (# Heading -> Heading)
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

        # Setext headings  (underlined with === or ---)
        text = re.sub(r"^[=\-]{2,}\s*$", "", text, flags=re.MULTILINE)

        # Images  ![alt](url) -> alt
        text = re.sub(r"!\[([^\]]*)\]\([^\)]*\)", r"\1", text)

        # Links  [text](url) -> text
        text = re.sub(r"\[([^\]]+)\]\([^\)]*\)", r"\1", text)

        # Bold+italic  ***text*** or ___text___
        text = re.sub(r"\*{3}(.+?)\*{3}", r"\1", text, flags=re.DOTALL)
        text = re.sub(r"_{3}(.+?)_{3}", r"\1", text, flags=re.DOTALL)

        # Bold  **text** or __text__
        text = re.sub(r"\*{2}(.+?)\*{2}", r"\1", text, flags=re.DOTALL)
        text = re.sub(r"_{2}(.+?)_{2}", r"\1", text, flags=re.DOTALL)

        # Italic  *text* or _text_
        text = re.sub(r"\*(.+?)\*", r"\1", text, flags=re.DOTALL)
        text = re.sub(r"_(.+?)_", r"\1", text, flags=re.DOTALL)

        # Inline code  `code`
        text = re.sub(r"`(.+?)`", r"\1", text)

        # Blockquotes  > text
        text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)

        # Horizontal rules
        text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)

        # HTML tags
        text = re.sub(r"<[^>]+>", "", text)

        # Collapse 3+ blank lines to 2
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip().encode("utf-8")


register(MarkdownTextConverter())
