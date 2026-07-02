import sys
from pathlib import Path


def load_markdown() -> str:
    """Read a ``doc.md`` file sitting next to the caller's caller module.

    Resolves the file two frames up so a helper wrapping this call still reads
    the markdown relative to the module that declared the route. Returns an
    empty string when no such file exists.
    """
    caller_file = sys._getframe(2).f_code.co_filename
    caller_dir = Path(caller_file).parent
    doc_path = caller_dir / "doc.md"
    try:
        return doc_path.read_text()
    except FileNotFoundError:
        return ""
