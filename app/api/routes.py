import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas import (
    AddCoverageRuleRequest,
    ClaimResponse,
    CreateMemberRequest,
    CreatePolicyRequest,
    CoverageRuleResponse,
    DisputeResponse,
    FileDisputeRequest,
    MemberResponse,
    PolicyResponse,
    ResolveDisputeRequest,
    SubmitClaimRequest,
)
from app.database import get_session
from app.models.db import CoverageRule, Member, Policy
from app.services.claims import LineItemData, get_claim, submit_claim
from app.services.disputes import file_dispute, resolve_dispute

_UI_HTML = Path(__file__).parent.parent / "static" / "index.html"

router = APIRouter()


def _policy_number() -> str:
    return f"POL-{uuid.uuid4().hex[:8].upper()}"


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def ui():
    return _UI_HTML.read_text()


# ── Members ────────────────────────────────────────────────────────────────────

@router.get("/members", response_model=list[MemberResponse])
def list_members(session: Session = Depends(get_session)):
    return session.query(Member).all()


@router.post("/members", response_model=MemberResponse, status_code=201)
def create_member(
    req: CreateMemberRequest,
    session: Session = Depends(get_session),
):
    member = Member(name=req.name, date_of_birth=req.date_of_birth)
    session.add(member)
    session.commit()
    session.refresh(member)
    return member


@router.get("/members/{member_id}", response_model=MemberResponse)
def get_member(member_id: str, session: Session = Depends(get_session)):
    member = session.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail=f"Member {member_id!r} not found.")
    return member


# ── Policies ───────────────────────────────────────────────────────────────────

@router.get("/policies", response_model=list[PolicyResponse])
def list_policies(
    member_id: Optional[str] = None,
    session: Session = Depends(get_session),
):
    q = session.query(Policy)
    if member_id:
        q = q.filter_by(member_id=member_id)
    return q.all()


@router.post("/policies", response_model=PolicyResponse, status_code=201)
def create_policy(
    req: CreatePolicyRequest,
    session: Session = Depends(get_session),
):
    if session.get(Member, req.member_id) is None:
        raise HTTPException(status_code=404, detail=f"Member {req.member_id!r} not found.")

    policy = Policy(
        member_id=req.member_id,
        policy_number=req.policy_number or _policy_number(),
        policy_type=req.policy_type,
        effective_date=req.effective_date,
        renewal_date=req.renewal_date,
        annual_deductible=req.annual_deductible,
        status=req.status,
    )
    session.add(policy)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Policy number {req.policy_number!r} already exists.",
        )
    session.refresh(policy)
    return policy


@router.get("/policies/{policy_id}", response_model=PolicyResponse)
def get_policy(policy_id: str, session: Session = Depends(get_session)):
    policy = session.get(Policy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id!r} not found.")
    return policy


# ── Coverage rules ─────────────────────────────────────────────────────────────

@router.post(
    "/policies/{policy_id}/coverage-rules",
    response_model=CoverageRuleResponse,
    status_code=201,
)
def add_coverage_rule(
    policy_id: str,
    req: AddCoverageRuleRequest,
    session: Session = Depends(get_session),
):
    if session.get(Policy, policy_id) is None:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id!r} not found.")

    rule = CoverageRule(
        policy_id=policy_id,
        service_type=req.service_type,
        annual_limit=req.annual_limit,
        coverage_percent=req.coverage_percent,
        is_active=True,
    )
    session.add(rule)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A coverage rule for {req.service_type.value} already exists on this policy.",
        )
    session.refresh(rule)
    return rule


@router.get(
    "/policies/{policy_id}/coverage-rules",
    response_model=list[CoverageRuleResponse],
)
def list_coverage_rules(policy_id: str, session: Session = Depends(get_session)):
    if session.get(Policy, policy_id) is None:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id!r} not found.")
    rules = session.query(CoverageRule).filter_by(policy_id=policy_id).all()
    return rules


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
