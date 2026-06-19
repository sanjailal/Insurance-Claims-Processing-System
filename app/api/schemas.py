"""
Pydantic request and response schemas for the API layer.
These are separate from the ORM models — they define the contract at the
HTTP boundary and never appear in the adjudication engine or service layer.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    ClaimStatus,
    DenialReason,
    DisputeResolution,
    DisputeStatus,
    LineItemStatus,
    PolicyStatus,
    PolicyType,
    ServiceType,
)


# ── Member ─────────────────────────────────────────────────────────────────────

class CreateMemberRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"name": "Alex Johnson", "date_of_birth": "1990-03-15"}}
    )

    name: str
    date_of_birth: date


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    date_of_birth: date


# ── Policy ─────────────────────────────────────────────────────────────────────

class CreatePolicyRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "member_id": "<id from POST /members>",
                "effective_date": "2024-01-01",
                "renewal_date": "2025-01-01",
                "annual_deductible": "500.00",
            }
        }
    )

    member_id: str
    policy_number: Optional[str] = Field(
        default=None,
        description="Auto-generated (e.g. POL-3A2F1B9C) if not provided.",
    )
    policy_type: PolicyType = PolicyType.INDIVIDUAL
    effective_date: date
    renewal_date: date
    annual_deductible: Decimal = Field(ge=Decimal("0.00"))
    status: PolicyStatus = PolicyStatus.ACTIVE

    @model_validator(mode="after")
    def renewal_must_follow_effective(self) -> CreatePolicyRequest:
        if self.renewal_date <= self.effective_date:
            raise ValueError("renewal_date must be after effective_date")
        return self


class PolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    member_id: str
    policy_number: str
    policy_type: PolicyType
    effective_date: date
    renewal_date: date
    annual_deductible: Decimal
    status: PolicyStatus


# ── Coverage rule ──────────────────────────────────────────────────────────────

class AddCoverageRuleRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "service_type": "PHYSICAL_THERAPY",
                "annual_limit": "1000.00",
                "coverage_percent": 80,
            }
        }
    )

    service_type: ServiceType
    annual_limit: Decimal = Field(gt=Decimal("0.00"))
    coverage_percent: int = Field(ge=0, le=100)


class CoverageRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    policy_id: str
    service_type: ServiceType
    annual_limit: Decimal
    coverage_percent: int
    is_active: bool


# ── Claim ──────────────────────────────────────────────────────────────────────

class LineItemRequest(BaseModel):
    service_type: ServiceType
    date_of_service: date
    billed_amount: Decimal
    diagnosis_code: Optional[str] = None
    provider_name: Optional[str] = None
    description: Optional[str] = None


class SubmitClaimRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "member_id": "<id from POST /members>",
                "policy_id": "<id from POST /policies>",
                "line_items": [
                    {
                        "service_type": "PHYSICAL_THERAPY",
                        "date_of_service": "2024-06-01",
                        "billed_amount": "200.00",
                    }
                ],
            }
        }
    )

    member_id: str
    policy_id: str
    line_items: List[LineItemRequest]


class FileDisputeRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "member_id": "<id from POST /members>",
                "reason": "This service is covered under my plan.",
            }
        }
    )

    member_id: str
    reason: str


class ResolveDisputeRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"resolution": "APPROVED", "notes": "Coverage confirmed by underwriting."}
        }
    )

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
