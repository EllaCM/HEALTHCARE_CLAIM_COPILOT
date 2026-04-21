# System Overview

## Problem

Clinicians in outpatient settings spend too much time turning visit documentation into reimbursement-ready content. The same treatment may require different support language depending on how clearly the note describes the patient's condition, objective findings, prior treatment history, and medical necessity.

## Product goal

Help clinicians save time by converting visit documentation into:
- structured evidence
- supportable coding options
- draft justification content
- documentation gap alerts

## System boundary

The MVP begins **after the visit** and before final claim submission.

It covers:
- evidence extraction from notes and structured inputs
- code supportability review
- justification draft generation
- missing documentation detection

It does not cover:
- full payer contract intelligence
- autonomous claim submission
- patient billing and collections
- full appeal automation beyond optional draft reuse

## Primary users

- clinicians in outpatient clinics
- coders or billing staff where present
- clinic administrators evaluating workflow efficiency

## Core objects

### Encounter package
A normalized representation of a visit, including:
- patient condition
- symptoms
- objective findings
- treatment performed
- prior treatment history
- candidate diagnosis and procedure codes
- missing evidence flags

### Structured bullets
A standardized intermediate representation of justification content. These sit between raw notes and final reimbursement prose.

Example sections:
- patient condition
- functional limitation
- objective findings
- prior treatment history
- treatment provided
- medical necessity
- missing documentation

## Agent workflow

```text
Encounter inputs
  -> Encounter Evidence Agent
  -> Code Supportability Agent
  -> Justification Drafting Agent
  -> Documentation Gap Agent
  -> Clinician review
  -> Approved claim support package
```

## Orchestration model

A lightweight orchestrator should:
1. validate the encounter payload
2. call each agent in sequence
3. stop if evidence quality is too low
4. surface warnings before draft generation if documentation is weak
5. store all outputs with version history

## Guardrails

The system must not:
- invent facts not found in source records
- recommend unsupported upcoding
- hide uncertainty
- discard source links to evidence
- submit reimbursement-facing content without human review
