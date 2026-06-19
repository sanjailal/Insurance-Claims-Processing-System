"""
Pydantic request and response schemas for the API layer.
These are separate from the ORM models — they define the contract at the
HTTP boundary and never appear in the adjudication engine or service layer.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.models.enums import (
    ClaimStatus,
    DenialReason,
    DisputeResolution,
    DisputeStatus,
    LineItemStatus,
    ServiceType,
)


# ── Request schemas ────────────────────────────────────────────────────────────

class LineItemRequest(BaseModel):
    service_type: ServiceType
    date_of_service: date
    billed_amount: Decimal
    diagnosis_code: Optional[str] = None
    provider_name: Optional[str] = None
    description: Optional[str] = None


class SubmitClaimRequest(BaseModel):
    member_id: str
    policy_id: str
    line_items: List[LineItemRequest]


class FileDisputeRequest(BaseModel):
    member_id: str
    reason: str


class ResolveDisputeRequest(BaseModel):
    resolution: DisputeResolution
    notes: str


# ── Response schemas ───────────────────────────────────────────────────────────

class AdjudicationResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    adjudicated_at: datetime
    approved_amount: Decimal
    deductible_applied: Decimal
    limit_cap_applied: Decimal
    denial_reason: Optional[DenialReason]
    explanation_text: str


class LineItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    service_type: ServiceType
    date_of_service: date
    billed_amount: Decimal
    status: LineItemStatus
    adjudication_result: Optional[AdjudicationResultResponse]


class ClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    claim_number: str
    member_id: str
    policy_id: str
    submitted_at: datetime
    status: ClaimStatus
    line_items: List[LineItemResponse]


class DisputeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    line_item_id: str
    member_id: str
    filed_at: datetime
    member_reason: str
    status: DisputeStatus
    resolution: Optional[DisputeResolution]
    resolved_at: Optional[datetime]
    resolution_notes: Optional[str]
