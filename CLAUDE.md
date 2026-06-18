# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A take-home engineering assignment: build a working **Insurance Claims Processing System** for evaluation by Realfast. The assignment tests domain modeling, engineering judgment, test-driven thinking, and AI collaboration.

Assignment specs are in `assignment instructions/`.

---

## Required Submission Structure

```
app/                    # Application code
docs/domain-model.md    # Entities, relationships, state machines
docs/decisions.md       # What was built, what wasn't, assumptions
docs/self-review.md     # Honest assessment
ai-artifacts/           # Raw JSONL session logs (mandatory) + chat exports
README.md               # Setup and run instructions (must work from clone)
```

The `.git` folder must be included in the final zip/tarball.

---

## Domain: Insurance Claims Processing

### Core entities to model

- **Member** — holds a policy; submits claims
- **Policy** — defines coverage rules (which service types are covered, up to what limits, with what deductible)
- **Claim** — submitted by a member; contains one or more line items
- **Line Item** — a single charge/service on a claim; adjudicated independently
- **Coverage Rule** — encodes what is covered and how much is payable (e.g. "service type X covered up to $Y per year")
- **Adjudication Result** — per-line-item decision with explanation (approved/denied/partially approved + reason)
- **Dispute** — member challenge to a denied/partially approved decision

### State machines

Claims and line items have independent lifecycles. A claim can be partially approved (some line items approved, some denied, some under review). Key states to model:

- **Claim**: `submitted → under_review → approved | partially_approved | denied → paid`
- **Line Item**: `submitted → adjudicated (covered | denied | partial) → paid | disputed`

### What's in scope

- Claim submission with line items
- Coverage rule application (limits, deductibles, service type coverage)
- Lifecycle state tracking for claims and line items
- Decision explanations (the system must say *why* something was denied)
- Member disputes

### What's explicitly out of scope

- Authentication, user registration, login
- Policy purchase/enrollment flows
- Member/provider account management
- Email notifications, dashboards, admin panels, multi-tenancy

---

## Key Design Problems

These are the interesting questions to answer in the domain model:

1. **How are coverage rules represented?** (code, config, DSL — justify the choice)
2. **How is benefit exhaustion tracked?** (year-to-date usage against annual limits)
3. **How are partial approvals handled?** (claim state vs. line item state)
4. **How are denial reasons structured?** (member-readable explanations)

---

## Evaluation Criteria

The reviewers specifically look for:

- Tests that encode domain rules (not just HTTP status codes) — git history should show tests written before or alongside implementation, not after
- A coherent scope (3 things done well > 10 things done poorly)
- Ability to explain any part of the code: what it does, why it's there, where it could break
- Honest self-assessment in `docs/self-review.md`

---

## Submission Logistics

Contact: Sumanth Raj Urs — sumanth@realfast.ai (logistics only; requirements are intentionally left to the candidate).
