"""
Dispute service — handles filing and resolving disputes on line items.
Filing a dispute automatically reopens the parent claim.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.db import AdjudicationResult, Dispute, LineItem
from app.models.enums import ClaimStatus, DisputeResolution, DisputeStatus, LineItemStatus

_ZERO = Decimal("0.00")


def file_dispute(
    line_item_id: str,
    member_id: str,
    reason: str,
    session: Session,
) -> Dispute:
    """
    Creates a Dispute record, sets LineItem.status = DISPUTED,
    and transitions the parent Claim to REOPENED.
    Raises ValueError if the line item already has an open dispute.
    """
    line_item = session.get(LineItem, line_item_id)
    if line_item is None:
        raise ValueError(f"Line item {line_item_id!r} not found.")

    if line_item.open_dispute is not None:
        raise ValueError(
            f"Line item {line_item_id!r} already has an open dispute. "
            "Resolve it before filing a new one."
        )

    dispute = Dispute(
        line_item_id=line_item_id,
        member_id=member_id,
        member_reason=reason,
        status=DisputeStatus.OPEN,
    )
    session.add(dispute)

    line_item.status = LineItemStatus.DISPUTED
    line_item.claim.status = ClaimStatus.REOPENED

    session.commit()
    session.refresh(dispute)
    return dispute


def resolve_dispute(
    dispute_id: str,
    resolution: DisputeResolution,
    notes: str,
    session: Session,
) -> Dispute:
    """
    Resolves a dispute with an insurer override decision.
    Creates a new AdjudicationResult reflecting the override.
    Closes the parent Claim if no other open disputes remain.

    Note: override approval sets approved_amount = billed_amount with no
    deductible or limit applied — this is a manual goodwill decision, not
    a re-adjudication. YTD usage records are not updated on override.
    """
    dispute = session.get(Dispute, dispute_id)
    if dispute is None:
        raise ValueError(f"Dispute {dispute_id!r} not found.")

    if dispute.status == DisputeStatus.RESOLVED:
        raise ValueError(f"Dispute {dispute_id!r} is already resolved.")

    dispute.status = DisputeStatus.RESOLVED
    dispute.resolution = resolution
    dispute.resolved_at = datetime.now(timezone.utc)
    dispute.resolution_notes = notes

    line_item = dispute.line_item

    if resolution == DisputeResolution.APPROVED:
        line_item.status = LineItemStatus.APPROVED
        session.add(AdjudicationResult(
            line_item_id=line_item.id,
            approved_amount=line_item.billed_amount,
            deductible_applied=_ZERO,
            limit_cap_applied=_ZERO,
            denial_reason=None,
            explanation_text="Approved upon dispute review.",
        ))
    else:
        line_item.status = LineItemStatus.DENIED
        session.add(AdjudicationResult(
            line_item_id=line_item.id,
            approved_amount=_ZERO,
            deductible_applied=_ZERO,
            limit_cap_applied=_ZERO,
            denial_reason=None,
            explanation_text="Denied upon dispute review.",
        ))

    # Flush so the identity map reflects dispute.status=RESOLVED before we
    # scan sibling disputes — otherwise the check could see the old status.
    session.flush()

    claim = line_item.claim
    open_disputes = [
        d
        for item in claim.line_items
        for d in item.disputes
        if d.status != DisputeStatus.RESOLVED
    ]
    if not open_disputes:
        claim.status = ClaimStatus.CLOSED

    session.commit()
    session.refresh(dispute)
    return dispute
