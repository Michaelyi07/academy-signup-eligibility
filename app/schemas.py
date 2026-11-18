"""Public schemas: viewer context, signup states, eligibility result."""
from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime


class SignupState(str, enum.Enum):
    """The 12 signup states. HTTP 404 (course missing / not visible) is an
    error path raised as CourseNotFoundError, NOT one of the 12 states."""

    FINISHED = "finished"
    CLOSED = "closed"
    NOT_OPEN = "not_open"
    APPLICATION = "application"
    SIGNED_UP = "signed_up"
    WAITLISTED = "waitlisted"
    PENDING_REVIEW = "pending_review"
    NEED_AUTH = "need_auth"
    NEED_MEMBER = "need_member"
    NO_ENTITLEMENT = "no_entitlement"
    WAITLIST_AVAILABLE = "waitlist_available"
    CAN_SIGNUP = "can_signup"


@dataclass(frozen=True)
class ViewerContext:
    """Identity of the caller resolved from the mini-program session.

    ``contact_id`` is None when the caller is not logged in.
    ``phone_authorized`` means phone-number authorization completed.
    """

    contact_id: uuid.UUID | None = None
    logged_in: bool = False
    phone_authorized: bool = False


@dataclass(frozen=True)
class EligibilityResult:
    signup_state: SignupState
    reasons: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict:
        return {
            "signup_state": self.signup_state.value,
            "reasons": list(self.reasons),
        }


class CourseNotFoundError(LookupError):
    """Course missing, invisible, or soft-deleted => maps to HTTP 404."""
