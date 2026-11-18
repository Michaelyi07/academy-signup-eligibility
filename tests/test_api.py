"""HTTP layer: 404 mapping and one happy-path contract test (TestClient)."""
from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import router


def make_client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_http_404_for_missing_course(seed):
    seed.commit()
    client = make_client()
    resp = client.get(f"/academy/sessions/{uuid.uuid4()}/signup-eligibility")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "course_not_found"


def test_http_404_for_invisible_course(seed):
    course = seed.course(visible=False)
    seed.commit()
    client = make_client()
    resp = client.get(f"/academy/sessions/{course.id}/signup-eligibility")
    assert resp.status_code == 404


def test_http_can_signup_contract(seed):
    course = seed.course()
    c = seed.contact()
    seed.commit()
    client = make_client()
    resp = client.get(
        f"/academy/sessions/{course.id}/signup-eligibility",
        params={
            "contact_id": str(c.id),
            "logged_in": True,
            "phone_authorized": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"signup_state": "can_signup", "reasons": []}


def test_http_need_auth_anonymous(seed):
    course = seed.course()
    seed.commit()
    client = make_client()
    resp = client.get(f"/academy/sessions/{course.id}/signup-eligibility")
    assert resp.status_code == 200
    assert resp.json() == {"signup_state": "need_auth", "reasons": ["login_required"]}
