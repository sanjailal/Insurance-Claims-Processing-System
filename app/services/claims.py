"""
Claim service — orchestrates submission, adjudication, and persistence.
Depends on the adjudication engine and the ORM layer (implemented later).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional

from app.models.enums import ServiceType


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
    session,
):
    """
    Creates a Claim with line items, runs adjudication on each line item,
    persists all results, and returns the adjudicated Claim.
    """
    raise NotImplementedError


def get_claim(claim_id: str, session):
    raise NotImplementedError
