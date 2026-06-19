# Decisions & Trade-offs

This document captures design decisions made during planning and implementation — what was built, what wasn't, the assumptions made, and the reasoning behind each choice.

---

## What We're Building

An insurance claims processing system that:
- Accepts claim submissions with line items from members
- Adjudicates each line item against coverage rules
- Tracks claims and line items through their lifecycle states
- Produces explanations for every coverage decision
- Allows members to dispute decisions

---

## Scope Boundaries

### In Scope
- Individual policy only
- Claim submission with one or more line items
- Adjudication of each line item against coverage rules (service type coverage, annual limits, shared deductible)
- Claim and line item lifecycle state management
- Denial explanations with human-readable text
- Member dispute flow with manual insurer override

### Explicitly Out of Scope

| Excluded | Reason |
|---|---|
| Group / family floater policies | Out of assignment scope; system is designed to extend to these in future |
| Authentication, login, user registration | Not part of claims processing; assignment explicitly excludes it |
| Policy enrollment / purchase flows | Adjacent concern, not evaluated |
| Email notifications, dashboards, analytics | Assignment explicitly excludes it |
| Prior authorization | Adds significant complexity; not required for core adjudication |
| Coordination of benefits (multiple insurers) | Member has exactly one active policy |
| Network negotiation / customary charges | Billed amount treated as allowed amount; simplification documented |
| Out-of-pocket maximum | Deductible + coverage percent is sufficient for the scope |
| Admin panels, provider account management | Assignment explicitly excludes it |
| PAID claim state | No payment disbursement use cases in scope; CLOSED is the terminal adjudication state |
| Manual review queue (pre-decision) | No reviewer role exists; all adjudication is automatic; post-decision review handled via dispute flow |

---

## Domain Design Decisions

### Policy Model — Individual Only

**Decision:** Support only individual policies for now. A `policyType` field is included on the Policy entity as an extension point.

**Why:** The assignment specifies individual plans. Group and floater policies would require shared benefit pools across members — a significant modeling change. The `policyType` field ensures the data model accommodates this without a breaking schema change later.

**Rejected alternative:** Modeling group policy from the start — adds complexity without evaluation benefit.

---

### Coverage Rules — One Rule Per Service Type Per Policy

**Decision:** Coverage is defined as a set of `CoverageRule` records attached to a policy. Each rule covers exactly one service type and specifies the annual limit and coverage percentage.

**Why:** Normalized, configurable, and queryable. Each adjudication step looks up one rule by `(policyId, serviceType)`. Adding or modifying coverage for a service type is a data change, not a code change.

**Rejected alternative:** Hard-coding coverage rules in application logic — would require code deployments to change coverage terms.

---

### Deductible — Shared Annual Pool

**Decision:** The annual deductible is a single amount on the Policy, shared across all covered service types. Year-to-date deductible spend is tracked per member per policy year.

**Why:** This is how real individual insurance policies work. A per-service-type deductible is unusual and would be less realistic to model.

**Implication:** During adjudication, the deductible balance is checked and reduced before calculating the insurer's share. The deductible accumulates across all claims in a policy year and resets on the policy renewal date.

**Rejected alternative:** Per-service-type deductible — simpler to implement but unrealistic and harder to explain in review.

---

### Cost-Sharing Model — Deductible + Coverage Percent Only

**Decision:** The two cost-sharing levers are: (1) shared annual deductible, and (2) coverage percent (what % the insurer pays after the deductible is met).

**Why:** Covers the core adjudication math without introducing copay/coinsurance distinctions, OOP maximum, or network tiers. Sufficient to demonstrate meaningful adjudication logic.

**Rejected:** Copays, OOP maximum, coinsurance terminology — adds complexity without proportional evaluation value given the time constraint.

---

### Service Types — Strict Enum

**Decision:** Service types are a fixed enum, not a free-text field.

**Supported types:**
- `PREVENTIVE_CARE`
- `SPECIALIST_VISIT`
- `EMERGENCY_CARE`
- `INPATIENT_HOSPITAL`
- `OUTPATIENT_PROCEDURE`
- `DIAGNOSTIC_LAB`
- `IMAGING`
- `PHYSICAL_THERAPY`
- `PRESCRIPTION_DRUGS`
- `MENTAL_HEALTH`

**Why:** A strict enum makes coverage rules exhaustive and testable. Unknown service types fail fast at the boundary rather than producing silent adjudication errors.

**Rejected alternative:** Free-text service type — flexible but unvalidatable; coverage rule lookups would be fragile.

---

### Network / Customary Charges — Out of Scope

**Decision:** Billed amount is treated as the allowed amount. No in-network / out-of-network distinction.

**Why:** Network negotiation requires provider data and fee schedule logic. It does not affect the core adjudication model being evaluated. Explicitly documented so the simplification is visible.

---

## State Machine Decisions

### Claim State Machine

```
SUBMITTED → UNDER_REVIEW → CLOSED ⇄ REOPENED
```

**SUBMITTED:** Claim has been received. No adjudication has run yet.

**UNDER_REVIEW:** Adjudication is running or in progress.

**CLOSED:** All line items have a final adjudication result. Terminal state until a dispute is filed.

**REOPENED:** A member has filed a dispute on at least one line item. The claim re-enters review.

**Transition rules:**
- `SUBMITTED → UNDER_REVIEW`: Automatic on submission
- `UNDER_REVIEW → CLOSED`: All line items adjudicated
- `CLOSED → REOPENED`: Automatic when any line item dispute is filed
- `REOPENED → UNDER_REVIEW`: Insurer begins dispute review
- `UNDER_REVIEW → CLOSED`: All disputes resolved

---

### Line Item State Machine

```
PENDING → APPROVED
        → DENIED
             ↓ (either)
          DISPUTED → UNDER_REVIEW → APPROVED
                                  → DENIED
```

**PENDING:** Line item submitted, not yet adjudicated.

**APPROVED:** Service type is covered by the policy; adjudication completed. `approvedAmount` may be less than `billedAmount` if the annual limit is partially exhausted.

**DENIED:** Service type is not covered, or the member was not eligible, or the annual limit is fully exhausted.

**DISPUTED:** Member has filed a dispute against this line item's decision.

**UNDER_REVIEW:** Insurer is manually reviewing the dispute.

**Key design decision — binary status:** Line item status is binary (`APPROVED` / `DENIED`). Whether the insurer pays the full billed amount or a lesser amount is captured in `approvedAmount` on the `AdjudicationResult`, not in the status. This avoids a third `PARTIALLY_APPROVED` state that would create dual sources of truth.

**Key design decision — deductible and APPROVED:** If a covered line item is fully consumed by the annual deductible (insurer pays $0), the status is still `APPROVED`. `APPROVED` means the service type is covered by the policy. `DENIED` means it is not. The amounts explain the payment outcome.

---

### Dispute Resolution

**Decision:** Disputes are resolved by manual insurer override. The insurer provides a decision (`APPROVED` or `DENIED`) and the line item is updated accordingly. No automatic re-adjudication.

**Why:** Re-adjudication would produce the same result for rule-based denials. Disputes are inherently exceptions that require human judgment — the assignment confirms this.

---

## Claim Outcome — Computed, Not Stored

**Decision:** There is no `PARTIALLY_APPROVED` status on a claim. The claim's payment outcome (fully covered, partially covered, fully denied) is derived from its line items at read time.

**Why:** A stored `PARTIALLY_APPROVED` status would need to stay in sync with every line item state change — a consistency risk. The line items are the source of truth for outcomes. Helpers like `totalApproved()` and `totalDenied()` expose the summary without duplicating state.

---

### PHI Isolation — LineItemClinicalDetail

**Decision:** Clinical fields (`diagnosisCode`, `providerName`, `description`) are stored in a separate `LineItemClinicalDetail` entity, not directly on `LineItem`.

**Why:** The adjudication engine only needs `serviceType`, `billedAmount`, and `dateOfService` to make a coverage decision. It never needs clinical detail. Separating PHI into its own entity ensures the core engine is architecturally prevented from touching it. Clinical detail is joined in only at the API response layer for endpoints that explicitly require it (member's claim detail view, insurer dispute review).

**In production this boundary would carry:** field-level encryption, audit logging on reads, and role-based access controls. For this scope, the structural separation is the primary signal.

**Rejected alternative:** Flat `LineItem` table with all fields — simpler schema but no architectural PHI boundary; clinical data leaks into list queries and adjudication reads by default.

---

### Dispute Resolution — Who and How

**Decision:** Disputes are resolved via a single API endpoint (`POST /disputes/{id}/resolve`) that accepts a resolution decision and notes. The caller is assumed to be an authorized insurer by convention — not enforced by the system (no auth in scope).

**Why:** We have no user system, no reviewer roles, and no assignment queue. The simplest model that satisfies the requirement is a direct API call with the decision payload.

**In production:** This endpoint would be gated behind an insurer role with audit logging. For this scope, authorization is documented as out of band.

---

## Assumptions

1. A member has exactly one active policy at any time.
2. The policy year resets on the `renewalDate` field of the policy. Deductible balances and annual limits reset annually.
3. A claim's date of service is determined by its line items. Each line item records the date the service was rendered. Eligibility is checked per line item against the policy effective/expiry dates.
4. The adjudication engine processes line items sequentially within a claim. Order does not affect outcome except in deductible application (which accumulates across line items in submission order).
5. There is no fraud detection, duplicate claim detection, or prior authorization logic.

---

## Technical Stack

### Language — Python 3.11+

**Decision:** Python over Java (primary experience) or TypeScript.

**Why:** Python's readability means the adjudication engine reads like the domain documentation — business rules are visible, not buried in framework boilerplate. Java/Spring Boot was ruled out: excessive scaffolding for a 48-hour submission and setup friction for reviewers cloning the repo. TypeScript was a valid alternative but adds ceremony (type imports, interface definitions, async chains) that obscures domain logic without proportional benefit.

---

### Framework — FastAPI

**Decision:** FastAPI for the REST API layer.

**Why:** Auto-generates Swagger UI at `/docs` and ReDoc at `/redoc` — zero extra work for a demo-able interface. Pydantic validation aligns with our strict enum approach on service types and state transitions. Minimal boilerplate keeps domain logic in focus.

**Interface:** Swagger UI at `/docs` serves as the primary interface for demonstrating claim flows. A web UI was considered but deprioritised — it adds frontend complexity that is not part of the evaluation criteria.

---

### ORM — SQLAlchemy (sync)

**Decision:** SQLAlchemy with synchronous sessions.

**Why:** Mature, explicit, maps cleanly to our 10-entity model. Sync mode is simpler to reason about for a domain-heavy system — async SQLAlchemy adds complexity that isn't needed at this scale.

---

### Migrations — Alembic

**Decision:** Alembic for schema migrations.

**Why:** Standard SQLAlchemy migration tool. Provides a clean upgrade path and a readable migration history, which matters for a submission where commit history is reviewed.

---

### Database — SQLite

**Decision:** SQLite as the persistence layer.

**Why:** Zero infrastructure — reviewers clone and run with no Docker, no database server, no environment variables. Fully sufficient for the adjudication workload (no concurrency requirements, no scale constraints).

**One deliberate constraint — financial decimal precision:** SQLite's `REAL` type is floating-point and cannot represent money exactly. All monetary fields (`billedAmount`, `approvedAmount`, `deductibleApplied`, `limitCapApplied`, etc.) use SQLAlchemy's `Numeric(precision=10, scale=2, asdecimal=True)`, which SQLite stores as text and returns as Python `Decimal` objects. Exact arithmetic, no floating-point drift.

---

### Testing — pytest

**Decision:** pytest with descriptive test names encoding domain rules.

**Why:** Test names like `test_claim_denied_when_annual_limit_exhausted` are readable as domain specifications — they communicate intent without reading the test body. Tests are written against the adjudication engine directly, independent of the HTTP layer, so they verify business rules rather than API plumbing.

---

*This document will be updated as implementation decisions are made.*
