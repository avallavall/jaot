"""Schemas for file import/export endpoints."""

from pydantic import BaseModel, Field

from app.schemas.optimization import OptimizationProblem

# --- Single source of truth for import file types and limits ---
SUPPORTED_FORMAT_EXTENSIONS = frozenset({".mps", ".lp", ".cip", ".json"})
GZIP_EXTENSIONS = frozenset({".mps.gz", ".lp.gz"})
ALL_EXTENSIONS = SUPPORTED_FORMAT_EXTENSIONS | GZIP_EXTENSIONS
MAX_IMPORT_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_JSON_SIZE = 10 * 1024 * 1024  # 10 MB
# Generous cap: real OptimizationProblem JSON is shallow (< 10 levels).
# Anything beyond 64 is a stack-exhaustion DoS attempt and is rejected
# before parsing. Safe cross-platform because it does not depend on
# sys.getrecursionlimit() or the CPython build's stack size.
MAX_JSON_DEPTH = 64


class FileImportMetadata(BaseModel):
    """Metadata about an imported optimization file."""

    source_format: str = Field(..., description="File extension (e.g., '.mps', '.lp')")
    num_variables: int = Field(..., description="Total number of variables")
    num_constraints: int = Field(..., description="Total number of constraints")
    num_integer: int = Field(..., description="Number of integer variables")
    num_binary: int = Field(..., description="Number of binary variables")
    num_continuous: int = Field(..., description="Number of continuous variables")
    estimated_credits: int = Field(..., description="Estimated credits for solving")
    file_size_bytes: int = Field(..., description="Size of uploaded file in bytes")
    original_filename: str = Field(..., description="Original filename")


class FileImportPreviewResponse(BaseModel):
    """Response for /import/preview — parsed problem + metadata."""

    problem: OptimizationProblem
    metadata: FileImportMetadata
