"""Acceptance #3: same input -> same result across repeated calls, and NO
INSERT or UPDATE (or DELETE) executed in the database during check().

The assertion is mechanical: a SQLAlchemy ``after_cursor_execute`` listener
records every statement the service issues while checking, then we grep the
recorded SQL for write verbs.
"""
from __future__ import annotations

import re
import uuid
from datetime import timedelta

from app import gateways, service
from app.schemas import ViewerContext
from tests.conftest import FIXED_NOW

WRITE_RE = re.compile(
    r"\b(INSERT\s+INTO|UPDATE\s+\w|DELETE\s+FROM|MERGE\s+INTO)\b", re.IGNORECASE
)


class StatementRecorder:
    def __init__(self, engine):
        self.statements: list[str] = []
        self._engine = engine
        from sqlalchemy import event

        event.listen(engine, "after_cursor_execute", self._record)

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def pop_writes(self) -> list[str]:
        writes = [s for s in self.statements if WRITE_RE.search(s)]
        self.statements.clear()
        return writes

    def detach(self):
        from sqlalchemy import event

        event.remove(self._engine, "after_cursor_execute", self._record)


def test_check_is_readonly_and_deterministic(seed):
    cat = seed.category(name="权益品类", deductible=True)
    course = seed.course(
        audience="member_only", fee_mode="entitlement", category_id=cat.id
    )
    c = seed.contact()
    seed.membership(c.id, status="active")
    seed.equity(c.id, cat.id, balance=2)
    seed.commit()

    viewer = ViewerContext(contact_id=c.id, logged_in=True, phone_authorized=True)
    recorder = StatementRecorder(seed.s.get_bind())

    # three repeated calls with identical inputs
    results = [
        service.check(course.id, viewer, seed.s, clock=lambda: FIXED_NOW)
        for _ in range(3)
    ]

    recorder.detach()

    # (a) determinism: same input -> same result every time
    assert all(r == results[0] for r in results)
    assert results[0].signup_state.value == "can_signup"

    # (b) read-only: zero INSERT/UPDATE/DELETE statements executed by check()
    # (c) sanity: the recorder did capture the service's SELECT traffic
    #     (guards against a silently broken listener reporting zero statements)
    recorded_selects = [
        s for s in recorder.statements if s.strip().upper().startswith("SELECT")
    ]
    writes = recorder.pop_writes()
    assert writes == [], f"check() executed write statements: {writes}"
    assert recorded_selects, "listener recorded no statements - assertion would be vacuous"


def test_check_readonly_across_all_states(seed):
    """Walk every reachable state and assert no write statement is issued."""
    from app.schemas import CourseNotFoundError

    cases = []

    cat = seed.category(name="权益品类B", deductible=True)
    cases.append(
        ("finished", seed.course(period_end=FIXED_NOW - timedelta(seconds=1)))
    )
    cases.append(("closed", seed.course(signup_closed=True)))
    cases.append(
        ("not_open", seed.course(signup_open_at=FIXED_NOW + timedelta(seconds=1)))
    )
    cases.append(("application", seed.course(delivery_mode="application")))
    ent_course = seed.course(audience="member_only", fee_mode="entitlement", category_id=cat.id)
    member_course = seed.course(audience="member_only")
    quota_course = seed.course(quota=1, waitlist_quota=1)
    normal_course = seed.course()
    c = seed.contact()
    seed.membership(c.id, status="active")
    seed.equity(c.id, cat.id, balance=0)
    seed.registration(quota_course.id, seed.contact().id, status="registered")
    seed.registration(normal_course.id, c.id, status="registered")
    seed.commit()

    viewer = ViewerContext(contact_id=c.id, logged_in=True, phone_authorized=True)
    recorder = StatementRecorder(seed.s.get_bind())

    exercised = []
    for _, course in cases:
        exercised.append(service.check(course.id, viewer, seed.s, clock=lambda: FIXED_NOW).signup_state.value)
    exercised.append(service.check(ent_course.id, viewer, seed.s, clock=lambda: FIXED_NOW).signup_state.value)
    exercised.append(service.check(member_course.id, viewer, seed.s, clock=lambda: FIXED_NOW).signup_state.value)
    exercised.append(service.check(quota_course.id, viewer, seed.s, clock=lambda: FIXED_NOW).signup_state.value)
    # viewer already registered on normal_course -> signed_up
    exercised.append(service.check(normal_course.id, viewer, seed.s, clock=lambda: FIXED_NOW).signup_state.value)

    # 404 path is also read-only
    try:
        service.check(uuid.uuid4(), viewer, seed.s, clock=lambda: FIXED_NOW)
    except CourseNotFoundError:
        pass

    recorder.detach()

    writes = recorder.pop_writes()
    assert writes == []
    # every reachable state in this walk produced its expected value
    assert set(exercised) == {
        "finished",
        "closed",
        "not_open",
        "application",
        "signed_up",
        "waitlist_available",
        "no_entitlement",
        "can_signup",
    }
