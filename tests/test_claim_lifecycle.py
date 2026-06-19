"""
Claim lifecycle tests — service layer, requires ORM models and DB.

These tests exercise submit_claim() through a real in-memory SQLite session.
Fixtures are enabled in conftest.py once ORM models are implemented.

Three rules under test:
  1. A claim with mixed service types (some covered, some not) adjudicates
     each line item independently and closes when all are resolved.
  2. Annual limits reset at the start of a new policy year.
  3. The deductible resets at the start of a new policy year.
"""

import pytest
from datetime import date
from decimal import Decimal

from app.models.enums import ClaimStatus, DenialReason, LineItemStatus, ServiceType
from app.services.claims import LineItemData, submit_claim


pytestmark = pytest.mark.skip(reason="Requires ORM models — enable after implementation")


def test_claim_with_multiple_service_types(db_session, member, active_policy, standard_coverage_rules):
    """
    A claim with three line items — two covered, one not covered — is adjudicated
    line by line. The claim closes only after all items have a final status.
    MENTAL_HEALTH has no coverage rule → denied with NOT_COVERED.
    """
    claim = submit_claim(
        member_id=member.id,
        policy_id=active_policy.id,
        line_items=[
            LineItemData(ServiceType.PHYSICAL_THERAPY, date(2024, 6, 1), Decimal("200.00")),
            LineItemData(ServiceType.SPECIALIST_VISIT, date(2024, 6, 1), Decimal("300.00")),
            LineItemData(ServiceType.MENTAL_HEALTH, date(2024, 6, 1), Decimal("150.00")),
        ],
        session=db_session,
    )

    statuses = {item.service_type: item.status for item in claim.line_items}
    assert statuses[ServiceType.PHYSICAL_THERAPY] == LineItemStatus.APPROVED
    assert statuses[ServiceType.SPECIALIST_VISIT] == LineItemStatus.APPROVED
    assert statuses[ServiceType.MENTAL_HEALTH] == LineItemStatus.DENIED

    mental_health_result = next(
        item.adjudication_result
        for item in claim.line_items
        if item.service_type == ServiceType.MENTAL_HEALTH
    )
    assert mental_health_result.denial_reason == DenialReason.NOT_COVERED

    assert claim.status == ClaimStatus.CLOSED


def test_annual_limits_reset_on_policy_renewal(db_session, member, active_policy, standard_coverage_rules):
    """
    Limit usage in year 1 does not count against year 2.
    After renewal, the full annual limit is available again.
    """
    # Year 1: exhaust the physical therapy limit
    year_1_claim = submit_claim(
        member_id=member.id,
        policy_id=active_policy.id,
        line_items=[
            LineItemData(ServiceType.PHYSICAL_THERAPY, date(2024, 6, 1), Decimal("1000.00")),
        ],
        session=db_session,
    )
    assert year_1_claim.line_items[0].status == LineItemStatus.APPROVED

    # Simulate year 2 policy (new policy record with updated effective/renewal dates)
    from app.models.db import Policy
    from app.models.enums import PolicyStatus, PolicyType
    year_2_policy = Policy(
        member_id=member.id,
        policy_number="POL-TEST-002",
        policy_type=PolicyType.INDIVIDUAL,
        effective_date=date(2025, 1, 1),
        renewal_date=date(2026, 1, 1),
        annual_deductible=Decimal("500.00"),
        status=PolicyStatus.ACTIVE,
    )
    db_session.add(year_2_policy)
    db_session.commit()

    # Copy coverage rules to year 2 policy
    from app.models.db import CoverageRule
    for rule in standard_coverage_rules:
        db_session.add(CoverageRule(
            policy_id=year_2_policy.id,
            service_type=rule.service_type,
            annual_limit=rule.annual_limit,
            coverage_percent=rule.coverage_percent,
            is_active=True,
        ))
    db_session.commit()

    # Year 2: full limit available again
    year_2_claim = submit_claim(
        member_id=member.id,
        policy_id=year_2_policy.id,
        line_items=[
            LineItemData(ServiceType.PHYSICAL_THERAPY, date(2025, 3, 1), Decimal("500.00")),
        ],
        session=db_session,
    )

    item = year_2_claim.line_items[0]
    assert item.status == LineItemStatus.APPROVED
    assert item.adjudication_result.limit_cap_applied == Decimal("0.00")


def test_deductible_resets_on_policy_renewal(db_session, member, active_policy, standard_coverage_rules):
    """
    Deductible paid in year 1 does not carry into year 2.
    The first claim of a new year faces the full annual deductible again.
    """
    # Year 1: satisfy the deductible with a first claim
    submit_claim(
        member_id=member.id,
        policy_id=active_policy.id,
        line_items=[
            LineItemData(ServiceType.PHYSICAL_THERAPY, date(2024, 3, 1), Decimal("500.00")),
        ],
        session=db_session,
    )

    # Year 2 policy — fresh deductible
    from app.models.db import Policy, CoverageRule
    from app.models.enums import PolicyStatus, PolicyType
    year_2_policy = Policy(
        member_id=member.id,
        policy_number="POL-TEST-003",
        policy_type=PolicyType.INDIVIDUAL,
        effective_date=date(2025, 1, 1),
        renewal_date=date(2026, 1, 1),
        annual_deductible=Decimal("500.00"),
        status=PolicyStatus.ACTIVE,
    )
    db_session.add(year_2_policy)
    db_session.commit()

    for rule in standard_coverage_rules:
        db_session.add(CoverageRule(
            policy_id=year_2_policy.id,
            service_type=rule.service_type,
            annual_limit=rule.annual_limit,
            coverage_percent=rule.coverage_percent,
            is_active=True,
        ))
    db_session.commit()

    year_2_claim = submit_claim(
        member_id=member.id,
        policy_id=year_2_policy.id,
        line_items=[
            LineItemData(ServiceType.PHYSICAL_THERAPY, date(2025, 2, 1), Decimal("200.00")),
        ],
        session=db_session,
    )

    item = year_2_claim.line_items[0]
    # Deductible is fresh — $200 billed, all goes to deductible, insurer pays $0
    assert item.adjudication_result.deductible_applied == Decimal("200.00")
    assert item.adjudication_result.approved_amount == Decimal("0.00")
    assert item.status == LineItemStatus.APPROVED
