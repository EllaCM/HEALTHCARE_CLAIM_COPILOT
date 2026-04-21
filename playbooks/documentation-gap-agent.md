# Documentation Gap Agent Playbook

## Purpose

Detect missing or weak documentation that may reduce coding supportability or weaken reimbursement justification.

## What should happen

The agent should review the encounter package and selected code option, then identify what information is missing, weak, or ambiguous before the clinician submits a final justification.

## Inputs

- validated encounter package
- ranked code options
- selected code option if available

## Outputs

- list of missing documentation items
- severity level for each gap
- suggested action to resolve each gap
- block-or-warn recommendation for the orchestrator

## Default execution path

1. Review the evidence package and selected code requirements.
2. Compare documented facts against the minimum support requirements.
3. Identify gaps such as:
   - missing time spent
   - missing severity
   - missing functional limitation detail
   - missing prior treatment history
   - missing objective findings
4. Assign severity to each gap.
5. Recommend whether the workflow should continue, warn, or block.
6. Return structured prompts for the clinician.

## Known forks and judgment criteria

### Fork A: Minor gap
Continue the workflow and show a warning.

### Fork B: Major gap
Block final prose generation until the missing detail is supplied.

### Fork C: Ambiguous chart language
Return a clarification request instead of choosing an interpretation.

## Improvisation rules

The agent may:
- group related gaps into one action item
- prioritize the smallest set of additions needed to strengthen supportability

The agent may not:
- fill in missing chart content on behalf of the clinician
- downgrade major compliance risks to warnings
- hide missing requirements to preserve workflow speed

## Scripts used

- `scripts/detect_gaps.py`
- `scripts/validate_payload.py`

## Severity definitions

- `low`: helpful but not required for basic support
- `medium`: likely to improve supportability and reduce edits
- `high`: required to justify the selected code or timed billing
