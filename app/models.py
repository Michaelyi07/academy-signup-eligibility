"""SQLAlchemy 2.0 declarative models.

Unified table conventions (per platform tech agreement):
- id: UUID primary key
- org_id / site_id: tenant scoping
- created_at / deleted_at: soft delete (rows with deleted_at IS NULL are live)

Only fictitious seed data is used; no real personal or business information.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class OrgScopedMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CourseCategory(OrgScopedMixin, Base):
    __tablename__ = "academy_course_category"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # True => membership entitlement (权益) can deduct the fee for courses in this category
    entitlement_deductible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )


class Course(OrgScopedMixin, Base):
    """One academy course *session* (an offering a contact can sign up for).

    ``Course.id`` is the ``session_id`` consumed by
    ``enrollment_eligibility_service.check(session_id, viewer)``.
    """

    __tablename__ = "academy_course"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # 'published' | 'cancelled'
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="published")
    # False => anonymous/API consumers must treat the course as nonexistent (404)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # manual signup switch; True => closed
    signup_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    signup_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signup_close_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 'live' | 'application' (application => transferred through an application flow)
    delivery_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="live")
    # 'public' | 'member_only'
    audience: Mapped[str] = mapped_column(String(20), nullable=False, default="public")
    # 'paid' | 'free' | 'entitlement'
    fee_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="free")
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academy_course_category.id")
    )
    quota: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    waitlist_quota: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Contact(OrgScopedMixin, Base):
    """Member-space contact (mock of the S3-MINI member identity)."""

    __tablename__ = "academy_contact"

    phone: Mapped[str | None] = mapped_column(String(32))
    # phone number authorization completed (mini-program OAuth)
    phone_authorized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )


class Membership(OrgScopedMixin, Base):
    """CRM membership record (mock of the S2-CRM membership object)."""

    __tablename__ = "academy_membership"

    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academy_contact.id"), nullable=False
    )
    # 'active' | 'about_to_expire' | 'expired'
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EntitlementEquity(OrgScopedMixin, Base):
    """Membership equity ledger for entitlement deduction (balance > 0 lets a
    member book a deductible course). Amount fields are stored as integer
    count of equity units; monetary amounts elsewhere use minutes."""

    __tablename__ = "academy_entitlement_equity"

    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academy_contact.id"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academy_course_category.id"), nullable=False
    )
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Registration(OrgScopedMixin, Base):
    """Event-module registration record (mock of the S3-MINI event module).

    status flow: 'pending_review' -> 'registered' | 'rejected';
    'waitlisted' when quota is full; 'cancelled' by the contact.
    """

    __tablename__ = "academy_registration"

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academy_course.id"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academy_contact.id"), nullable=False
    )
    # 'registered' | 'waitlisted' | 'pending_review' | 'cancelled' | 'rejected'
    status: Mapped[str] = mapped_column(String(20), nullable=False)


class CoursePrice(OrgScopedMixin, Base):
    """Price row in minutes (fee_mode='paid'); kept for the course-detail
    contract, not consulted by the eligibility service itself."""

    __tablename__ = "academy_course_price"

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academy_course.id"), nullable=False
    )
    amount_minutes: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
