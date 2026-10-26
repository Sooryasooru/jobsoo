"""Regression tests: malformed (non-UUID) resource ids must never produce a 500.

A non-UUID path parameter used to be handed straight to Postgres, which failed
with `invalid input syntax for type uuid`; SQLAlchemy surfaced that as an
unhandled DataError and FastAPI returned HTTP 500 on /cvs, /tailored and the
/job sub-routes. These tests pin the corrected behaviour: a malformed id is
indistinguishable from a missing one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

BAD_ID = "not-a-uuid"


def test_cv_detail_with_malformed_id_is_404(api: TestClient) -> None:
    response = api.get(f"/cvs/{BAD_ID}")
    assert response.status_code == 404
    assert response.json()["detail"] == "cv not found"


def test_tailored_detail_with_malformed_id_is_404(api: TestClient) -> None:
    response = api.get(f"/tailored/{BAD_ID}")
    assert response.status_code == 404
    assert response.json()["detail"] == "tailored resume not found"


@pytest.mark.parametrize("action", ["submit", "approve", "reject", "pdf"])
def test_tailored_actions_with_malformed_id_are_client_errors(api: TestClient, action: str) -> None:
    response = (
        api.post(f"/tailored/{BAD_ID}/{action}")
        if action != "pdf"
        else api.get(f"/tailored/{BAD_ID}/pdf")
    )
    assert response.status_code in (400, 404)
    assert "not found" in response.json()["detail"].lower()


def test_tailored_create_with_malformed_resume_id_is_client_error(api: TestClient) -> None:
    response = api.post(
        "/tailored",
        params={"resume_id": BAD_ID, "job_id": BAD_ID},
    )
    assert response.status_code in (400, 404)
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/jobs/{id}"),
        ("get", "/jobs/{id}/match"),
        ("post", "/jobs/{id}/match"),
        ("get", "/jobs/{id}/requirements"),
        ("post", "/jobs/{id}/requirements/extract"),
        ("post", "/jobs/{id}/evidence"),
    ],
)
def test_job_routes_with_malformed_id_are_404(api: TestClient, method: str, path: str) -> None:
    url = path.format(id=BAD_ID)
    response = api.get(url) if method == "get" else api.post(url)
    assert response.status_code == 404
    assert response.json()["detail"] == "job not found"


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/applications/{id}"),
        ("get", "/applications/{id}/events"),
        ("get", "/applications/{id}/availability"),
        ("post", "/applications/{id}/status"),
        ("post", "/applications/{id}/confirm-submit"),
    ],
)
def test_application_routes_with_malformed_id_are_404(
    api: TestClient, method: str, path: str
) -> None:
    url = path.format(id=BAD_ID)
    if method == "get":
        response = api.get(url)
    else:
        # Body must be valid so FastAPI's validation does not mask the 404.
        payload = {"status": "submitted"} if url.endswith("/status") else {}
        response = api.post(url, json=payload)
    assert response.status_code == 404
    assert response.json()["detail"] == "application not found"
