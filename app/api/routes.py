from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import (
    ClaimResponse,
    DisputeResponse,
    FileDisputeRequest,
    ResolveDisputeRequest,
    SubmitClaimRequest,
)
from app.database import get_session
from app.services.claims import LineItemData, get_claim, submit_claim
from app.services.disputes import file_dispute, resolve_dispute

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/claims", response_model=ClaimResponse, status_code=201)
def submit_claim_route(
    req: SubmitClaimRequest,
    session: Session = Depends(get_session),
):
    try:
        claim = submit_claim(
            member_id=req.member_id,
            policy_id=req.policy_id,
            line_items=[
                LineItemData(
                    service_type=item.service_type,
                    date_of_service=item.date_of_service,
                    billed_amount=item.billed_amount,
                    diagnosis_code=item.diagnosis_code,
                    provider_name=item.provider_name,
                    description=item.description,
                )
                for item in req.line_items
            ],
            session=session,
        )
        # Touch relationships now, while the session is open, so Pydantic
        # can serialize them without an expired-instance error.
        for item in claim.line_items:
            _ = item.adjudication_results
        return claim
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/claims/{claim_id}", response_model=ClaimResponse)
def get_claim_route(
    claim_id: str,
    session: Session = Depends(get_session),
):
    try:
        claim = get_claim(claim_id, session)
        for item in claim.line_items:
            _ = item.adjudication_results
        return claim
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/line-items/{line_item_id}/disputes",
    response_model=DisputeResponse,
    status_code=201,
)
def file_dispute_route(
    line_item_id: str,
    req: FileDisputeRequest,
    session: Session = Depends(get_session),
):
    try:
        return file_dispute(
            line_item_id=line_item_id,
            member_id=req.member_id,
            reason=req.reason,
            session=session,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/disputes/{dispute_id}/resolve", response_model=DisputeResponse)
def resolve_dispute_route(
    dispute_id: str,
    req: ResolveDisputeRequest,
    session: Session = Depends(get_session),
):
    try:
        return resolve_dispute(
            dispute_id=dispute_id,
            resolution=req.resolution,
            notes=req.notes,
            session=session,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
