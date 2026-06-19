"""
Dispute flow tests — service layer, requires ORM models and DB.

Three rules under test:
  1. Filing a dispute on any line item of a closed claim reopens it.
  2. Resolving a dispute with an insurer override creates a new
     AdjudicationResult and closes the claim if no disputes remain.
  3. A second dispute cannot be filed while one is already open.
"""

import pytest
from datetime import date
from decimal import Decimal

from app.models.enums import (
    ClaimStatus,
    DisputeResolution,
    DisputeStatus,
    LineItemStatus,
    ServiceType,
)
from app.services.claims import LineItemData, submit_claim
from app.services.disputes import file_dispute, resolve_dispute


pytestmark = pytest.mark.skip(reason="Requires ORM models — enable after implementation")


def test_dispute_reopens_closed_claim(db_session, member, active_policy, standard_coverage_rules):
    """
    Filing a dispute on a line item of a CLOSED claim automatically
    transitions the claim to REOPENED and the line item to DISPUTED.
    """
    claim = submit_claim(
        member_id=member.id,
        policy_id=active_policy.id,
        line_items=[
            LineItemData(ServiceType.PHYSICAL_THERAPY, date(2024, 6, 1), Decimal("200.00")),
        ],
        session=db_session,
    )
    assert claim.status == ClaimStatus.CLOSED

    line_item = claim.line_items[0]
    file_dispute(
        line_item_id=str(line_item.id),
        member_id=str(member.id),
        reason="The service is covered under my plan.",
        session=db_session,
    )

    db_session.refresh(claim)
    db_session.refresh(line_item)

    assert claim.status == ClaimStatus.REOPENED
    assert line_item.status == LineItemStatus.DISPUTED


def test_dispute_resolution_creates_new_adjudication_result(
    db_session, member, active_policy, standard_coverage_rules
):
    """
    Resolving a dispute with APPROVED creates a new AdjudicationResult
    that overrides the original. The claim closes when no open disputes remain.
    """
    claim = submit_claim(
        member_id=member.id,
        policy_id=active_policy.id,
        line_items=[
            LineItemData(ServiceType.MENTAL_HEALTH, date(2024, 6, 1), Decimal("150.00")),
        ],
        session=db_session,
    )

    line_item = claim.line_items[0]
    assert line_item.status == LineItemStatus.DENIED  # no MENTAL_HEALTH rule

    dispute = file_dispute(
        line_item_id=str(line_item.id),
        member_id=str(member.id),
        reason="My policy was updated to include mental health.",
        session=db_session,
    )

    resolve_dispute(
        dispute_id=str(dispute.id),
        resolution=DisputeResolution.APPROVED,
        notes="Coverage confirmed by underwriting. Approved.",
        session=db_session,
    )

    db_session.refresh(claim)
    db_session.refresh(line_item)

    assert dispute.status == DisputeStatus.RESOLVED
    assert dispute.resolution == DisputeResolution.APPROVED
    assert line_item.status == LineItemStatus.APPROVED
    # A new AdjudicationResult exists reflecting the override
    assert line_item.adjudication_result is not None
    assert claim.status == ClaimStatus.CLOSED


def test_cannot_file_dispute_when_dispute_already_open(
    db_session, member, active_policy, standard_coverage_rules
):
    """
    A second dispute cannot be filed on a line item that already has an
    open or under-review dispute. This is a hard domain constraint.
    """
    claim = submit_claim(
        member_id=member.id,
        policy_id=active_policy.id,
        line_items=[
            LineItemData(ServiceType.PHYSICAL_THERAPY, date(2024, 6, 1), Decimal("200.00")),
        ],
        session=db_session,
    )

    line_item = claim.line_items[0]

    file_dispute(
        line_item_id=str(line_item.id),
        member_id=str(member.id),
        reason="First dispute.",
        session=db_session,
    )

    with pytest.raises(ValueError, match="open dispute"):
        file_dispute(
            line_item_id=str(line_item.id),
            member_id=str(member.id),
            reason="Duplicate dispute while first is still open.",
            session=db_session,
        )
