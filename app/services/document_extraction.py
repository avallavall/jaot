"""Document text extraction service for PDF, CSV, and TXT files.

Extracts text content from uploaded documents for use as LLM context.
Raw binary is discarded after extraction -- only text is retained.
"""

import csv
import io
import logging
from typing import NamedTuple

import pypdf

logger = logging.getLogger(__name__)

# Constants
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_EXTRACTED_CHARS = 100_000
ALLOWED_MIME_TYPES = {"application/pdf", "text/csv", "text/plain"}

TRUNCATION_MARKER = "[Document truncated at 100,000 characters]"


class ExtractionResult(NamedTuple):
    """Result of text extraction from a document."""

    text: str
    char_count: int
    preview: str
    mime_type: str


def extract_text(content: bytes, filename: str, content_type: str) -> ExtractionResult:
    """Extract text from a document file.

    Args:
        content: Raw file bytes.
        filename: Original filename (for logging).
        content_type: MIME type of the file.

    Returns:
        ExtractionResult with extracted text, char count, preview, and mime type.

    Raises:
        ValueError: If content type is unsupported, text is too short,
                    or PDF is encrypted/image-only.
    """
    if content_type not in ALLOWED_MIME_TYPES:
        raise ValueError(f"Unsupported file type: {content_type}")

    # Route to type-specific extractor
    if content_type == "application/pdf":
        text = _extract_pdf(content)
    elif content_type == "text/csv":
        text = _extract_csv(content)
    else:
        text = _extract_txt(content)

    # Quality validation: reject near-empty results
    if len(text.strip()) < 10:
        raise ValueError(
            f"Extracted text too short ({len(text.strip())} chars). "
            "The document may be scanned/image-only or empty."
        )

    # Truncate if needed
    if len(text) > MAX_EXTRACTED_CHARS:
        text = text[:MAX_EXTRACTED_CHARS] + f"\n\n{TRUNCATION_MARKER}"

    preview = text[:200]
    char_count = len(text)

    return ExtractionResult(
        text=text,
        char_count=char_count,
        preview=preview,
        mime_type=content_type,
    )


def _extract_pdf(content: bytes) -> str:
    """Extract text from PDF using pypdf (plain text, pages joined by blank lines).

    Args:
        content: Raw PDF bytes.

    Returns:
        Plain text concatenated from all pages.

    Raises:
        ValueError: If the PDF is encrypted or cannot be opened.
    """
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            # PDFs with an empty user password are readable; anything else is rejected
            if not reader.decrypt(""):
                raise ValueError("PDF is encrypted: cannot extract text without the password.")
        pages = [page.extract_text() for page in reader.pages]
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            f"Cannot open PDF: {exc}. The file may be encrypted or corrupted."
        ) from exc

    return "\n\n".join(pages)


def _extract_csv(content: bytes) -> str:
    """Extract text from CSV as pipe-delimited table.

    Args:
        content: Raw CSV bytes (UTF-8 or Latin-1).

    Returns:
        Pipe-delimited text representation of the CSV.

    Raises:
        ValueError: If the CSV is empty.
    """
    text_content = _decode_bytes(content)

    reader = csv.reader(io.StringIO(text_content))
    rows = list(reader)

    if not rows:
        raise ValueError("CSV file is empty")

    lines = [" | ".join(row) for row in rows]
    return "\n".join(lines)


def _extract_txt(content: bytes) -> str:
    """Extract text from plain text file.

    Args:
        content: Raw text bytes (UTF-8 or Latin-1).

    Returns:
        Decoded text string.
    """
    return _decode_bytes(content)


def _decode_bytes(content: bytes) -> str:
    """Decode bytes with UTF-8, falling back to Latin-1.

    Args:
        content: Raw bytes.

    Returns:
        Decoded string.
    """
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1", errors="replace")
