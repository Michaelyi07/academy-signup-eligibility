"""One or more test cases for each of the 12 signup_states (acceptance #1),
plus the entitlement-zero case (acceptance #2) and the 404 error path."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app import service
from app.schemas import CourseNotFoundError, SignupState, ViewerContext
from tests.conftest import FIXED_NOW

ANON = ViewerContext(contact_id=None, logged_in=False, phone_authorized=False)


def viewer(contact):
    return ViewerContext(
        contact_id=contact.id, logged_in=True, phone_authorized=contact.phone_authorized
    )


def run_check(course, viewer_ctx, seed):
    seed.commit()
    return service.check(
        course.id, viewer_ctx, seed.s, clock=lambda: FIXED_NOW
    )


# ---------------------------------------------------------------- 1. finished
def test_state_finished(seed):
    course = seed.course(period_end=FIXED_NOW - timedelta(seconds=1))
    c = seed.contact()
    assert run_check(course, viewer(c), seed).signup_state is SignupState.FINISHED


# ---------------------------------------------------------------- 2. closed
def test_state_closed_cancelled_course(seed):
    course = seed.course(status="cancelled", cancelled=True)
    c = seed.contact()
    result = run_check(course, viewer(c), seed)
    assert result.signup_state is SignupState.CLOSED
    assert result.reasons == ("course_cancelled",)


def test_state_closed_signup_switch(seed):
    course = seed.course(signup_closed=True)
    c = seed.contact()
    result = run_check(course, viewer(c), seed)
    assert result.signup_state is SignupState.CLOSED
    assert result.reasons == ("signup_closed",)


def test_state_closed_quota_and_waitlist_full(seed):
    course = seed.course(quota=1, waitlist_quota=1)
    c = seed.contact()
    other = seed.contact()
    seed.registration(course.id, other.id, status="registered")
    seed.registration(course.id, seed.contact().id, status="waitlisted")
    assert run_check(course, viewer(c), seed).signup_state is SignupState.CLOSED


# ---------------------------------------------------------------- 3. not_open
def test_state_not_open_before_signup_window(seed):
    course = seed.course(signup_open_at=FIXED_NOW + timedelta(days=1))
    c = seed.contact()
    assert run_check(course, viewer(c), seed).signup_state is SignupState.NOT_OPEN


# ---------------------------------------------------------------- 4. application
def test_state_application_delivery_mode(seed):
    course = seed.course(delivery_mode="application")
    c = seed.contact()
    result = run_check(course, viewer(c), seed)
    assert result.signup_state is SignupState.APPLICATION


# ------------------------------------------------- 5. signed_up/waitlisted/pending_review
def test_state_signed_up_existing_registration(seed):
    course = seed.course()
    c = seed.contact()
    seed.registration(course.id, c.id, status="registered")
    result = run_check(course, viewer(c), seed)
    assert result.signup_state is SignupState.SIGNED_UP


def test_state_waitlisted_existing_registration(seed):
    course = seed.course()
    c = seed.contact()
    seed.registration(course.id, c.id, status="waitlisted")
    assert run_check(course, viewer(c), seed).signup_state is SignupState.WAITLISTED


def test_state_pending_review_existing_registration(seed):
    course = seed.course()
    c = seed.contact()
    seed.registration(course.id, c.id, status="pending_review")
    assert run_check(course, viewer(c), seed).signup_state is SignupState.PENDING_REVIEW


def test_cancelled_registration_is_not_valid(seed):
    """A cancelled registration must NOT short-circuit; viewer continues down
    the judging order and lands on can_signup."""
    course = seed.course()
    c = seed.contact()
    seed.registration(course.id, c.id, status="cancelled")
    assert run_check(course, viewer(c), seed).signup_state is SignupState.CAN_SIGNUP


# ---------------------------------------------------------------- 6. need_auth
def test_state_need_auth_not_logged_in(seed):
    course = seed.course()
    assert run_check(course, ANON, seed).signup_state is SignupState.NEED_AUTH


def test_state_need_auth_phone_not_authorized(seed):
    course = seed.course()
    c = seed.contact(phone_authorized=False)
    result = run_check(course, viewer(c), seed)
    assert result.signup_state is SignupState.NEED_AUTH
    assert result.reasons == ("phone_auth_required",)


# ---------------------------------------------------------------- 7. need_member
def test_state_need_member_without_membership(seed):
    course = seed.course(audience="member_only")
    c = seed.contact()
    assert run_check(course, viewer(c), seed).signup_state is SignupState.NEED_MEMBER


def test_state_need_member_expired_membership(seed):
    course = seed.course(audience="member_only")
    c = seed.contact()
    seed.membership(c.id, status="expired")
    assert run_check(course, viewer(c), seed).signup_state is SignupState.NEED_MEMBER


def test_state_need_member_about_to_expire_is_valid(seed):
    """Membership status 'about_to_expire' counts as valid (CRM rule)."""
    course = seed.course(audience="member_only")
    c = seed.contact()
    seed.membership(c.id, status="about_to_expire")
    assert run_check(course, viewer(c), seed).signup_state is SignupState.CAN_SIGNUP


def test_state_need_auth_precedes_need_member(seed):
    """member_only course + anonymous viewer -> need_auth (step 6 beats step 7)."""
    course = seed.course(audience="member_only")
    assert run_check(course, ANON, seed).signup_state is SignupState.NEED_AUTH


# ------------------------------------------------------------ 8. no_entitlement
def test_state_no_entitlement_zero_balance(seed):
    """Acceptance #2: member with benefit balance 0 querying an entitlement
    course period returns no_entitlement."""
    cat = seed.category(deductible=True)
    course = seed.course(fee_mode="entitlement", category_id=cat.id)
    c = seed.contact()
    seed.membership(c.id, status="active")
    seed.equity(c.id, cat.id, balance=0)
    result = run_check(course, viewer(c), seed)
    assert result.signup_state is SignupState.NO_ENTITLEMENT
    assert result.reasons == ("entitlement_balance_zero",)


def test_no_entitlement_skipped_when_balance_positive(seed):
    cat = seed.category(deductible=True)
    course = seed.course(fee_mode="entitlement", category_id=cat.id)
    c = seed.contact()
    seed.membership(c.id, status="active")
    seed.equity(c.id, cat.id, balance=3)
    assert run_check(course, viewer(c), seed).signup_state is SignupState.CAN_SIGNUP


def test_no_entitlement_skipped_when_category_not_deductible(seed):
    cat = seed.category(deductible=False)
    course = seed.course(fee_mode="entitlement", category_id=cat.id)
    c = seed.contact()
    seed.membership(c.id, status="active")
    seed.equity(c.id, cat.id, balance=0)
    assert run_check(course, viewer(c), seed).signup_state is SignupState.CAN_SIGNUP


# --------------------------------------------------------- 9. waitlist_available
def test_state_waitlist_available_quota_full(seed):
    course = seed.course(quota=1, waitlist_quota=2)
    c = seed.contact()
    seed.registration(course.id, seed.contact().id, status="registered")
    result = run_check(course, viewer(c), seed)
    assert result.signup_state is SignupState.WAITLIST_AVAILABLE


# ---------------------------------------------------------------- 11. can_signup
def test_state_can_signup_public_course_non_member(seed):
    """Non-member of a public course, phone authorized -> can_signup."""
    course = seed.course()
    c = seed.contact()
    result = run_check(course, viewer(c), seed)
    assert result.signup_state is SignupState.CAN_SIGNUP
    assert result.reasons == ()


def test_state_can_signup_member_only_with_active_membership(seed):
    course = seed.course(audience="member_only")
    c = seed.contact()
    seed.membership(c.id, status="active")
    assert run_check(course, viewer(c), seed).signup_state is SignupState.CAN_SIGNUP


def test_state_can_signup_member_only_membership_expiring_boundary(seed):
    """valid_until exactly == now is NOT valid anymore (rule: valid_until > now)."""
    course = seed.course(audience="member_only")
    c = seed.contact()
    seed.membership(c.id, status="about_to_expire", valid_until=FIXED_NOW)
    assert run_check(course, viewer(c), seed).signup_state is SignupState.NEED_MEMBER


# ------------------------------------------------------------ 404 error path
def test_course_not_found_missing(seed):
    seed.commit()
    with pytest.raises(CourseNotFoundError):
        service.check(uuid.uuid4(), ANON, seed.s, clock=lambda: FIXED_NOW)


def test_course_not_found_not_visible(seed):
    course = seed.course(visible=False)
    seed.commit()
    with pytest.raises(CourseNotFoundError):
        service.check(course.id, ANON, seed.s, clock=lambda: FIXED_NOW)


def test_course_not_found_soft_deleted(seed):
    course = seed.course()
    course.deleted_at = FIXED_NOW
    seed.commit()
    with pytest.raises(CourseNotFoundError):
        service.check(course.id, ANON, seed.s, clock=lambda: FIXED_NOW)
