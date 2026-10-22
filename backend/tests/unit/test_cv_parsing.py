"""Unit tests for deterministic CV text parsing."""

from __future__ import annotations

from app.cv.parsing import parse_cv_text

SAMPLE = """
Dev Candidate
dev@example.com | +971 50 123 4567

SKILLS
Python, SQL, FastAPI, PostgreSQL, Pytest; Pandas

EXPERIENCE
Backend Engineer - ACME Ltd - 2021-01 to 2024-02
- Built APIs with Python and FastAPI
- Managed PostgreSQL schemas
Junior Developer - StartupCo - 2020-06 to 2020-12
- Fixed bugs in Django app

EDUCATION
BSc Computer Science, University of Technology, 2020

PROJECTS
Attendance tracker written in Python
Dashboard with SQL analytics

CERTIFICATIONS
AWS Certified Developer
"""


def test_extracts_contact_information() -> None:
    parsed = parse_cv_text(SAMPLE)
    assert parsed.contact_email == "dev@example.com"
    assert parsed.contact_phone and "971" in parsed.contact_phone


def test_extracts_skills() -> None:
    parsed = parse_cv_text(SAMPLE)
    lowered = [s.lower() for s in parsed.skills]
    assert "python" in lowered
    assert "sql" in lowered
    assert "fastapi" in lowered


def test_extracts_experiences_with_company_and_bullets() -> None:
    parsed = parse_cv_text(SAMPLE)
    assert len(parsed.experiences) == 2
    first = parsed.experiences[0]
    assert first.title == "Backend Engineer"
    assert first.company == "ACME Ltd"
    assert any("FastAPI" in b for b in first.bullets)


def test_extracts_education_year() -> None:
    parsed = parse_cv_text(SAMPLE)
    assert parsed.education
    assert parsed.education[0].year == "2020"


def test_projects_and_certifications() -> None:
    parsed = parse_cv_text(SAMPLE)
    assert any("Attendance" in p for p in parsed.projects)
    assert any("AWS" in c for c in parsed.certifications)


def test_sparse_cv_yields_unknown_not_invented() -> None:
    parsed = parse_cv_text("Just a plain text CV with no sections.")
    assert parsed.skills == []
    assert parsed.experiences == []
    assert any("No explicit work-experience section" in n for n in parsed.parse_notes)


def test_never_invents_missing_fields() -> None:
    parsed = parse_cv_text("Name only here")
    assert parsed.contact_email is None
    assert parsed.contact_phone is None
    assert parsed.education == []
