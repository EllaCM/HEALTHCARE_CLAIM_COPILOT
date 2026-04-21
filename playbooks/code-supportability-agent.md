# Code Supportability Agent Playbook

## Purpose

Recommend supportable CPT and ICD options based on documented evidence, while preventing unsupported or overly aggressive coding recommendations.

## What should happen

The agent should map extracted evidence to ranked code options and explain why each option is supportable, borderline, or unsupported.

## Inputs

- validated encounter package
- clinic coding configuration
- optional clinician-preferred code list

## Outputs

- ranked CPT and ICD code options
- supportability score per code
- explanation of supporting evidence
- missing requirements per code
- compliance warnings where relevant

## Default execution path

1. Receive the validated encounter package.
2. Compare extracted evidence against code requirement templates.
3. Generate candidate code options.
4. Rank options by supportability first, then by workflow usefulness.
5. Annotate each option with:
   - evidence summary
   - missing elements
   - confidence level
   - compliance warning if applicable
6. Return one recommended option plus alternatives.

## Known forks and judgment criteria

### Fork A: Clinician-preferred code is supportable
Return it as recommended if it clears the supportability threshold.

### Fork B: Clinician-preferred code is weakly supported
Return it with a warning and provide a safer alternative.

### Fork C: Multiple supportable codes exist
Show the recommended option, a conservative option, and any higher-risk option with clear labeling.

### Fork D: No supportable code exists
Escalate to clinician or coder review and explain the missing evidence.

## Improvisation rules

The agent may:
- rank equivalent codes based on documented specificity
- suggest safer alternatives when the preferred code is weakly supported

The agent may not:
- optimize for reimbursement over documentation support
- recommend a code solely because it is common for the specialty
- hide uncertainty or missing evidence

## Scripts used

- `scripts/rank_codes.py`
- `scripts/validate_payload.py`

## Output format expectations

Each recommended code should include:
- code
- label
- supportability score
- evidence summary
- missing elements
- compliance flags
