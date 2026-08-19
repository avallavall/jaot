"""Whether this server can hold an upload, asked before it accepts one.

An uploaded model file is written to the temporary filesystem twice: once by
Starlette, which spools any multipart part over 1 MB to a file, and once by the
importer, which needs a real path to hand to SCIP. The containers mount ``/tmp``
as a tmpfs — 256 MB in production, 64 MB in local development — while the import
endpoint advertises 500 MB, so an ordinary upload can ask for more room than the
machine has.

What that looked like from the browser: the file uploaded for two minutes and
then failed with a sentence about the server's disk. What it looked like before
the truncation fix that came first: the upload was silently cut short and SCIP
solved a different model.

Content-Length is known before a byte of the body is read, so the answer is
available at the door. Refusing there costs the user nothing and tells them
something they can act on.
"""

from __future__ import annotations

import shutil
import tempfile

#: Copies of the upload that must fit at once: Starlette's spooled part and the
#: file the importer writes for SCIP.
_COPIES_ON_DISK = 2

#: Room left over for everything else the container writes to /tmp while an
#: import runs — an export, another solve's LP file, a second upload.
_HEADROOM_BYTES = 32 * 1024 * 1024


def temp_space_free() -> int:
    """Bytes free on the filesystem holding the temporary directory."""
    return shutil.disk_usage(tempfile.gettempdir()).free


def _mb(value: int) -> int:
    return value // (1024 * 1024)


def upload_refusal(
    content_length: int, *, free_bytes: int | None = None
) -> dict[str, object] | None:
    """The refusal body for an upload that cannot be stored, or None when it can.

    The sentence is for whoever chose the file: how big it is, how much this
    server can take, and what to do instead. What an operator needs — that the
    container's ``/tmp`` is the thing to grow — belongs in the deployment
    documentation, not in a message to somebody who cannot act on it.

    Shaped like every other refusal in the API: an English ``detail``, which is
    the contract, plus a ``code`` and its ``params`` for a page that renders it
    in the reader's language.
    """
    free = temp_space_free() if free_bytes is None else free_bytes
    room = free - _HEADROOM_BYTES
    if room > 0 and content_length * _COPIES_ON_DISK <= room:
        return None

    size_mb = _mb(content_length)
    capacity_mb = _mb(max(0, room // _COPIES_ON_DISK))
    return {
        "detail": (
            f"This file is {size_mb} MB and this server can take {capacity_mb} MB right now. "
            "Try a smaller model, or gzip the file and upload that."
        ),
        "code": "import.too_big_for_server",
        "params": {"size_mb": size_mb, "capacity_mb": capacity_mb},
    }
