"""Interface files for cross-work-order dependencies (mock-first).

The brief says: "when relying on interfaces with other work orders, use an
interface file or mock first, and specify the connection points in the README".

Two gateways are depended on:

- ``CrmGateway``   <- S2-CRM (CRM core object: membership status, equity balance)
- ``EventGateway`` <- S3-MINI (member applet event module: registration records)

This module provides Protocol interfaces plus a DB-backed mock adapter used by
tests and local runs. Integration point for the core team: replace the adapter
bound in ``service.check(...)`` defaults with HTTP/RPC adapters for S2-CRM and
S3-MINI - the Protocol signatures below are the contract.

All adapters are READ-ONLY; none of them may issue INSERT/UPDATE/DELETE.
"""
from __future__ import annotations

import typing as t
import uuid
from dataclasses import dataclass
from datetime import datetime

from . import models

if t.TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class MembershipSnapshot:
    status: str  # 'active' | 'about_to_expire' | 'expired'
    valid_until: datetime


@dataclass(frozen=True)
class RegistrationSnapshot:
    status: str  # 'registered' | 'waitlisted' | 'pending_review'


class CrmGateway(t.Protocol):
    """S2-CRM connection point (read-only)."""

    def get_membership(self, contact_id: uuid.UUID) -> MembershipSnapshot | None: ...

    def get_entitlement_balance(
        self, contact_id: uuid.UUID, category_id: uuid.UUID
    ) -> int: ...


class EventGateway(t.Protocol):
    """S3-MINI event-module connection point (read-only)."""

    def get_active_registration(
        self, course_id: uuid.UUID, contact_id: uuid.UUID
    ) -> RegistrationSnapshot | None: ...

    def count_confirmed_registrations(self, course_id: uuid.UUID) -> int: ...

    def count_waitlisted(self, course_id: uuid.UUID) -> int: ...


class DbBackedCrmGateway:
    """Mock adapter reading CRM objects from the local tables.

    To be swapped for the real S2-CRM adapter at integration time.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_membership(
        self, contact_id: uuid.UUID
    ) -> MembershipSnapshot | None:
        row = (
            self._db.query(models.Membership)
            .filter(
                models.Membership.contact_id == contact_id,
                models.Membership.deleted_at.is_(None),
            )
            .first()
        )
        if row is None:
            return None
        return MembershipSnapshot(status=row.status, valid_until=row.valid_until)

    def get_entitlement_balance(
        self, contact_id: uuid.UUID, category_id: uuid.UUID
    ) -> int:
        row = (
            self._db.query(models.EntitlementEquity)
            .filter(
                models.EntitlementEquity.contact_id == contact_id,
                models.EntitlementEquity.category_id == category_id,
                models.EntitlementEquity.deleted_at.is_(None),
            )
            .first()
        )
        return int(row.balance) if row is not None else 0


class DbBackedEventGateway:
    """Mock adapter reading registration records from the local tables.

    To be swapped for the real S3-MINI event-module adapter at integration time.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_active_registration(
        self, course_id: uuid.UUID, contact_id: uuid.UUID
    ) -> RegistrationSnapshot | None:
        row = (
            self._db.query(models.Registration)
            .filter(
                models.Registration.course_id == course_id,
                models.Registration.contact_id == contact_id,
                models.Registration.status.in_(ACTIVE_REGISTRATION_STATUSES),
                models.Registration.deleted_at.is_(None),
            )
            .first()
        )
        if row is None:
            return None
        return RegistrationSnapshot(status=row.status)

    def count_confirmed_registrations(self, course_id: uuid.UUID) -> int:
        # confirmed = registered + pending_review (waiting review still takes a seat)
        return (
            self._db.query(models.Registration)
            .filter(
                models.Registration.course_id == course_id,
                models.Registration.status.in_(("registered", "pending_review")),
                models.Registration.deleted_at.is_(None),
            )
            .count()
        )

    def count_waitlisted(self, course_id: uuid.UUID) -> int:
        return (
            self._db.query(models.Registration)
            .filter(
                models.Registration.course_id == course_id,
                models.Registration.status == "waitlisted",
                models.Registration.deleted_at.is_(None),
            )
            .count()
        )


ACTIVE_REGISTRATION_STATUSES = ("registered", "waitlisted", "pending_review")
