"""
Dispute service — handles filing and resolving disputes on line items.
Filing a dispute automatically reopens the parent claim.
"""

from app.models.enums import DisputeResolution


def file_dispute(
    line_item_id: str,
    member_id: str,
    reason: str,
    session,
):
    """
    Creates a Dispute record, sets LineItem.status = DISPUTED,
    and transitions the parent Claim to REOPENED.
    Raises ValueError if the line item already has an open dispute.
    """
    raise NotImplementedError


def resolve_dispute(
    dispute_id: str,
    resolution: DisputeResolution,
    notes: str,
    session,
):
    """
    Resolves a dispute with an insurer override decision.
    Creates a new AdjudicationResult reflecting the override.
    Closes the parent Claim if no other open disputes remain.
    """
    raise NotImplementedError
