"""Integration tests for CV upload + parsing (requires PostgreSQL)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User

SAMPLE_MD = """# Dev Candidate

dev@example.com

SKILLS
Python, SQL, FastAPI

EXPERIENCE
Backend Engineer - ACME - 2021-01 to 2023-12
- Built REST APIs

EDUCATION
BSc Computer Science, Tech University, 2020
"""


@pytest.fixture
def client(_api_identity: dict[str, str]) -> TestClient:
    """Authorized API client wired to the test database (per-test user)."""
    from app.main import app

    return TestClient(app, headers={"Authorization": f"Bearer {_api_identity['token']}"})


def test_upload_md_cv_round_trip(client: TestClient) -> None:
    response = client.post(
        "/cvs",
        files={"file": ("cv.md", SAMPLE_MD.encode("utf-8"), "text/markdown")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "original"
    assert body["file_type"] == "md"
    parsed = body["parsed_content"]
    assert parsed["contact_email"] == "dev@example.com"
    assert "python" in [s.lower() for s in parsed["skills"]]
    listing = client.get("/cvs")
    assert listing.status_code == 200
    assert {r["id"] for r in listing.json()} >= {body["id"]}


def test_upload_validates_extension(client: TestClient) -> None:
    response = client.post(
        "/cvs",
        files={"file": ("malware.exe", b"MZ...", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "unsupported CV type" in response.json()["detail"]


def test_upload_validates_size(db, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    """Size limit is enforced by the service layer (no huge multipart needed)."""

    from app.config import reset_settings_cache
    from app.services.resumes import CVUploadError, upload_resume

    monkeypatch.setenv("MAX_CV_UPLOAD_MB", "1")
    reset_settings_cache()
    try:
        with Session(db) as session:
            user = User(email="size-test@example.com", display_name="Size Test")
            session.add(user)
            session.commit()
            with pytest.raises(CVUploadError, match="upload limit"):
                upload_resume(session, user, "big.md", b"x" * (2 * 1024 * 1024))
    finally:
        reset_settings_cache()


def test_upload_rejects_empty_file(client: TestClient) -> None:
    response = client.post("/cvs", files={"file": ("empty.md", b"", "text/markdown")})
    assert response.status_code == 400


def test_upload_pdf_round_trip(client: TestClient, tmp_path: Path) -> None:
    """Generate a CV PDF with WeasyPrint, upload it, verify parsed text."""
    html = (
        "<html><body><h1>Dev Candidate</h1>"
        "<p>dev@example.com</p>"
        "<h2>SKILLS</h2><p>Python, SQL, FastAPI</p>"
        "<h2>EXPERIENCE</h2><p>Backend Engineer - ACME - 2021-01 to 2023-12</p>"
        "<p>- Built REST APIs with FastAPI</p></body></html>"
    )
    from weasyprint import HTML

    pdf_path = tmp_path / "cv.pdf"
    HTML(string=html).write_pdf(str(pdf_path))
    pdf_bytes = pdf_path.read_bytes()
    assert pdf_bytes.startswith(b"%PDF")

    response = client.post(
        "/cvs",
        files={"file": ("cv.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    parsed = response.json()["parsed_content"]
    assert parsed["contact_email"] == "dev@example.com"
    assert "python" in [s.lower() for s in parsed["skills"]]


def test_upload_scanned_pdf_rejected_with_clear_error(client: TestClient) -> None:
    """A PDF with no text layer (scanned image) must fail loudly."""
    header = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    response = client.post(
        "/cvs",
        files={"file": ("scan.pdf", header + b"\n" * 200, "application/pdf")},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "no extractable text" in detail or "not a readable PDF" in detail
