from typing import List, Tuple, Protocol, Optional

class Converter(Protocol):
    name: str
    def supported(self) -> List[Tuple[str, str]]:
        """Returns a list of supported (from_format, to_format) conversion pairs."""
        ...
    def convert(self, data: bytes, from_fmt: str, to_fmt: str) -> bytes:
        """Converts input bytes from from_fmt to to_fmt and returns output bytes."""
        ...

REGISTRY: List[Converter] = []

def register(c: Converter):
    """Registers a new converter engine."""
    if c not in REGISTRY:
        REGISTRY.append(c)

def all_pairs() -> List[Tuple[str, str]]:
    """Returns all supported conversion pairs registered in the system."""
    pairs = set()
    for c in REGISTRY:
        for p in c.supported():
            pairs.add(p)
    return sorted(list(pairs))

def find(from_fmt: str, to_fmt: str) -> Optional[Converter]:
    """Finds a registered converter that supports the (from_fmt, to_fmt) conversion."""
    for c in REGISTRY:
        if (from_fmt, to_fmt) in c.supported():
            return c
    return None

# Import submodules to trigger automatic registration.
# Order matters: the first converter that matches a (from, to) pair wins.
# markdown_converter must precede pandoc_converter so markdown->text works
# without pandoc installed.
import servers.converters.passthrough_converter
import servers.converters.pdf_converter
import servers.converters.markdown_converter
import servers.converters.pandoc_converter

