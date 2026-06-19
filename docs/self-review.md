# Self-Review

---

## What Works Well

### Pure-function adjudication engine

The adjudication engine (`app/services/adjudication.py`) takes an `AdjudicationInput` struct and returns an `AdjudicationOutput` struct. No database. No session. No framework. This makes the business rules directly testable: 16 tests run in under 0.03s and each test reads as a specification of a domain rule. The isolation also means the engine can be moved, re-used, or replaced without touching any other layer.

### Tests written before or alongside implementation — verifiable in git history

The test file (`tests/test_adjudication.py`) was committed before the adjudication engine implementation. The 22 tests across all three test files were written first and drove the implementation. The git log reflects this: `test: write all 21 tests before implementation (TDD)` precedes `feat: implement adjudication engine`.

### PHI architectural boundary

Clinical data (`diagnosisCode`, `providerName`, `description`) lives in a separate `LineItemClinicalDetail` entity. The adjudication engine's `AdjudicationInput` type does not have a field for it — it is structurally impossible for the engine to read PHI, not merely convention. The docstring in `submit_claim` marks the boundary explicitly.

### Deductible accumulation within a claim

Line items within a single claim are adjudicated in order, and each item's deductible and limit spend is visible to the next. This is handled via SQLAlchemy's identity map: the `AnnualDeductibleUsage` Python object is updated in memory after each item, so the next item reads the updated balance without a round-trip to the database. The comment in the code names the mechanism.

### Shared deductible, per-service-type limits

The deductible is policy-wide (shared across service types), while annual limits are per service type. This matches how real individual insurance policies work. The two tracking tables (`AnnualDeductibleUsage`, `AnnualLimitUsage`) have different keys: deductible is keyed by `(member, policy, year)`, limits are keyed by `(member, policy, service_type, year)`.

### Eligibility window is fully specified

The adjudication engine checks three independent eligibility conditions: policy status must be `ACTIVE`, date of service must be on or after the effective date, and date of service must be before the renewal date. The last check was missing in the initial design and was added after reviewing the gap — the upper bound bug was caught before shipping because the test for it was easy to reason about.

---

## What's Rough or Incomplete

### No Alembic migrations

The schema is created with `Base.metadata.create_all()` on startup. This works for a demo but means there is no migration history, no upgrade path, and no way to evolve the schema without dropping and recreating tables. Alembic was listed in `requirements.txt` and the `decisions.md` mentions it, but it was not set up within the assignment time.

### Dispute resolution does not update YTD balances

When a denied item is overridden to `APPROVED` via dispute resolution, the service creates a new `AdjudicationResult` with `approved_amount = billed_amount` but does not update `AnnualDeductibleUsage` or `AnnualLimitUsage`. This means a dispute-approved item does not count against the member's annual limit or deductible for the rest of the year. In production this would require a re-adjudication pass or an explicit balance adjustment. The service docstring documents this limitation.

### No API integration tests

The domain tests are thorough, but there are no tests that exercise the full HTTP → service → DB → JSON response cycle. The routes were verified manually with `curl` during development. An `httpx`-based `TestClient` test suite would catch serialization issues (like Decimal handling or lazy-load errors) before deployment.

### Dispute resolution approved amount is a simplification

On insurer override `APPROVED`, the approved amount is set to `billed_amount` — the insurer absorbs the full bill with no deductible or limit adjustment. A real system would let the adjudicator specify the amount, or re-run adjudication with a modified input (e.g., waiving the deductible). For the scope of this assignment the simplified override is sufficient, but it would not be acceptable in production.

### No loading strategy

All relationships are lazy-loaded. The API routes explicitly touch `item.adjudication_results` before returning to pre-load within the open session, but the approach is fragile: if a relationship is added later without updating the route, it produces an expired-instance error. A production version would use SQLAlchemy's `selectin` loading strategy declared on the relationship.

---

## What I Would Change With More Time

1. **Set up Alembic** with an initial migration and a `db upgrade head` step in the README. The `create_tables()` shortcut would be replaced entirely.

2. **Re-adjudication on dispute approval** — rather than paying `billed_amount` unconditionally, allow the insurer to specify an override amount, or re-run the engine with the deductible waived and the limit check skipped. This makes the financial outcome correct and keeps the AdjudicationResult as a complete audit trail.

3. **API integration tests** — add a `tests/test_api.py` using FastAPI's `TestClient` that covers the full claim submission → dispute → resolution path via HTTP. These would replace the manual `curl` verification.

4. **Explicit relationship loading** — declare `lazy="selectin"` on `Claim.line_items` and `LineItem.adjudication_results` so the routes do not need to manually touch collections.

5. **Policy expiry automation** — add a background task or a startup check that sets `status = EXPIRED` for policies whose `renewal_date` has passed. Currently, a stale policy remains `ACTIVE` until something explicitly updates it. The renewal_date upper bound check in the engine is the safety net, but the status should be authoritative.

---

## Edge Cases Not Handled

- **Duplicate claim detection** — submitting the same claim twice for the same service on the same date creates two records and runs adjudication twice. There is no idempotency key or duplicate check.
- **Zero-dollar billed amount** — a $0.00 line item would adjudicate to $0.00 approved with no deductible applied, which is technically correct but would produce a strange explanation. Not validated at the API layer.
- **Service date exactly on renewal date** — the check is `date_of_service >= renewal_date` which means the renewal date itself is not covered by the expiring policy. This is intentional (the new policy starts on that date), but it is a boundary that could surprise callers.
- **Balance update on dispute denial** — a dispute resolved as `DENIED` creates a new `AdjudicationResult` with `approved_amount = $0` but does not revert any balance changes from the original adjudication. Since the original adjudication was also denied, balances were never updated anyway. But if a previously approved item is re-disputed and denied, the approved spend would remain in the YTD balances — an overcount. This scenario is not reachable in the current flow (you cannot dispute an already-approved item to get a denial), but the model does not prevent it.
