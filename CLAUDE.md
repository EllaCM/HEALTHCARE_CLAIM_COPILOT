This repository is a starter structure for an agentic AI product that helps small and mid-sized U.S. outpatient clinics reduce clinician time spent on reimbursement preparation.

## MVP scope

This MVP focuses on four core capabilities:

1. **Encounter Evidence Extraction**
   - Turn fragmented clinical inputs into structured evidence.
2. **Code Supportability Review**
   - Recommend supportable CPT/ICD options based on documented facts.
3. **Justification Drafting**
   - Generate clinician-reviewable reimbursement justification drafts.
4. **Documentation Gap Detection**
   - Flag missing details that weaken claim support.

This MVP **does not** include a full payer and contract knowledge layer. It may use lightweight coding guidance and configurable clinic rules, but it does not attempt payer-specific reimbursement optimization.

## Design principles

- **Evidence-grounded**: outputs must be traceable to the chart, questionnaire, lab result, or treatment plan.
- **Human-in-the-loop**: clinicians approve or edit all reimbursement-facing content.
- **Compliance-first**: the system must not invent diagnoses, symptoms, treatments, or unsupported rationale.
- **Deterministic execution where possible**: repeated operational tasks should live in scripts.
- **Playbook-led agent behavior**: each agent should follow a documented process, not free-form improvisation.

## Two-layer operating model

Each agent is governed by two layers:

### 1. Playbooks (`playbooks/`)
Playbooks define **what should happen**.

They describe:
- the purpose of the agent
- the default execution path
- the known forks and judgment criteria
- what the agent may improvise and what it may not
- expected inputs, outputs, and handoffs

### 2. Scripts (`scripts/`)
Scripts define **what is executed deterministically**.

They are responsible for:
- file management
- structured parsing
- schema validation
- repeatable transformations
- API calls and service wrappers
- formatting and export steps

A script must produce the same output for the same input and configuration.

## Folder structure

```text
HEALTHCARE_CLAIM_COPILOT/
├── CLAUDE.md  #This file
├── docs/
│   └── system-overview.md     # already provided
├── playbooks/
│   ├── orchestrator-playbook.md      # already provided
│   ├── encounter-evidence-agent.md   # already provided
│   ├── code-supportability-agent.md  # already provided
│   ├── justification-drafting-agent.md  # already provided
│   └── documentation-gap-agent.md       # already provided
├── scripts/    # execution layer, include all the .sh / .py files
├── src/        # source code of this project
├── tests/      # test files
├── schemas/
|   └── encounter_package.schema.json    # already provided
└── .tmp/       # temporary files for processing outputs generated before the final outputs, do not submit.
```
On top of this scaffold:
Keep structured_bullets as the canonical intermediate artifact across agents.
Make the orchestrator block final draft generation when evidence is too weak, rather than letting the drafting agent guess.

## Recommended build sequence

1. Implement the shared encounter package schema.
2. Build deterministic extraction and validation scripts.
3. Build the Encounter Evidence Agent.
4. Add code supportability ranking.
5. Add justification drafting.
6. Add documentation gap detection.
7. Add clinician review UI and feedback capture.

## Success metrics for the MVP

- time to produce a clinician-reviewable justification draft
- clinician acceptance rate of suggested drafts
- rate of missing documentation detected before submission
- edit distance between draft and final approved version
- documentation-related denial reduction over baseline

## General requirements
- prioritize edit on top of existing files instead of rewriting the entire file
- unless the file has been edited, do not repeatedly read the files that have been read.
- concise output, thorough logic

## Coding requirements
- each file should not exceed 400 lines. if so, break it down into seperate files.
- There should be no more than 4 layers within each nested loop