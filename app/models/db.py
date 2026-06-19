from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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

_MONEY = Numeric(10, 2)  # asdecimal=True is the default for Numeric


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ── Member ────────────────────────────────────────────────────────────────────

class Member(Base):
    __tablename__ = "members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    date_of_birth: Mapped[date] = mapped_column(Date)

    policies: Mapped[List[Policy]] = relationship(back_populates="member")
    claims: Mapped[List[Claim]] = relationship(back_populates="member")


# ── Policy ────────────────────────────────────────────────────────────────────

class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    member_id: Mapped[str] = mapped_column(String(36), ForeignKey("members.id"), nullable=False)
    policy_number: Mapped[str] = mapped_column(String(50), unique=True)
    policy_type: Mapped[PolicyType] = mapped_column(SAEnum(PolicyType))
    effective_date: Mapped[date] = mapped_column(Date)
    renewal_date: Mapped[date] = mapped_column(Date)
    annual_deductible: Mapped[Decimal] = mapped_column(_MONEY)
    status: Mapped[PolicyStatus] = mapped_column(SAEnum(PolicyStatus))

    member: Mapped[Member] = relationship(back_populates="policies")
    coverage_rules: Mapped[List[CoverageRule]] = relationship(back_populates="policy")
    claims: Mapped[List[Claim]] = relationship(back_populates="policy")
    deductible_usage: Mapped[List[AnnualDeductibleUsage]] = relationship(back_populates="policy")
    limit_usage: Mapped[List[AnnualLimitUsage]] = relationship(back_populates="policy")


# ── CoverageRule ──────────────────────────────────────────────────────────────

class CoverageRule(Base):
    __tablename__ = "coverage_rules"
    __table_args__ = (
        UniqueConstraint("policy_id", "service_type", name="uq_policy_service_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    policy_id: Mapped[str] = mapped_column(String(36), ForeignKey("policies.id"), nullable=False)
    service_type: Mapped[ServiceType] = mapped_column(SAEnum(ServiceType))
    annual_limit: Mapped[Decimal] = mapped_column(_MONEY)
    coverage_percent: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(default=True)

    policy: Mapped[Policy] = relationship(back_populates="coverage_rules")


# ── Claim ─────────────────────────────────────────────────────────────────────

class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    member_id: Mapped[str] = mapped_column(String(36), ForeignKey("members.id"), nullable=False)
    policy_id: Mapped[str] = mapped_column(String(36), ForeignKey("policies.id"), nullable=False)
    claim_number: Mapped[str] = mapped_column(String(50), unique=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    status: Mapped[ClaimStatus] = mapped_column(SAEnum(ClaimStatus), default=ClaimStatus.SUBMITTED)

    member: Mapped[Member] = relationship(back_populates="claims")
    policy: Mapped[Policy] = relationship(back_populates="claims")
    line_items: Mapped[List[LineItem]] = relationship(back_populates="claim")


# ── LineItem ──────────────────────────────────────────────────────────────────

class LineItem(Base):
    __tablename__ = "line_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id"), nullable=False)
    service_type: Mapped[ServiceType] = mapped_column(SAEnum(ServiceType))
    date_of_service: Mapped[date] = mapped_column(Date)
    billed_amount: Mapped[Decimal] = mapped_column(_MONEY)
    status: Mapped[LineItemStatus] = mapped_column(
        SAEnum(LineItemStatus), default=LineItemStatus.PENDING
    )

    claim: Mapped[Claim] = relationship(back_populates="line_items")
    clinical_detail: Mapped[Optional[LineItemClinicalDetail]] = relationship(
        back_populates="line_item", uselist=False
    )
    adjudication_results: Mapped[List[AdjudicationResult]] = relationship(
        back_populates="line_item"
    )
    disputes: Mapped[List[Dispute]] = relationship(back_populates="line_item")

    @property
    def adjudication_result(self) -> Optional[AdjudicationResult]:
        """The most recent adjudication result — current decision."""
        if not self.adjudication_results:
            return None
        return max(self.adjudication_results, key=lambda r: r.adjudicated_at)

    @property
    def open_dispute(self) -> Optional[Dispute]:
        """The active (unresolved) dispute, if any."""
        return next(
            (d for d in self.disputes if d.status != DisputeStatus.RESOLVED),
            None,
        )


# ── LineItemClinicalDetail (PHI boundary) ─────────────────────────────────────

class LineItemClinicalDetail(Base):
    __tablename__ = "line_item_clinical_details"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    line_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("line_items.id"), unique=True, nullable=False
    )
    diagnosis_code: Mapped[Optional[str]] = mapped_column(String(20))
    provider_name: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String(500))

    line_item: Mapped[LineItem] = relationship(back_populates="clinical_detail")


# ── AdjudicationResult ────────────────────────────────────────────────────────

class AdjudicationResult(Base):
    __tablename__ = "adjudication_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    line_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("line_items.id"), nullable=False
    )
    adjudicated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    approved_amount: Mapped[Decimal] = mapped_column(_MONEY)
    deductible_applied: Mapped[Decimal] = mapped_column(_MONEY)
    limit_cap_applied: Mapped[Decimal] = mapped_column(_MONEY)
    denial_reason: Mapped[Optional[DenialReason]] = mapped_column(SAEnum(DenialReason))
    explanation_text: Mapped[str] = mapped_column(String(1000))

    line_item: Mapped[LineItem] = relationship(back_populates="adjudication_results")


# ── AnnualDeductibleUsage ─────────────────────────────────────────────────────

class AnnualDeductibleUsage(Base):
    """Tracks shared deductible spend per member per policy year."""

    __tablename__ = "annual_deductible_usage"
    __table_args__ = (
        UniqueConstraint("member_id", "policy_id", "policy_year", name="uq_deductible_usage"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    member_id: Mapped[str] = mapped_column(String(36), ForeignKey("members.id"), nullable=False)
    policy_id: Mapped[str] = mapped_column(String(36), ForeignKey("policies.id"), nullable=False)
    policy_year: Mapped[int] = mapped_column(Integer)
    paid_to_date: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0.00"))

    policy: Mapped[Policy] = relationship(back_populates="deductible_usage")


# ── AnnualLimitUsage ──────────────────────────────────────────────────────────

class AnnualLimitUsage(Base):
    """Tracks benefit usage per member per service type per policy year."""

    __tablename__ = "annual_limit_usage"
    __table_args__ = (
        UniqueConstraint(
            "member_id", "policy_id", "service_type", "policy_year",
            name="uq_limit_usage",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    member_id: Mapped[str] = mapped_column(String(36), ForeignKey("members.id"), nullable=False)
    policy_id: Mapped[str] = mapped_column(String(36), ForeignKey("policies.id"), nullable=False)
    service_type: Mapped[ServiceType] = mapped_column(SAEnum(ServiceType))
    policy_year: Mapped[int] = mapped_column(Integer)
    used_to_date: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0.00"))

    policy: Mapped[Policy] = relationship(back_populates="limit_usage")


# ── Dispute ───────────────────────────────────────────────────────────────────

class Dispute(Base):
    __tablename__ = "disputes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    line_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("line_items.id"), nullable=False
    )
    member_id: Mapped[str] = mapped_column(String(36), ForeignKey("members.id"), nullable=False)
    filed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    member_reason: Mapped[str] = mapped_column(String(1000))
    status: Mapped[DisputeStatus] = mapped_column(
        SAEnum(DisputeStatus), default=DisputeStatus.OPEN
    )
    resolution: Mapped[Optional[DisputeResolution]] = mapped_column(SAEnum(DisputeResolution))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolution_notes: Mapped[Optional[str]] = mapped_column(String(1000))

    line_item: Mapped[LineItem] = relationship(back_populates="disputes")
