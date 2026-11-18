"""pytest fixtures: real PostgreSQL (DATABASE_URL or local default).

Seeding happens ONLY in test setup (INSERTs are allowed there); the service
under test must never write - that invariant is asserted in
tests/test_readonly_invariants.py.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models

FIXED_NOW = datetime(2026, 11, 18, 9, 0, 0, tzinfo=timezone.utc)

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
SITE = uuid.UUID("00000000-0000-0000-0000-000000000002")


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://postgres:postgres@127.0.0.1:5433/academy_test"
    )


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(database_url(), future=True)
    with eng.begin() as conn:
        models.Base.metadata.create_all(conn)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    """Fresh schema per test; seed session committed, then closed."""
    models.Base.metadata.drop_all(engine)
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


def clock():
    return FIXED_NOW


class Seed:
    """Insert-only seed helpers (test setup only)."""

    def __init__(self, s):
        self.s = s

    def category(self, name="品类A", deductible=False):
        row = models.CourseCategory(
            org_id=ORG, site_id=SITE, name=name, entitlement_deductible=deductible
        )
        self.s.add(row)
        self.s.flush()
        return row

    def course(self, **kw):
        base = dict(
            org_id=ORG,
            site_id=SITE,
            title="虚构课程",
            period_start=FIXED_NOW - timedelta(days=1),
            period_end=FIXED_NOW + timedelta(days=7),
            quota=30,
            waitlist_quota=5,
        )
        base.update(kw)
        row = models.Course(**base)
        self.s.add(row)
        self.s.flush()
        return row

    def contact(self, logged=True, phone_authorized=True):
        row = models.Contact(
            org_id=ORG,
            site_id=SITE,
            phone="13800000000" if phone_authorized else None,
            phone_authorized=phone_authorized,
        )
        self.s.add(row)
        self.s.flush()
        return row

    def membership(self, contact_id, status="active", valid_until=None):
        row = models.Membership(
            org_id=ORG,
            site_id=SITE,
            contact_id=contact_id,
            status=status,
            valid_until=valid_until or FIXED_NOW + timedelta(days=60),
        )
        self.s.add(row)
        self.s.flush()
        return row

    def equity(self, contact_id, category_id, balance=0):
        row = models.EntitlementEquity(
            org_id=ORG,
            site_id=SITE,
            contact_id=contact_id,
            category_id=category_id,
            balance=balance,
        )
        self.s.add(row)
        self.s.flush()
        return row

    def registration(self, course_id, contact_id, status="registered"):
        row = models.Registration(
            org_id=ORG,
            site_id=SITE,
            course_id=course_id,
            contact_id=contact_id,
            status=status,
        )
        self.s.add(row)
        self.s.flush()
        return row

    def commit(self):
        self.s.commit()
        return self


@pytest.fixture()
def seed(db):
    return Seed(db)
