# Justification Drafting Agent Playbook

## Purpose

Generate clinician-reviewable reimbursement justification drafts from structured evidence and selected code options.

## What should happen

The agent should turn chart-supported evidence into two outputs:
1. structured bullets for review and auditability
2. a concise reimbursement-ready draft paragraph

## Inputs

- validated encounter package
- selected or recommended code option
- documentation gap annotations
- clinic formatting preferences

## Outputs

- structured bullets grouped by justification section
- draft paragraph for claim support
- optional alternate format for internal coding review
- confidence notes and unsupported-content warnings

## Default execution path

1. Read the selected code and supporting evidence.
2. Build structured bullets under standard sections:
   - patient condition
   - functional limitation
   - objective findings
   - prior treatment history
   - treatment provided
   - medical necessity
3. Ensure every bullet links back to source evidence.
4. Generate a concise justification draft from the bullets.
5. Mark any sections that rely on weak or incomplete evidence.
6. Return the draft for clinician review.

## Known forks and judgment criteria

### Fork A: Evidence is strong and complete
Generate full structured bullets and draft prose.

### Fork B: Evidence is partial but still usable
Generate the draft with explicit warnings and highlight the missing additions.

### Fork C: Evidence is too weak
Do not generate final reimbursement prose. Return only structured bullets and missing-data prompts.

## Improvisation rules

The agent may:
- rewrite content for clarity and brevity
- convert extracted facts into medically neutral, reimbursement-ready language
- present both bullet and paragraph views

The agent may not:
- add new clinical facts
- exaggerate severity or duration
- create medical necessity statements unsupported by the chart

## Scripts used

- `scripts/generate_justification.py`
- `scripts/validate_payload.py`

## Quality bar

A good output should be:
- evidence-grounded
- concise
- readable by clinicians
- reusable in downstream review
- easy to edit section by section
