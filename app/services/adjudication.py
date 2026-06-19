"""
Pure adjudication engine — no database, no framework.

adjudicate_line_item() takes a fully resolved AdjudicationInput (all
policy and usage data already fetched) and returns an AdjudicationOutput.
The caller is responsible for persisting the updated usage values.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from app.models.enums import DenialReason, LineItemStatus, PolicyStatus, ServiceType

_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


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
    # ── Step 1: Eligibility ───────────────────────────────────────────────────
    if inp.policy_status != PolicyStatus.ACTIVE:
        return _denial(
            inp,
            DenialReason.NOT_ELIGIBLE,
            f"Policy is not active (status: {inp.policy_status.value}). "
            f"Coverage was not in effect on {inp.date_of_service}.",
        )

    if inp.date_of_service < inp.policy_effective_date:
        return _denial(
            inp,
            DenialReason.NOT_ELIGIBLE,
            f"Date of service ({inp.date_of_service}) is before the policy "
            f"effective date ({inp.policy_effective_date}).",
        )

    if inp.date_of_service >= inp.policy_renewal_date:
        return _denial(
            inp,
            DenialReason.NOT_ELIGIBLE,
            f"Date of service ({inp.date_of_service}) is on or after the policy "
            f"renewal date ({inp.policy_renewal_date}). Submit against the renewed policy.",
        )

    # ── Step 2: Coverage ──────────────────────────────────────────────────────
    if inp.coverage_rule is None:
        service_name = _service_label(inp.service_type)
        return _denial(
            inp,
            DenialReason.NOT_COVERED,
            f"{service_name} is not a covered benefit under this policy.",
        )

    rule = inp.coverage_rule

    # ── Step 3: Annual limit check ────────────────────────────────────────────
    limit_remaining = rule.annual_limit - inp.limit_used_to_date
    if limit_remaining <= _ZERO:
        service_name = _service_label(inp.service_type)
        return _denial(
            inp,
            DenialReason.LIMIT_EXHAUSTED,
            f"Your annual {service_name} benefit limit of ${rule.annual_limit:.2f} "
            f"has been fully used this policy year.",
        )

    # ── Step 4: Effective covered amount (cap at remaining limit) ─────────────
    effective_covered = min(inp.billed_amount, limit_remaining)
    limit_cap_applied = inp.billed_amount - effective_covered

    # ── Step 5: Apply shared annual deductible ────────────────────────────────
    deductible_remaining = inp.annual_deductible - inp.deductible_paid_to_date
    deductible_applied = min(deductible_remaining, effective_covered)

    # ── Step 6: Apply coverage percent to remainder ───────────────────────────
    after_deductible = effective_covered - deductible_applied
    approved_amount = (
        after_deductible * Decimal(rule.coverage_percent) / Decimal("100")
    ).quantize(_CENT, rounding=ROUND_HALF_UP)

    # ── Step 7 & 8: Build result, return updated YTD values ───────────────────
    return AdjudicationOutput(
        status=LineItemStatus.APPROVED,
        approved_amount=approved_amount,
        deductible_applied=deductible_applied,
        limit_cap_applied=limit_cap_applied,
        denial_reason=None,
        explanation_text=_explanation(
            inp, effective_covered, limit_cap_applied,
            deductible_applied, after_deductible,
            approved_amount, rule.coverage_percent,
        ),
        updated_deductible_paid=inp.deductible_paid_to_date + deductible_applied,
        updated_limit_used=inp.limit_used_to_date + effective_covered,
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _denial(inp: AdjudicationInput, reason: DenialReason, text: str) -> AdjudicationOutput:
    """Returns a denial with no financial impact on YTD balances."""
    return AdjudicationOutput(
        status=LineItemStatus.DENIED,
        approved_amount=_ZERO,
        deductible_applied=_ZERO,
        limit_cap_applied=_ZERO,
        denial_reason=reason,
        explanation_text=text,
        updated_deductible_paid=inp.deductible_paid_to_date,
        updated_limit_used=inp.limit_used_to_date,
    )


def _explanation(
    inp: AdjudicationInput,
    effective_covered: Decimal,
    limit_cap_applied: Decimal,
    deductible_applied: Decimal,
    after_deductible: Decimal,
    approved_amount: Decimal,
    coverage_percent: int,
) -> str:
    service_name = _service_label(inp.service_type)
    parts: list[str] = []

    if limit_cap_applied > _ZERO:
        limit_remaining = inp.coverage_rule.annual_limit - inp.limit_used_to_date  # type: ignore[union-attr]
        parts.append(
            f"${limit_cap_applied:.2f} of your ${inp.billed_amount:.2f} bill "
            f"exceeds your remaining ${limit_remaining:.2f} annual {service_name} "
            f"benefit and is your responsibility."
        )

    if deductible_applied > _ZERO:
        new_total = inp.deductible_paid_to_date + deductible_applied
        parts.append(
            f"${deductible_applied:.2f} of ${inp.billed_amount:.2f} applied to your "
            f"${inp.annual_deductible:.2f} annual deductible "
            f"(${new_total:.2f} paid to date)."
        )

    if approved_amount > _ZERO:
        parts.append(
            f"Insurer pays {coverage_percent}% of ${after_deductible:.2f} "
            f"= ${approved_amount:.2f}."
        )
    elif deductible_applied > _ZERO:
        parts.append(
            "Insurer pays $0.00 this claim; full covered amount applied to deductible."
        )

    member_pays = inp.billed_amount - approved_amount
    parts.append(f"Your total responsibility: ${member_pays:.2f}.")

    return " ".join(parts)


def _service_label(service_type: ServiceType) -> str:
    return service_type.value.replace("_", " ").title()
