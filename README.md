# Insurance Claims Processing System

A claims adjudication engine built as a take-home assignment for Realfast.

---

## What It Does

- Accepts claim submissions with one or more line items
- Adjudicates each line item against the member's policy coverage rules (service type coverage, annual limits, shared deductible)
- Tracks claims and line items through independent lifecycle state machines
- Produces a human-readable explanation for every coverage decision — including the edge case where a covered service results in $0 payment because the deductible consumed it
- Supports member disputes with manual insurer override

---

## Prerequisites

- Python 3.9 or higher
- No database server, no Docker — SQLite is used as the persistence layer

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/sanjailal/Insurance-Claims-Processing-System.git
cd Insurance-Claims-Processing-System

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate.bat       # Windows

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Running Tests

```bash
python3 -m pytest tests/ -v
```

Expected output: **22 tests pass**, 0 skipped.

The test suite has two layers:

- `tests/test_adjudication.py` — 16 pure-function tests against the adjudication engine. No database, no HTTP. Run in ~0.03s. These encode the domain rules: eligibility windows, deductible mechanics, annual limit exhaustion, explanation quality.
- `tests/test_claim_lifecycle.py` — 3 service-layer tests verifying multi-service adjudication, annual limit resets, and deductible resets across policy years.
- `tests/test_disputes.py` — 3 service-layer tests verifying dispute filing, resolution, and the duplicate-dispute guard.

---

## Running the Server

```bash
python3 -m uvicorn app.main:app --reload
```

The database tables are created automatically on startup. Interactive API documentation is available at:

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

---

## API Walkthrough

### 1. Seed a member and policy

```bash
python3 scripts/seed.py
```

This creates one member, one active individual policy ($500 annual deductible), and three coverage rules. It prints `member_id` and `policy_id` — copy these for the steps below.

### 2. Submit a claim

```bash
curl -X POST http://localhost:8000/claims \
  -H "Content-Type: application/json" \
  -d '{
    "member_id": "<member_id from seed>",
    "policy_id": "<policy_id from seed>",
    "line_items": [
      {
        "service_type": "PHYSICAL_THERAPY",
        "date_of_service": "2024-06-01",
        "billed_amount": "200.00"
      },
      {
        "service_type": "MENTAL_HEALTH",
        "date_of_service": "2024-06-01",
        "billed_amount": "150.00"
      }
    ]
  }'
```

The response includes each `line_item` with its `status` and `adjudication_result`. `PHYSICAL_THERAPY` is approved (deductible applied first, then 80% of remainder). `MENTAL_HEALTH` is denied `NOT_COVERED` — no coverage rule exists for it on this policy.

### 3. File a dispute

Copy a `line_item.id` from the response above.

```bash
curl -X POST http://localhost:8000/line-items/<line_item_id>/disputes \
  -H "Content-Type: application/json" \
  -d '{
    "member_id": "<member_id>",
    "reason": "This service is covered under my updated plan."
  }'
```

The claim transitions to `REOPENED` and the line item to `DISPUTED`.

### 4. Resolve the dispute

Copy the `dispute.id` from the response above.

```bash
curl -X POST http://localhost:8000/disputes/<dispute_id>/resolve \
  -H "Content-Type: application/json" \
  -d '{
    "resolution": "APPROVED",
    "notes": "Coverage confirmed by underwriting."
  }'
```

The dispute closes, the line item moves to `APPROVED`, and the claim closes when no open disputes remain.

---

## Project Structure

```
app/
  api/
    schemas.py          Pydantic request/response models
    routes.py           FastAPI endpoints
  models/
    enums.py            All domain enumerations
    db.py               SQLAlchemy ORM models (10 tables)
  services/
    adjudication.py     Pure adjudication engine — no DB, no framework
    claims.py           Claim submission and orchestration
    disputes.py         Dispute filing and resolution
  database.py           SQLAlchemy engine and session factory
  main.py               FastAPI application entry point

docs/
  domain-model.md       Entities, relationships, state machines
  decisions.md          Design decisions with alternatives rejected
  self-review.md        Honest assessment

scripts/
  seed.py               Creates demo member, policy, and coverage rules

tests/
  conftest.py           Fixtures — pure-function helpers and DB session
  test_adjudication.py  16 domain rule tests (no DB)
  test_claim_lifecycle.py  3 service-layer tests
  test_disputes.py      3 service-layer tests
```

---

## Domain Documentation

- [`docs/domain-model.md`](docs/domain-model.md) — full entity model, state machines, adjudication algorithm
- [`docs/decisions.md`](docs/decisions.md) — design decisions with reasoning and rejected alternatives
- [`docs/self-review.md`](docs/self-review.md) — honest self-assessment
