"""
Test fixtures — two categories:

  1. Pure-function fixtures (no DB) — used by test_adjudication.py.
  2. Service-layer fixtures (in-memory SQLite) — used by
     test_claim_lifecycle.py and test_disputes.py.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models.db import Base, CoverageRule, Member, Policy
from app.models.enums import PolicyStatus, PolicyType, ServiceType
from app.services.adjudication import AdjudicationInput, CoverageRuleSnapshot

# ── Shared rule snapshots (pure-function tests) ────────────────────────────────

PHYSICAL_THERAPY_RULE = CoverageRuleSnapshot(
    annual_limit=Decimal("1000.00"),
    coverage_percent=80,
)

SPECIALIST_RULE = CoverageRuleSnapshot(
    annual_limit=Decimal("2000.00"),
    coverage_percent=70,
)


# ── Pure-function helper ───────────────────────────────────────────────────────

def make_input(**overrides) -> AdjudicationInput:
    """
    Builds a default AdjudicationInput for a straightforward covered claim.
    Override specific fields to isolate the scenario under test.

    Defaults
    --------
    service_type             PHYSICAL_THERAPY
    date_of_service          2024-06-01  (within active policy year)
    billed_amount            $200.00
    policy_status            ACTIVE
    policy_effective_date    2024-01-01
    policy_renewal_date      2025-01-01
    annual_deductible        $500.00
    deductible_paid_to_date  $0.00  (nothing paid toward deductible yet)
    limit_used_to_date       $0.00  (full $1000 limit available)
    coverage_rule            PHYSICAL_THERAPY_RULE (80%, $1000 limit)
    """
    defaults: dict = {
        "service_type": ServiceType.PHYSICAL_THERAPY,
        "date_of_service": date(2024, 6, 1),
        "billed_amount": Decimal("200.00"),
        "policy_status": PolicyStatus.ACTIVE,
        "policy_effective_date": date(2024, 1, 1),
        "policy_renewal_date": date(2025, 1, 1),
        "annual_deductible": Decimal("500.00"),
        "deductible_paid_to_date": Decimal("0.00"),
        "limit_used_to_date": Decimal("0.00"),
        "coverage_rule": PHYSICAL_THERAPY_RULE,
    }
    defaults.update(overrides)
    return AdjudicationInput(**defaults)


# ── Service-layer fixtures (in-memory SQLite) ──────────────────────────────────

@pytest.fixture(scope="function")
def db_session():
    """Fresh in-memory SQLite database for each test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


@pytest.fixture
def member(db_session):
    m = Member(name="Jane Smith", date_of_birth=date(1985, 4, 12))
    db_session.add(m)
    db_session.commit()
    return m


@pytest.fixture
def active_policy(db_session, member):
    p = Policy(
        member_id=member.id,
        policy_number="POL-TEST-001",
        policy_type=PolicyType.INDIVIDUAL,
        effective_date=date(2024, 1, 1),
        renewal_date=date(2025, 1, 1),
        annual_deductible=Decimal("500.00"),
        status=PolicyStatus.ACTIVE,
    )
    db_session.add(p)
    db_session.commit()
    return p


@pytest.fixture
def standard_coverage_rules(db_session, active_policy):
    """
    Two coverage rules on the active policy:
      - PHYSICAL_THERAPY  : $1000 annual limit, 80% coverage
      - SPECIALIST_VISIT  : $2000 annual limit, 70% coverage
    MENTAL_HEALTH is intentionally absent — used to test NOT_COVERED denials.
    """
    rules = [
        CoverageRule(
            policy_id=active_policy.id,
            service_type=ServiceType.PHYSICAL_THERAPY,
            annual_limit=Decimal("1000.00"),
            coverage_percent=80,
            is_active=True,
        ),
        CoverageRule(
            policy_id=active_policy.id,
            service_type=ServiceType.SPECIALIST_VISIT,
            annual_limit=Decimal("2000.00"),
            coverage_percent=70,
            is_active=True,
        ),
    ]
    db_session.add_all(rules)
    db_session.commit()
    return rules
