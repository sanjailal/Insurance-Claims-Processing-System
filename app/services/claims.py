"""
Claim service — orchestrates submission, adjudication, and persistence.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.db import (
    AdjudicationResult,
    AnnualDeductibleUsage,
    AnnualLimitUsage,
    Claim,
    CoverageRule,
    LineItem,
    LineItemClinicalDetail,
    Policy,
)
from app.models.enums import ClaimStatus, LineItemStatus, ServiceType
from app.services.adjudication import AdjudicationInput, CoverageRuleSnapshot, adjudicate_line_item


@dataclass
class LineItemData:
    """Input payload for a single line item on a new claim submission."""
    service_type: ServiceType
    date_of_service: date
    billed_amount: Decimal
    diagnosis_code: Optional[str] = None
    provider_name: Optional[str] = None
    description: Optional[str] = None


def submit_claim(
    member_id: str,
    policy_id: str,
    line_items: List[LineItemData],
    session: Session,
) -> Claim:
    """
    Creates a Claim with line items, runs adjudication on each, persists
    all results and updated YTD usage, then closes the claim.
    Line items within a single claim accumulate deductible and limit usage
    in order — each item sees the updated balances from its predecessors.
    """
    if not line_items:
        raise ValueError("A claim must have at least one line item.")

    policy = session.get(Policy, policy_id)
    if policy is None:
        raise ValueError(f"Policy {policy_id!r} not found.")

    claim = Claim(
        member_id=member_id,
        policy_id=policy_id,
        claim_number=_claim_number(),
        status=ClaimStatus.UNDER_REVIEW,
    )
    session.add(claim)
    session.flush()  # assign claim.id before adding children

    for item_data in line_items:
        year = _policy_year(policy.effective_date, policy.renewal_date, item_data.date_of_service)

        line_item = LineItem(
            claim_id=claim.id,
            service_type=item_data.service_type,
            date_of_service=item_data.date_of_service,
            billed_amount=item_data.billed_amount,
            status=LineItemStatus.PENDING,
        )
        session.add(line_item)
        session.flush()  # assign line_item.id before adding children

        # PHI boundary — clinical detail stored separately, never read by adjudication engine.
        if any([item_data.diagnosis_code, item_data.provider_name, item_data.description]):
            session.add(LineItemClinicalDetail(
                line_item_id=line_item.id,
                diagnosis_code=item_data.diagnosis_code,
                provider_name=item_data.provider_name,
                description=item_data.description,
            ))

        rule_db = session.query(CoverageRule).filter_by(
            policy_id=policy_id,
            service_type=item_data.service_type,
            is_active=True,
        ).first()

        rule_snapshot = (
            CoverageRuleSnapshot(
                annual_limit=rule_db.annual_limit,
                coverage_percent=rule_db.coverage_percent,
            )
            if rule_db else None
        )

        # get-or-create usage rows; in-memory objects accumulate across items
        # in this claim via SQLAlchemy's identity map — no flush required between items.
        ded_usage = _get_or_create_deductible_usage(member_id, policy_id, year, session)
        lim_usage = _get_or_create_limit_usage(member_id, policy_id, item_data.service_type, year, session)

        output = adjudicate_line_item(AdjudicationInput(
            service_type=item_data.service_type,
            date_of_service=item_data.date_of_service,
            billed_amount=item_data.billed_amount,
            policy_status=policy.status,
            policy_effective_date=policy.effective_date,
            policy_renewal_date=policy.renewal_date,
            annual_deductible=policy.annual_deductible,
            deductible_paid_to_date=ded_usage.paid_to_date,
            limit_used_to_date=lim_usage.used_to_date,
            coverage_rule=rule_snapshot,
        ))

        line_item.status = output.status

        session.add(AdjudicationResult(
            line_item_id=line_item.id,
            approved_amount=output.approved_amount,
            deductible_applied=output.deductible_applied,
            limit_cap_applied=output.limit_cap_applied,
            denial_reason=output.denial_reason,
            explanation_text=output.explanation_text,
        ))

        # Only approved items consume deductible and limit budget.
        # For denied items the engine already returns unchanged YTD values,
        # but the explicit guard makes the domain rule legible.
        if output.status == LineItemStatus.APPROVED:
            ded_usage.paid_to_date = output.updated_deductible_paid
            lim_usage.used_to_date = output.updated_limit_used

    claim.status = ClaimStatus.CLOSED
    session.commit()
    session.refresh(claim)
    return claim


def get_claim(claim_id: str, session: Session) -> Claim:
    claim = session.get(Claim, claim_id)
    if claim is None:
        raise ValueError(f"Claim {claim_id!r} not found.")
    return claim


# ── Private helpers ────────────────────────────────────────────────────────────

def _policy_year(effective_date: date, renewal_date: date, service_date: date) -> int:
    """1-indexed policy year that service_date falls in."""
    year = 1
    boundary = renewal_date
    while service_date >= boundary:
        year += 1
        boundary = boundary.replace(year=boundary.year + 1)
    return year


def _claim_number() -> str:
    return f"CLM-{uuid.uuid4().hex[:8].upper()}"


def _get_or_create_deductible_usage(
    member_id: str, policy_id: str, policy_year: int, session: Session
) -> AnnualDeductibleUsage:
    usage = session.query(AnnualDeductibleUsage).filter_by(
        member_id=member_id, policy_id=policy_id, policy_year=policy_year
    ).first()
    if usage is None:
        usage = AnnualDeductibleUsage(
            member_id=member_id,
            policy_id=policy_id,
            policy_year=policy_year,
            paid_to_date=Decimal("0.00"),
        )
        session.add(usage)
        session.flush()
    return usage


def _get_or_create_limit_usage(
    member_id: str,
    policy_id: str,
    service_type: ServiceType,
    policy_year: int,
    session: Session,
) -> AnnualLimitUsage:
    usage = session.query(AnnualLimitUsage).filter_by(
        member_id=member_id, policy_id=policy_id,
        service_type=service_type, policy_year=policy_year,
    ).first()
    if usage is None:
        usage = AnnualLimitUsage(
            member_id=member_id,
            policy_id=policy_id,
            service_type=service_type,
            policy_year=policy_year,
            used_to_date=Decimal("0.00"),
        )
        session.add(usage)
        session.flush()
    return usage
