"""
Adjudication engine tests — pure function, no database, no HTTP.

Each test calls adjudicate_line_item() directly with a constructed
AdjudicationInput and asserts the AdjudicationOutput encodes the
correct domain rule. Tests are runnable as soon as the engine is
implemented; they do not depend on the ORM or service layer.
"""

from decimal import Decimal
from datetime import date

from app.models.enums import DenialReason, LineItemStatus, PolicyStatus, ServiceType
from app.services.adjudication import CoverageRuleSnapshot, adjudicate_line_item
from tests.conftest import PHYSICAL_THERAPY_RULE, SPECIALIST_RULE, make_input


# ── Eligibility & Coverage ─────────────────────────────────────────────────────

def test_covered_service_is_approved():
    """A line item for a covered service type is approved with the correct amounts."""
    result = adjudicate_line_item(make_input(
        billed_amount=Decimal("200.00"),
        deductible_paid_to_date=Decimal("500.00"),  # deductible already fully met
    ))

    assert result.status == LineItemStatus.APPROVED
    assert result.approved_amount == Decimal("160.00")  # 80% of $200
    assert result.deductible_applied == Decimal("0.00")
    assert result.limit_cap_applied == Decimal("0.00")
    assert result.denial_reason is None


def test_service_without_coverage_rule_is_denied_not_covered():
    """A service type with no coverage rule is denied immediately with NOT_COVERED."""
    result = adjudicate_line_item(make_input(
        service_type=ServiceType.MENTAL_HEALTH,
        coverage_rule=None,
    ))

    assert result.status == LineItemStatus.DENIED
    assert result.denial_reason == DenialReason.NOT_COVERED
    assert result.approved_amount == Decimal("0.00")


def test_claim_denied_when_policy_inactive():
    """A line item submitted against an inactive policy is denied with NOT_ELIGIBLE."""
    result = adjudicate_line_item(make_input(
        policy_status=PolicyStatus.EXPIRED,
    ))

    assert result.status == LineItemStatus.DENIED
    assert result.denial_reason == DenialReason.NOT_ELIGIBLE
    assert result.approved_amount == Decimal("0.00")


def test_line_item_before_policy_effective_date_is_denied():
    """
    A service rendered before the policy effective date is denied with NOT_ELIGIBLE.
    This is distinct from an inactive policy — the policy is ACTIVE but date of
    service predates coverage.
    """
    result = adjudicate_line_item(make_input(
        date_of_service=date(2023, 12, 31),       # one day before effectiveDate
        policy_effective_date=date(2024, 1, 1),
        policy_status=PolicyStatus.ACTIVE,
    ))

    assert result.status == LineItemStatus.DENIED
    assert result.denial_reason == DenialReason.NOT_ELIGIBLE


# ── Deductible mechanics ───────────────────────────────────────────────────────

def test_deductible_applied_before_coverage_percentage():
    """
    Deductible is consumed first. Coverage percent applies only to the
    remainder after the deductible. Order of operations matters.
    """
    result = adjudicate_line_item(make_input(
        billed_amount=Decimal("300.00"),
        annual_deductible=Decimal("500.00"),
        deductible_paid_to_date=Decimal("400.00"),  # $100 of deductible remaining
    ))
    # $100 → deductible, $200 remaining → 80% = $160 approved

    assert result.deductible_applied == Decimal("100.00")
    assert result.approved_amount == Decimal("160.00")
    assert result.status == LineItemStatus.APPROVED


def test_claim_fully_consumed_by_deductible_is_still_approved():
    """
    A covered line item that is entirely consumed by the deductible is APPROVED
    with approvedAmount = $0. The service type is covered; the deductible
    determines that the insurer owes nothing this period.
    The explanation must make this explicit to the member.
    """
    result = adjudicate_line_item(make_input(
        billed_amount=Decimal("200.00"),
        annual_deductible=Decimal("500.00"),
        deductible_paid_to_date=Decimal("0.00"),   # full $500 deductible remaining
    ))

    assert result.status == LineItemStatus.APPROVED
    assert result.deductible_applied == Decimal("200.00")
    assert result.approved_amount == Decimal("0.00")
    assert result.denial_reason is None


def test_no_deductible_applied_when_deductible_already_satisfied():
    """When the annual deductible is fully met, it no longer reduces the covered amount."""
    result = adjudicate_line_item(make_input(
        billed_amount=Decimal("200.00"),
        annual_deductible=Decimal("500.00"),
        deductible_paid_to_date=Decimal("500.00"),  # fully satisfied
    ))

    assert result.deductible_applied == Decimal("0.00")
    assert result.approved_amount == Decimal("160.00")  # 80% of full $200


def test_deductible_consumption_carries_across_line_items():
    """
    Deductible paid by an earlier line item reduces what later line items
    contribute to the deductible. updated_deductible_paid is the handoff value.
    """
    first = adjudicate_line_item(make_input(
        billed_amount=Decimal("400.00"),
        annual_deductible=Decimal("500.00"),
        deductible_paid_to_date=Decimal("200.00"),  # $300 remaining
    ))
    # $300 goes to deductible, $100 remaining → 80% = $80 approved

    assert first.deductible_applied == Decimal("300.00")
    assert first.approved_amount == Decimal("80.00")
    assert first.updated_deductible_paid == Decimal("500.00")  # now fully met

    second = adjudicate_line_item(make_input(
        billed_amount=Decimal("200.00"),
        annual_deductible=Decimal("500.00"),
        deductible_paid_to_date=first.updated_deductible_paid,  # carry forward
    ))
    # Deductible fully met — no deductible applied, 80% of $200 = $160

    assert second.deductible_applied == Decimal("0.00")
    assert second.approved_amount == Decimal("160.00")


def test_deductible_resets_on_policy_renewal():
    """
    In a new policy year, deductible_paid_to_date starts at $0.
    The full annual deductible applies again from the first claim.
    """
    result = adjudicate_line_item(make_input(
        billed_amount=Decimal("100.00"),
        annual_deductible=Decimal("500.00"),
        deductible_paid_to_date=Decimal("0.00"),  # fresh policy year
    ))

    assert result.deductible_applied == Decimal("100.00")
    assert result.updated_deductible_paid == Decimal("100.00")
    assert result.approved_amount == Decimal("0.00")  # all went to deductible


# ── Annual limit mechanics ─────────────────────────────────────────────────────

def test_claim_denied_when_annual_limit_exhausted():
    """A line item submitted after the annual limit is fully used is denied."""
    result = adjudicate_line_item(make_input(
        billed_amount=Decimal("100.00"),
        deductible_paid_to_date=Decimal("500.00"),
        limit_used_to_date=Decimal("1000.00"),  # $1000 limit fully exhausted
        coverage_rule=CoverageRuleSnapshot(annual_limit=Decimal("1000.00"), coverage_percent=80),
    ))

    assert result.status == LineItemStatus.DENIED
    assert result.denial_reason == DenialReason.LIMIT_EXHAUSTED
    assert result.approved_amount == Decimal("0.00")


def test_partial_limit_remaining_caps_covered_amount():
    """
    When only part of the annual limit remains, only that portion is adjudicated.
    The excess is captured in limit_cap_applied — not silently lost.
    """
    result = adjudicate_line_item(make_input(
        billed_amount=Decimal("800.00"),
        deductible_paid_to_date=Decimal("500.00"),  # deductible met
        limit_used_to_date=Decimal("700.00"),        # $300 of $1000 remaining
    ))
    # $500 over limit → limit_cap_applied = $500
    # $300 within limit → 80% = $240 approved

    assert result.limit_cap_applied == Decimal("500.00")
    assert result.approved_amount == Decimal("240.00")
    assert result.status == LineItemStatus.APPROVED


def test_limit_usage_is_updated_after_approval():
    """updated_limit_used reflects the effective covered amount consumed."""
    result = adjudicate_line_item(make_input(
        billed_amount=Decimal("200.00"),
        deductible_paid_to_date=Decimal("500.00"),
        limit_used_to_date=Decimal("600.00"),
    ))

    assert result.updated_limit_used == Decimal("800.00")  # 600 + 200


def test_limit_usage_carries_across_multiple_claims():
    """
    Limits are policy-year scoped, not claim-scoped. Usage from one
    adjudication reduces what is available for the next.
    """
    first = adjudicate_line_item(make_input(
        billed_amount=Decimal("700.00"),
        deductible_paid_to_date=Decimal("500.00"),
        limit_used_to_date=Decimal("0.00"),
    ))
    assert first.updated_limit_used == Decimal("700.00")

    second = adjudicate_line_item(make_input(
        billed_amount=Decimal("400.00"),
        deductible_paid_to_date=Decimal("500.00"),
        limit_used_to_date=first.updated_limit_used,  # carry forward from prior claim
    ))
    # $300 remaining of $1000 → $100 over limit
    assert second.limit_cap_applied == Decimal("100.00")
    assert second.approved_amount == Decimal("240.00")    # 80% of $300
    assert second.updated_limit_used == Decimal("1000.00")


# ── Multi-service type ─────────────────────────────────────────────────────────

def test_each_line_item_uses_its_own_coverage_rule():
    """
    Two line items of different service types are adjudicated against
    their respective rules. Coverage percents differ → approved amounts differ.
    """
    pt_result = adjudicate_line_item(make_input(
        service_type=ServiceType.PHYSICAL_THERAPY,
        coverage_rule=PHYSICAL_THERAPY_RULE,       # 80%
        billed_amount=Decimal("200.00"),
        deductible_paid_to_date=Decimal("500.00"),
    ))

    specialist_result = adjudicate_line_item(make_input(
        service_type=ServiceType.SPECIALIST_VISIT,
        coverage_rule=SPECIALIST_RULE,             # 70%
        billed_amount=Decimal("200.00"),
        deductible_paid_to_date=Decimal("500.00"),
    ))

    assert pt_result.approved_amount == Decimal("160.00")      # 80% of $200
    assert specialist_result.approved_amount == Decimal("140.00")  # 70% of $200


# ── Explanation quality ────────────────────────────────────────────────────────

def test_zero_payment_due_to_deductible_has_clear_explanation():
    """
    When approvedAmount is $0 because the deductible consumed the full bill,
    the explanation_text must say so explicitly.
    A member receiving '$0 approved' without context will assume a denial.
    """
    result = adjudicate_line_item(make_input(
        billed_amount=Decimal("150.00"),
        annual_deductible=Decimal("500.00"),
        deductible_paid_to_date=Decimal("0.00"),
    ))

    assert result.status == LineItemStatus.APPROVED
    assert result.approved_amount == Decimal("0.00")
    assert "deductible" in result.explanation_text.lower()
    assert "150" in result.explanation_text
