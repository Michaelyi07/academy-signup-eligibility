"""enrollment_eligibility_service.check(session_id, viewer) - READ-ONLY.

Judging order (verbatim from the work order, then operationalized):

 0. course missing / not visible / soft-deleted          -> CourseNotFoundError (HTTP 404)
 1. course period finished                               -> finished
 2. cancelled or signup_closed                           -> closed
 3. not signed up_open_at (now < signup_open_at)         -> not_open
 4. delivery_mode = application                          -> application
 5. current contact has a valid registration for this
    course (by event-module registration status)         -> signed_up | waitlisted | pending_review
 6. not logged in or phone authorization not completed   -> need_auth
 7. audience = member_only and no valid membership
    (CRM status active or about_to_expire)               -> need_member
 8. fee_mode = entitlement, course category within
    deductible range and equity balance is 0             -> no_entitlement
 9. quota full and waiting list not full                 -> waitlist_available
10. places and waitlists full                            -> closed
11. others                                               -> can_signup

Non-members of public courses can reach can_signup after completing phone
number authorization (steps 6-7 above encode exactly that).

The service performs NO write operations. Every statement it executes is a
SELECT; ``tests/test_readonly_invariants.py`` asserts this mechanically.
"""
from __future__ import annotations

import typing as t
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import gateways, models
from .schemas import CourseNotFoundError, EligibilityResult, SignupState, ViewerContext

if t.TYPE_CHECKING:  # pragma: no cover
    from .gateways import CrmGateway, EventGateway

VALID_MEMBERSHIP_STATUSES = ("active", "about_to_expire")

REGISTRATION_STATE_MAP = {
    "registered": SignupState.SIGNED_UP,
    "waitlisted": SignupState.WAITLISTED,
    "pending_review": SignupState.PENDING_REVIEW,
}


def default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _live_course(db: Session, session_id: uuid.UUID) -> models.Course | None:
    """Live = present, visible, not soft-deleted. Cancelled courses are NOT
    hidden here: they resolve to state ``closed`` per judging order step 2."""
    return (
        db.query(models.Course)
        .filter(
            models.Course.id == session_id,
            models.Course.visible.is_(True),
            models.Course.deleted_at.is_(None),
        )
        .first()
    )


def check(
    session_id: uuid.UUID,
    viewer: ViewerContext,
    db: Session,
    crm: CrmGateway | None = None,
    events: EventGateway | None = None,
    clock: t.Callable[[], datetime] | None = None,
) -> EligibilityResult:
    """Return the signup_state for ``viewer`` on course session ``session_id``.

    Read-only: the bound Session must never receive INSERT/UPDATE/DELETE from
    this function. ``crm``/``events`` default to the DB-backed mock adapters
    (integration point: pass real S2-CRM / S3-MINI adapters here).
    """
    now = (clock or default_clock)()
    crm = crm or gateways.DbBackedCrmGateway(db)
    events = events or gateways.DbBackedEventGateway(db)

    course = _live_course(db, session_id)
    if course is None:
        raise CourseNotFoundError(f"course session {session_id} not found or not visible")

    # 1. course period finished
    if course.period_end is not None and now > course.period_end:
        return EligibilityResult(SignupState.FINISHED, ("period_finished",))

    # 2. cancelled or signup_closed
    if course.status == "cancelled" or course.cancelled:
        return EligibilityResult(SignupState.CLOSED, ("course_cancelled",))
    if course.signup_closed:
        return EligibilityResult(SignupState.CLOSED, ("signup_closed",))

    # 3. not signed up_open_at yet
    if course.signup_open_at is not None and now < course.signup_open_at:
        return EligibilityResult(SignupState.NOT_OPEN, ("signup_not_open",))

    # 4. application-mode delivery (application transfer process)
    if course.delivery_mode == "application":
        return EligibilityResult(SignupState.APPLICATION, ("application_mode",))

    # 5. current contact already holds a valid registration for this course
    if viewer.contact_id is not None:
        reg = events.get_active_registration(course.id, viewer.contact_id)
        if reg is not None and reg.status in REGISTRATION_STATE_MAP:
            state = REGISTRATION_STATE_MAP[reg.status]
            return EligibilityResult(state, (f"existing_registration_{reg.status}",))

    # 6. not logged in, or phone-number authorization not completed
    if not viewer.logged_in:
        return EligibilityResult(SignupState.NEED_AUTH, ("login_required",))
    if not viewer.phone_authorized:
        return EligibilityResult(SignupState.NEED_AUTH, ("phone_auth_required",))

    # 7. member_only audience requires a valid membership (active / about_to_expire)
    if course.audience == "member_only":
        membership = crm.get_membership(viewer.contact_id)
        valid = (
            membership is not None
            and membership.status in VALID_MEMBERSHIP_STATUSES
            and membership.valid_until > now
        )
        if not valid:
            return EligibilityResult(SignupState.NEED_MEMBER, ("member_only_no_valid_membership",))

    # 8. entitlement fee mode: category deductible and equity balance is 0
    if course.fee_mode == "entitlement" and course.category_id is not None:
        category = (
            db.query(models.CourseCategory)
            .filter(
                models.CourseCategory.id == course.category_id,
                models.CourseCategory.deleted_at.is_(None),
            )
            .first()
        )
        if category is not None and category.entitlement_deductible:
            balance = crm.get_entitlement_balance(viewer.contact_id, category.id)
            if balance <= 0:
                return EligibilityResult(
                    SignupState.NO_ENTITLEMENT, ("entitlement_balance_zero",)
                )

    # 9./10. quota and waitlist
    confirmed = events.count_confirmed_registrations(course.id)
    waitlisted_n = events.count_waitlisted(course.id)
    if confirmed >= course.quota:
        if waitlisted_n < course.waitlist_quota:
            return EligibilityResult(
                SignupState.WAITLIST_AVAILABLE, ("quota_full_waitlist_open",)
            )
        return EligibilityResult(SignupState.CLOSED, ("quota_and_waitlist_full",))

    # 11. default
    return EligibilityResult(SignupState.CAN_SIGNUP, ())
