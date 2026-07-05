import sys
from pathlib import Path


def load_markdown(
    filename: str | Path = "doc.md",
    *,
    relative_to: str | Path | None = None,
) -> str:
    """Read a markdown file, by default ``doc.md`` next to the calling module.

    Pass ``relative_to`` (typically ``__file__``) to resolve ``filename``
    against that module's directory explicitly — the robust option, since it
    avoids the frame introspection used otherwise. An absolute ``filename`` is
    read as-is. Returns an empty string when the file does not exist.

    Without ``relative_to`` the base directory is taken two frames up, so a
    single helper wrapping this call (e.g. ``get_csv_export``) still reads the
    markdown relative to the module that declared the route.
    """
    doc_path = Path(filename)

    if not doc_path.is_absolute():
        if relative_to is not None:
            base = Path(relative_to)
            base_dir = base.parent if base.suffix else base
        else:
            base_dir = Path(sys._getframe(2).f_code.co_filename).parent
        doc_path = base_dir / doc_path

    try:
        return doc_path.read_text()
    except (FileNotFoundError, IsADirectoryError):
        return ""
