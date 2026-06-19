# Domain Model

This document describes the entities, relationships, state machines, and adjudication logic of the Insurance Claims Processing System.

---

## Entity Relationship Overview

```
Member ──────────────────── Policy ──────────────── CoverageRule (×N, one per serviceType)
  │                            │
  │                            ├── AnnualDeductibleUsage (×N, one per policy year)
  │                            │
  └──── Claim ─────────────────┘
           │
           └──── LineItem (×N)
                     │
                     ├──── LineItemClinicalDetail (1:1, PHI boundary)
                     ├──── AdjudicationResult (1:1, after adjudication)
                     └──── Dispute (1:N, history of disputes)

AnnualLimitUsage (per member × serviceType × policy year)
```

---

## Entities

### Member

The insured individual. Kept minimal — account management is out of scope.

| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `name` | string | |
| `dateOfBirth` | date | Reserved for future eligibility rules |

**Relationships:** Has one active Policy at a time. Submits many Claims.

---

### Policy

The insurance contract between a member and the insurer. Defines the financial terms and anchors the policy year.

| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `memberId` | UUID | FK → Member |
| `policyNumber` | string | Human-readable identifier (e.g. `POL-2024-00042`) |
| `policyType` | enum | `INDIVIDUAL` — extension point for `GROUP`, `FLOATER` in future |
| `effectiveDate` | date | Coverage begins |
| `renewalDate` | date | Policy year boundary — deductible and annual limits reset annually on this date |
| `annualDeductible` | decimal | Shared deductible across all covered service types |
| `status` | enum | `ACTIVE`, `EXPIRED`, `CANCELLED` |

**Relationships:** Has many CoverageRules (one per covered service type). Has many AnnualDeductibleUsage records (one per policy year).

**Policy year:** Defined by `renewalDate`. Year 1 = first year, Year 2 = second year, etc. All YTD tracking uses this integer, not calendar year. The renewal date itself provides the date boundary for any calculation.

---

### CoverageRule

Defines whether a service type is covered under a policy and at what financial terms. One rule per service type per policy.

| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `policyId` | UUID | FK → Policy |
| `serviceType` | enum | See ServiceType enum below |
| `annualLimit` | decimal | Maximum the insurer pays for this service type per policy year |
| `coveragePercent` | integer | Percentage the insurer pays after the deductible is satisfied (e.g. `80`) |
| `isActive` | boolean | Allows rules to be deactivated without deletion |

**Absence of a rule:** If no active CoverageRule exists for a submitted line item's service type, the line item is denied with `NOT_COVERED`. Absence equals exclusion.

**Deductible:** Lives on Policy as a single shared pool, not on individual CoverageRules. All covered line items draw from the same annual deductible balance.

---

### ServiceType Enum

```
PREVENTIVE_CARE       Annual checkups, screenings
SPECIALIST_VISIT      Cardiologist, dermatologist, etc.
EMERGENCY_CARE        Emergency room visits
INPATIENT_HOSPITAL    Admitted stays, surgeries
OUTPATIENT_PROCEDURE  Day procedures, minor surgery
DIAGNOSTIC_LAB        Blood tests, pathology
IMAGING               X-ray, MRI, CT scan
PHYSICAL_THERAPY      Rehabilitation, physiotherapy
PRESCRIPTION_DRUGS    Pharmacy
MENTAL_HEALTH         Therapy, psychiatry
```

---

### Claim

A request for reimbursement submitted by a member. Container for one or more line items.

| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `memberId` | UUID | FK → Member |
| `policyId` | UUID | Denormalized — captures which policy was active at submission time |
| `claimNumber` | string | Human-readable identifier (e.g. `CLM-2024-00001`) |
| `submittedAt` | timestamp | |
| `status` | enum | `SUBMITTED`, `UNDER_REVIEW`, `CLOSED`, `REOPENED` |

**No stored aggregate amounts.** `totalBilled`, `totalApproved`, `totalDenied` are computed from line items at read time — never stored on Claim.

**Why `policyId` on Claim?** Freezes the policy context at submission time. Supports future scenarios where a member renews or switches policies.

---

### LineItem

A single service or charge on a claim. The unit of adjudication.

| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `claimId` | UUID | FK → Claim |
| `serviceType` | enum | Determines which CoverageRule applies |
| `dateOfService` | date | Date the service was rendered — used for policy eligibility check |
| `billedAmount` | decimal | What the provider charged. Treated as the allowed amount (network negotiation out of scope) |
| `status` | enum | `PENDING`, `APPROVED`, `DENIED`, `DISPUTED`, `UNDER_REVIEW` |

**Status is binary at decision time:** `APPROVED` or `DENIED`. Whether the insurer pays the full billed amount or a lesser amount is captured in `AdjudicationResult`, not in the status.

**APPROVED with `approvedAmount = $0`:** Valid. Occurs when a covered line item is fully consumed by the annual deductible. The service is covered; the deductible consumed the payment this period. The explanation text must communicate this explicitly to the member — "$0 paid, but $X applied to your annual deductible."

---

### LineItemClinicalDetail

PHI (Protected Health Information) isolated from administrative data. Accessed only in contexts that explicitly require clinical detail — member claim view, insurer dispute review.

| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `lineItemId` | UUID | FK → LineItem (1:1) |
| `diagnosisCode` | string | ICD-10 code as submitted |
| `providerName` | string | Name of the treating provider |
| `description` | string | Free-text description of the service |

**PHI isolation principle:** The adjudication engine queries only `LineItem`. It never reads `LineItemClinicalDetail`. Clinical details are joined in only at the API response layer, and only for endpoints that require them (claim detail view, dispute review). In production, this table would carry field-level encryption and stricter audit logging.

---

### AdjudicationResult

The output of adjudicating a line item. Created automatically when adjudication runs. Replaced when a dispute is resolved with a manual override.

| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `lineItemId` | UUID | FK → LineItem (1:1 at any point in time) |
| `adjudicatedAt` | timestamp | |
| `approvedAmount` | decimal | What the insurer pays. Can be $0 on an APPROVED line item (deductible consumed it). |
| `deductibleApplied` | decimal | Amount from this line item that reduced the shared annual deductible balance |
| `limitCapApplied` | decimal | Amount excluded because the annual limit was exhausted or partially exhausted. $0 when limit was not a factor. |
| `denialReason` | enum | Nullable — only populated when line item is DENIED |
| `explanationText` | string | Human-readable breakdown of the decision, always populated |

**Denial reason enum:**

| Code | Meaning |
|---|---|
| `NOT_COVERED` | No active CoverageRule for this service type |
| `NOT_ELIGIBLE` | Policy was not active on the date of service |
| `LIMIT_EXHAUSTED` | Annual limit for this service type was $0 remaining |

**Amount breakdown:**

```
billedAmount (on LineItem)
 ├── limitCapApplied          excluded — annual limit ran out
 └── effectiveCoveredAmount   = billedAmount - limitCapApplied
      ├── deductibleApplied   member's deductible obligation
      └── afterDeductible     = effectiveCoveredAmount - deductibleApplied
           ├── approvedAmount  insurer pays  (= afterDeductible × coveragePercent%)
           └── memberCoinsurance member pays (= afterDeductible × (1 - coveragePercent%)) [derivable]

Total member pays = limitCapApplied + deductibleApplied + memberCoinsurance
```

---

### AnnualDeductibleUsage

Tracks cumulative deductible spend per member per policy year. One record per member per policy year.

| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `memberId` | UUID | |
| `policyId` | UUID | |
| `policyYear` | integer | Year 1, Year 2, etc. — anchored to Policy.renewalDate |
| `paidToDate` | decimal | Cumulative deductible paid so far this policy year |

**Separate from AnnualLimitUsage** because deductible is a single shared pool with no service type dimension.

---

### AnnualLimitUsage

Tracks cumulative benefit usage per member per service type per policy year. One record per (member × serviceType × policy year).

| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `memberId` | UUID | |
| `policyId` | UUID | |
| `serviceType` | enum | |
| `policyYear` | integer | |
| `usedToDate` | decimal | Cumulative amount used against the CoverageRule's annualLimit |

**Read during adjudication** to compute remaining limit before approving a line item. Updated after approval.

---

### Dispute

A member's challenge to a line item's adjudication decision. One line item can have many disputes over time (sequential, not concurrent).

| Attribute | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `lineItemId` | UUID | FK → LineItem |
| `memberId` | UUID | Denormalized for convenience |
| `filedAt` | timestamp | |
| `memberReason` | string | Member's stated reason for the dispute |
| `status` | enum | `OPEN`, `UNDER_REVIEW`, `RESOLVED` |
| `resolution` | enum | Nullable: `APPROVED` or `DENIED` — set when resolved |
| `resolvedAt` | timestamp | Nullable |
| `resolutionNotes` | string | Insurer's explanation of the resolution. Nullable. |

**One open dispute at a time:** A new dispute can only be filed when the line item is `APPROVED` or `DENIED` (not when it is already `DISPUTED` or `UNDER_REVIEW`). This is enforced at the application layer, not the schema.

**Historical record:** All resolved disputes are retained. Filing a new dispute after resolution creates a new Dispute record.

---

## State Machines

### Claim Lifecycle

```
┌───────────┐    adjudication     ┌──────────────┐    all items final    ┌────────┐
│ SUBMITTED │ ─────────────────►  │ UNDER_REVIEW │ ──────────────────►   │ CLOSED │
└───────────┘     begins          └──────────────┘                        └────────┘
                                        ▲                                      │
                                        │      insurer begins                  │ dispute
                                        │      dispute review                  │ filed
                                   ┌──────────┐                               │
                                   │ REOPENED │ ◄─────────────────────────────┘
                                   └──────────┘
```

| Transition | Trigger |
|---|---|
| `SUBMITTED → UNDER_REVIEW` | Adjudication begins automatically on submission |
| `UNDER_REVIEW → CLOSED` | All line items are `APPROVED` or `DENIED` |
| `CLOSED → REOPENED` | Any line item dispute is filed (automatic) |
| `REOPENED → UNDER_REVIEW` | Insurer begins reviewing the dispute |
| `UNDER_REVIEW → CLOSED` | All open disputes are resolved |

---

### Line Item Lifecycle

```
           ┌──────────┐
           │ PENDING  │
           └──────────┘
                │
       adjudication runs
          ┌─────┴─────┐
          ▼           ▼
     ┌──────────┐  ┌────────┐
     │ APPROVED │  │ DENIED │
     └──────────┘  └────────┘
          │              │
          └──────┬────────┘
            member disputes
                 ▼
          ┌──────────┐
          │ DISPUTED │
          └──────────┘
                │
         insurer reviews
                ▼
        ┌──────────────┐
        │ UNDER_REVIEW │
        └──────────────┘
                │
         override decision
          ┌─────┴─────┐
          ▼           ▼
     ┌──────────┐  ┌────────┐
     │ APPROVED │  │ DENIED │  ← member may dispute again from here
     └──────────┘  └────────┘
```

| Transition | Trigger |
|---|---|
| `PENDING → APPROVED` | Adjudication: service covered, amount calculated |
| `PENDING → DENIED` | Adjudication: not covered, not eligible, or limit exhausted |
| `APPROVED / DENIED → DISPUTED` | Member files a dispute |
| `DISPUTED → UNDER_REVIEW` | Insurer begins manual review |
| `UNDER_REVIEW → APPROVED / DENIED` | Insurer submits override decision |

---

### Dispute Lifecycle

| Transition | Trigger |
|---|---|
| `OPEN → UNDER_REVIEW` | Insurer begins reviewing |
| `UNDER_REVIEW → RESOLVED` | Override decision submitted |

---

## Adjudication Algorithm

Runs automatically when a claim is submitted. Processes each line item independently, in order. Steps run sequentially — the first failure produces a denial and stops.

```
For each LineItem in Claim:

  STEP 1 — ELIGIBILITY CHECK
  ─────────────────────────────────────────────────────────
  Is policy.status == ACTIVE?
  Is lineItem.dateOfService >= policy.effectiveDate
    AND < policy.renewalDate (for current year)?

  → FAIL: status = DENIED, denialReason = NOT_ELIGIBLE


  STEP 2 — COVERAGE CHECK
  ─────────────────────────────────────────────────────────
  Is there an active CoverageRule for lineItem.serviceType?

  → FAIL: status = DENIED, denialReason = NOT_COVERED


  STEP 3 — LIMIT CHECK
  ─────────────────────────────────────────────────────────
  limitRemaining = coverageRule.annualLimit - annualLimitUsage.usedToDate

  Is limitRemaining <= 0?

  → FAIL: status = DENIED, denialReason = LIMIT_EXHAUSTED


  STEP 4 — COMPUTE EFFECTIVE COVERED AMOUNT
  ─────────────────────────────────────────────────────────
  effectiveCoveredAmount = min(lineItem.billedAmount, limitRemaining)
  limitCapApplied        = lineItem.billedAmount - effectiveCoveredAmount


  STEP 5 — APPLY DEDUCTIBLE
  ─────────────────────────────────────────────────────────
  deductibleRemaining = policy.annualDeductible - annualDeductibleUsage.paidToDate
  deductibleApplied   = min(deductibleRemaining, effectiveCoveredAmount)

  Update: annualDeductibleUsage.paidToDate += deductibleApplied


  STEP 6 — APPLY COVERAGE PERCENT
  ─────────────────────────────────────────────────────────
  afterDeductible = effectiveCoveredAmount - deductibleApplied
  approvedAmount  = afterDeductible × (coverageRule.coveragePercent / 100)


  STEP 7 — UPDATE LIMIT USAGE
  ─────────────────────────────────────────────────────────
  Update: annualLimitUsage.usedToDate += effectiveCoveredAmount


  STEP 8 — RECORD RESULT
  ─────────────────────────────────────────────────────────
  LineItem.status = APPROVED
  Create AdjudicationResult:
    approvedAmount    = (calculated above)
    deductibleApplied = (calculated above)
    limitCapApplied   = (calculated above)
    denialReason      = null
    explanationText   = (generated from all amounts — must be explicit when approvedAmount = $0)
```

**After all line items are processed:**
If all line items are `APPROVED` or `DENIED` → Claim transitions to `CLOSED`.

---

## Dispute Resolution

When a member disputes a line item:

1. New `Dispute` record created with `status = OPEN`
2. `LineItem.status → DISPUTED`
3. `Claim.status → REOPENED` (automatic)

When the insurer resolves the dispute via `POST /disputes/{id}/resolve`:

1. `Dispute.status → RESOLVED`, resolution and notes recorded
2. `LineItem.status → APPROVED or DENIED` (per insurer decision)
3. New `AdjudicationResult` created (replaces previous — override decision)
4. If no other open disputes remain on the claim → `Claim.status → CLOSED`

---

## PHI Boundary

`LineItemClinicalDetail` is the PHI boundary. Fields within it (`diagnosisCode`, `providerName`, `description`) are never read by the adjudication engine and are excluded from all list/summary API responses. They are joined in only for:

- A member viewing the detail of their own claim
- An insurer reviewing an open dispute

In production this boundary would carry field-level encryption, access audit logging, and role-based read controls.
