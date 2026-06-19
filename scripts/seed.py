"""
Inserts one member, one active policy, and three coverage rules for a
quick API demo. Run once after starting the server for the first time.

    python3 scripts/seed.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from decimal import Decimal

from app.database import SessionLocal, create_tables
from app.models.db import CoverageRule, Member, Policy
from app.models.enums import PolicyStatus, PolicyType, ServiceType


def seed() -> None:
    create_tables()
    session = SessionLocal()
    try:
        member = Member(name="Alex Johnson", date_of_birth=date(1990, 3, 15))
        session.add(member)
        session.flush()

        policy = Policy(
            member_id=member.id,
            policy_number="POL-DEMO-001",
            policy_type=PolicyType.INDIVIDUAL,
            effective_date=date(2024, 1, 1),
            renewal_date=date(2025, 1, 1),
            annual_deductible=Decimal("500.00"),
            status=PolicyStatus.ACTIVE,
        )
        session.add(policy)
        session.flush()

        session.add_all([
            CoverageRule(
                policy_id=policy.id,
                service_type=ServiceType.PHYSICAL_THERAPY,
                annual_limit=Decimal("1000.00"),
                coverage_percent=80,
                is_active=True,
            ),
            CoverageRule(
                policy_id=policy.id,
                service_type=ServiceType.SPECIALIST_VISIT,
                annual_limit=Decimal("2000.00"),
                coverage_percent=70,
                is_active=True,
            ),
            CoverageRule(
                policy_id=policy.id,
                service_type=ServiceType.PREVENTIVE_CARE,
                annual_limit=Decimal("500.00"),
                coverage_percent=100,
                is_active=True,
            ),
        ])
        session.commit()

        print("Seed data created.")
        print(f"  member_id : {member.id}")
        print(f"  policy_id : {policy.id}")
        print()
        print("Coverage rules on this policy:")
        print("  PHYSICAL_THERAPY  — 80% coverage, $1,000 annual limit")
        print("  SPECIALIST_VISIT  — 70% coverage, $2,000 annual limit")
        print("  PREVENTIVE_CARE   — 100% coverage, $500 annual limit")
        print()
        print("Try the API at http://localhost:8000/docs")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
