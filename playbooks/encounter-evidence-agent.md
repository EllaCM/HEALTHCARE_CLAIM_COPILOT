# Encounter Evidence Agent Playbook

## Purpose

Transform fragmented visit inputs into a structured, evidence-linked encounter package that downstream agents can trust.

## What should happen

The agent should read the available visit materials and extract only chart-supported facts relevant to coding and reimbursement justification.

## Inputs

- encounter note
- treatment plan
- patient questionnaires
- lab results or imaging summaries
- prior treatment history if available

## Outputs

- normalized evidence sections
- evidence links back to source material
- confidence scores on extracted elements
- unresolved ambiguity flags

## Default execution path

1. Parse all encounter inputs into structured sections.
2. Extract candidate evidence under these headings:
   - patient condition
   - symptoms
   - functional limitation
   - objective findings
   - prior treatment history
   - treatment provided
   - medical necessity signals
3. Attach source references for each extracted item.
4. Score confidence for each extracted item.
5. Mark uncertain or conflicting evidence.
6. Return a validated encounter package.

## Known forks and judgment criteria

### Fork A: Source conflict
If two sources conflict, prefer the most recent clinician-authored note and flag the conflict.

### Fork B: Weak evidence
If evidence is implied but not explicit, mark it as low confidence and do not promote it to a hard fact.

### Fork C: Missing section
If a key section is absent, return an empty value and a missing-data flag instead of inferring content.

## Improvisation rules

The agent may:
- normalize synonymous phrases into standard labels
- collapse duplicate facts across sources
- summarize repetitive findings into one evidence item

The agent may not:
- infer diagnoses that are not documented
- invent duration, severity, time spent, or failed prior therapy
- convert speculation into fact

## Scripts used

- `scripts/extract_evidence.py`
- `scripts/validate_payload.py`

## Minimum output sections

- `patient_condition`
- `functional_limitation`
- `objective_findings`
- `prior_treatment_history`
- `treatment_provided`
- `medical_necessity_signals`
- `missing_information`
