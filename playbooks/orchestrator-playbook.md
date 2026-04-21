# Orchestrator Playbook

## Purpose

Coordinate the end-to-end post-visit workflow from raw encounter inputs to a clinician-reviewable claim support package.

## Inputs

- encounter note
- treatment plan
- questionnaires
- lab or imaging summaries if available
- clinician-selected or pre-filled candidate codes if available
- clinic configuration

## Outputs

- validated encounter package
- agent outputs from each stage
- final review bundle for the clinician
- structured logs for audit and debugging

## Default execution path

1. Validate raw input payload.
2. Run the Encounter Evidence Agent.
3. Run the Code Supportability Agent.
4. Run the Documentation Gap Agent.
5. If documentation is minimally sufficient, run the Justification Drafting Agent.
6. Assemble the clinician review bundle.
7. Persist outputs and version metadata.

## Known forks and judgment criteria

### Fork A: Missing or malformed input
- If required fields are missing, stop the pipeline.
- Return a structured error and request correction.

### Fork B: Insufficient evidence quality
- If evidence extraction confidence is below threshold, do not generate final justification prose.
- Return a request for more documentation.

### Fork C: No supportable code found
- If no code option meets the clinic threshold, escalate to clinician or coder review.
- Provide the strongest evidence summary and explain why no code was recommended.

### Fork D: Documentation gaps found
- If gaps are minor, continue and annotate draft with warnings.
- If gaps are major, block final recommendation and ask for missing inputs.

## Improvisation rules

The orchestrator may:
- reorder non-dependent validations
- retry deterministic script steps after transient failures
- attach warnings and confidence levels to downstream payloads

The orchestrator may not:
- overwrite clinical facts
- invent missing structured data
- force downstream generation when blocking criteria are met

## Scripts used

- `scripts/validate_payload.py`
- `scripts/extract_evidence.py`
- `scripts/rank_codes.py`
- `scripts/detect_gaps.py`
- `scripts/generate_justification.py`

## Handoff contract

All downstream agents receive a single normalized encounter package that conforms to `schemas/encounter_package.schema.json`.
