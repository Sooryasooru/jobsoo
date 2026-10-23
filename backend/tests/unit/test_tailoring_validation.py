"""Unit tests for deterministic tailored-CV claim validation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.schemas.tailoring import TailoredBullet, TailoredContent, TailoredSection
from app.tailoring.validation import validate_tailored_content

PARSED: dict[str, Any] = {
    "experiences": [
        {
            "title": "Backend Engineer",
            "company": "ACME",
            "bullets": [
                "Built 3 REST APIs in Python with Django",
                "Reduced query time by 40% via SQL indexing",
            ],
        }
    ],
    "education": [{"degree": "BSc Computer Science", "institution": "XYZ Uni", "year": "2021"}],
    "skills": ["Python", "SQL", "Docker"],
    "projects": ["Buildtool: open-source packaging tool in Python"],
    "certifications": ["AWS Cloud Practitioner"],
}


def make_resume() -> SimpleNamespace:
    return SimpleNamespace(parsed_content=PARSED)


ORIGINAL = {
    "experiences": [
        ". ".join(["Backend Engineer - ACME", str(b)]) for b in PARSED["experiences"][0]["bullets"]
    ],
    "skills": PARSED["skills"],
    "projects": PARSED["projects"],
    "certifications": PARSED["certifications"],
    "education": ["BSc Computer Science | XYZ Uni"],
}


def bullet(text: str, refs: list[str]) -> TailoredBullet:
    return TailoredBullet(text=text, evidence_refs=refs)


def test_supported_reword_passes() -> None:
    content = TailoredContent(
        sections=[
            TailoredSection(
                name="experiences",
                items=[
                    bullet("Built REST APIs in Python with Django (ACME)", ["exp[0].bullets[0]"]),
                ],
            ),
        ]
    )
    result = validate_tailored_content(make_resume(), content, ORIGINAL)  # type: ignore[arg-type]
    assert result.is_truthful
    assert result.change_summary.reworded_bullets == 1


def test_invented_skill_rejected() -> None:
    content = TailoredContent(
        sections=[
            TailoredSection(
                name="experiences",
                items=[
                    bullet(
                        "Designed Kubernetes clusters on GCP with Terraform", ["exp[0].bullets[0]"]
                    ),
                ],
            ),
        ]
    )
    result = validate_tailored_content(make_resume(), content, ORIGINAL)  # type: ignore[arg-type]
    assert not result.is_truthful
    assert result.unsupported_claims[0].section == "experiences"
    # The untruthful bullet must not survive into validated content.
    assert result.content.sections == []


def test_bad_evidence_ref_rejected() -> None:
    content = TailoredContent(
        sections=[
            TailoredSection(name="skills", items=[bullet("Python", ["skill[9]"])]),
        ]
    )
    result = validate_tailored_content(make_resume(), content, ORIGINAL)  # type: ignore[arg-type]
    assert not result.is_truthful
    assert "does not resolve" in result.unsupported_claims[0].reason


def test_invented_number_rejected() -> None:
    content = TailoredContent(
        sections=[
            TailoredSection(
                name="experiences",
                items=[
                    bullet("Built 99 REST APIs in Python with Django", ["exp[0].bullets[0]"]),
                ],
            ),
        ]
    )
    result = validate_tailored_content(make_resume(), content, ORIGINAL)  # type: ignore[arg-type]
    assert not result.is_truthful
    assert "numbers not present" in result.unsupported_claims[0].reason


def test_verbatim_number_allowed() -> None:
    content = TailoredContent(
        sections=[
            TailoredSection(
                name="experiences",
                items=[
                    bullet("Reduced query time by 40% via SQL indexing", ["exp[0].bullets[1]"]),
                ],
            ),
        ]
    )
    result = validate_tailored_content(make_resume(), content, ORIGINAL)  # type: ignore[arg-type]
    assert result.is_truthful


def test_removes_only_bad_bullets_keeps_good_ones() -> None:
    content = TailoredContent(
        sections=[
            TailoredSection(
                name="skills",
                items=[
                    bullet("Python", ["skill[0]"]),
                    bullet("Quantum Computing expert", ["skill[0]"]),
                ],
            ),
        ]
    )
    result = validate_tailored_content(make_resume(), content, ORIGINAL)  # type: ignore[arg-type]
    skill_section = result.content.sections[0]
    assert [b.text for b in skill_section.items] == ["Python"]
    assert len(result.unsupported_claims) == 1
