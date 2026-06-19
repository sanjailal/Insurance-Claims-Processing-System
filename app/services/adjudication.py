"""
Pure adjudication engine — no database, no framework.

adjudicate_line_item() takes a fully resolved AdjudicationInput (all
policy and usage data already fetched) and returns an AdjudicationOutput.
The caller is responsible for persisting the updated usage values.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from app.models.enums import DenialReason, LineItemStatus, PolicyStatus, ServiceType


@dataclass(frozen=True)
class CoverageRuleSnapshot:
    """Immutable snapshot of a CoverageRule — decoupled from the ORM."""
    annual_limit: Decimal
    coverage_percent: int  # 0–100


@dataclass(frozen=True)
class AdjudicationInput:
    service_type: ServiceType
    date_of_service: date
    billed_amount: Decimal
    # Policy context
    policy_status: PolicyStatus
    policy_effective_date: date
    policy_renewal_date: date
    annual_deductible: Decimal
    # Year-to-date usage at the time this line item is processed
    deductible_paid_to_date: Decimal
    limit_used_to_date: Decimal
    # None when no active CoverageRule exists for this service type
    coverage_rule: Optional[CoverageRuleSnapshot]


@dataclass(frozen=True)
class AdjudicationOutput:
    status: LineItemStatus          # APPROVED or DENIED
    approved_amount: Decimal        # what the insurer pays (can be $0 on APPROVED)
    deductible_applied: Decimal     # portion of billed_amount applied to shared deductible
    limit_cap_applied: Decimal      # portion excluded because annual limit was exhausted
    denial_reason: Optional[DenialReason]
    explanation_text: str
    # Updated YTD values — caller persists these after a successful adjudication
    updated_deductible_paid: Decimal
    updated_limit_used: Decimal


def adjudicate_line_item(inp: AdjudicationInput) -> AdjudicationOutput:
    raise NotImplementedError
