"""CV upload pipeline: validate, store outside web root, parse, persist."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.cv.parsing import parse_cv_text, parse_resume_file, parsed_cv_to_dict
from app.logging import get_logger
from app.models import Resume, User

logger = get_logger(__name__)

_ALLOWED_TYPE_BY_EXTENSION = {".pdf": "pdf", ".docx": "docx", ".md": "md", ".txt": "txt"}


class CVUploadError(ValueError):
    """Raised with a user-safe message when a CV upload is rejected."""


def _do_not_contain(path: Path) -> None:
    try:
        with open(path, "rb") as fh:
            head = fh.read(6)
        if head.startswith(b"%PDF") and b"/JS" in head:
            # pdfminer won't execute JS, but PDFs with embedded JS are not CVs.
            raise CVUploadError("PDF contains embedded scripts and is not accepted")
    except CVUploadError:
        raise
    except OSError as exc:
        raise CVUploadError("could not read uploaded file") from exc


def validate_upload(filename: str, size_bytes: int) -> str:
    """Validate extension and size; returns the detected file type."""
    settings = get_settings()
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_TYPE_BY_EXTENSION:
        raise CVUploadError(
            f"unsupported CV type {suffix!r}; allowed: {sorted(_ALLOWED_TYPE_BY_EXTENSION)}"
        )
    if size_bytes <= 0:
        raise CVUploadError("uploaded file is empty")
    if size_bytes > settings.max_cv_upload_bytes:
        raise CVUploadError(f"file exceeds the {settings.max_cv_upload_mb} MB CV upload limit")
    return _ALLOWED_TYPE_BY_EXTENSION[suffix]


def store_upload(user: User, filename: str, content: bytes) -> Path:
    """Persist the upload under the private upload dir and return its path."""
    settings = get_settings()
    upload_dir = Path(settings.cv_upload_dir)
    suffix = Path(filename).suffix.lower()
    upload_dir.mkdir(parents=True, exist_ok=True)

    stored_name = (
        f"{user.id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}{suffix}"
    )
    stored_path = upload_dir / stored_name
    resolved_root = upload_dir.resolve()
    if not stored_path.resolve().parent == resolved_root:
        raise CVUploadError("invalid upload filename")
    stored_path.write_bytes(content)
    _do_not_contain(stored_path)
    return stored_path


def upload_resume(session: Session, user: User, original_filename: str, content: bytes) -> Resume:
    """Full upload flow. Raises CVUploadError for invalid inputs."""
    file_type = validate_upload(original_filename, len(content))
    stored_path = store_upload(user, original_filename, content)
    _do_not_contain(stored_path)

    try:
        text, _notes = parse_resume_file(stored_path, file_type)
    except ValueError as exc:
        stored_path.unlink(missing_ok=True)
        raise CVUploadError(str(exc)) from exc
    if file_type in ("pdf", "docx") and not text.strip():
        stored_path.unlink(missing_ok=True)
        raise CVUploadError("document contained no extractable text (scanned file?)")

    parsed = parse_cv_text(text)

    resume = Resume(
        user_id=user.id,
        kind="original",
        original_filename=original_filename[:512],
        file_type=file_type,
        file_size_bytes=len(content),
        file_path=str(stored_path),
        file_checksum_sha256=hashlib.sha256(content).hexdigest(),
        parsed_content=parsed_cv_to_dict(parsed),
        parse_notes=parsed.parse_notes,
    )
    session.add(resume)
    session.commit()
    # Do not log file contents - only identifiers (docs/security.md).
    logger.info("resume.uploaded", resume_id=resume.id, file_type=file_type)
    return resume
