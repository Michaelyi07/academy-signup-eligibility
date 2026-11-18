"""FastAPI layer: exposes the eligibility service over HTTP.

404 mapping: CourseNotFoundError -> HTTP 404 {"detail": "course_not_found"}.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import service
from .db import make_session
from .schemas import CourseNotFoundError, ViewerContext

router = APIRouter(prefix="/academy", tags=["academy"])


def get_db() -> Session:
    db = make_session()
    try:
        yield db
    finally:
        db.close()


class EligibilityOut(BaseModel):
    signup_state: str
    reasons: list[str] = Field(default_factory=list)


@router.get(
    "/sessions/{session_id}/signup-eligibility",
    response_model=EligibilityOut,
    responses={404: {"description": "course not found or not visible"}},
)
def get_signup_eligibility(
    session_id: uuid.UUID,
    # viewer identity: in production these come from the mini-program session
    # (S3-MINI auth). Here they are explicit query params for service-to-service
    # calls from the course-detail and registration interfaces.
    contact_id: uuid.UUID | None = None,
    logged_in: bool = False,
    phone_authorized: bool = False,
    db: Session = Depends(get_db),
) -> EligibilityOut:
    viewer = ViewerContext(
        contact_id=contact_id, logged_in=logged_in, phone_authorized=phone_authorized
    )
    try:
        result = service.check(session_id, viewer, db)
    except CourseNotFoundError:
        raise HTTPException(status_code=404, detail="course_not_found")
    return EligibilityOut(**result.as_dict())
