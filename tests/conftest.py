"""
Test fixtures.

Two categories:
  1. Pure-function fixtures (no DB) — used by test_adjudication.py.
     These are plain dataclasses, runnable immediately.

  2. Service-layer fixtures (in-memory SQLite DB) — used by
     test_claim_lifecycle.py and test_disputes.py.
     Marked with TODO; enabled once ORM models are implemented.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

import pytest

from app.models.enums import PolicyStatus, ServiceType
from app.services.adjudication import AdjudicationInput, CoverageRuleSnapshot

# ── Shared rule snapshots ──────────────────────────────────────────────────────

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
    service_type          PHYSICAL_THERAPY
    date_of_service       2024-06-01   (within active policy year)
    billed_amount         $200.00
    policy_status         ACTIVE
    policy_effective_date 2024-01-01
    policy_renewal_date   2025-01-01
    annual_deductible     $500.00
    deductible_paid_to_date  $0.00    (nothing paid toward deductible yet)
    limit_used_to_date    $0.00       (full $1000 limit available)
    coverage_rule         PHYSICAL_THERAPY_RULE (80%, $1000 limit)
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


# ── Service-layer fixtures (TODO: enable after ORM models are implemented) ─────
#
# @pytest.fixture
# def db_session():
#     from sqlalchemy import create_engine
#     from sqlalchemy.orm import Session
#     from app.database import Base
#     engine = create_engine("sqlite:///:memory:")
#     Base.metadata.create_all(engine)
#     with Session(engine) as session:
#         yield session
#
# @pytest.fixture
# def member(db_session):
#     from app.models.db import Member
#     m = Member(name="Jane Smith", date_of_birth=date(1985, 4, 12))
#     db_session.add(m)
#     db_session.commit()
#     return m
#
# @pytest.fixture
# def active_policy(db_session, member):
#     from app.models.db import Policy
#     from app.models.enums import PolicyType
#     p = Policy(
#         member_id=member.id,
#         policy_number="POL-TEST-001",
#         policy_type=PolicyType.INDIVIDUAL,
#         effective_date=date(2024, 1, 1),
#         renewal_date=date(2025, 1, 1),
#         annual_deductible=Decimal("500.00"),
#         status=PolicyStatus.ACTIVE,
#     )
#     db_session.add(p)
#     db_session.commit()
#     return p
#
# @pytest.fixture
# def standard_coverage_rules(db_session, active_policy):
#     """Physical therapy + specialist rules. Mental health intentionally excluded."""
#     from app.models.db import CoverageRule
#     rules = [
#         CoverageRule(
#             policy_id=active_policy.id,
#             service_type=ServiceType.PHYSICAL_THERAPY,
#             annual_limit=Decimal("1000.00"),
#             coverage_percent=80,
#             is_active=True,
#         ),
#         CoverageRule(
#             policy_id=active_policy.id,
#             service_type=ServiceType.SPECIALIST_VISIT,
#             annual_limit=Decimal("2000.00"),
#             coverage_percent=70,
#             is_active=True,
#         ),
#     ]
#     db_session.add_all(rules)
#     db_session.commit()
#     return rules
