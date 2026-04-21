"""Extract structured evidence sections from raw encounter inputs via the Claude API."""

import json
import os
import sys
from typing import Any

import anthropic

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


SYSTEM_PROMPT = """You are a clinical evidence extractor for outpatient reimbursement workflows.
Extract structured facts from the provided visit materials. Return valid JSON only.
Rules:
- Only include chart-supported facts.
- Use low confidence scores for implied or ambiguous evidence.
- Never invent diagnoses, severity, duration, or prior therapy not found in the source.
- For each item, include a source_type and document_id reference."""

EXTRACT_SCHEMA = {
    "patient_condition": "string",
    "symptoms": ["string"],
    "functional_limitation": "string",
    "objective_findings": ["string"],
    "prior_treatment_history": ["string"],
    "treatment_provided": ["string"],
    "medical_necessity_signals": ["string"],
    "missing_information": ["string"],
    "confidence_score": "number 0-1",
}


def extract_evidence(
    encounter_note: str,
    supporting_docs: dict[str, str] | None = None,
    encounter_id: str = "unknown",
) -> dict[str, Any]:
    """Return a structured evidence dict extracted from the encounter note."""
    client = _get_client()

    docs_section = ""
    if supporting_docs:
        docs_section = "\n\n## Supporting Documents\n" + "\n\n".join(
            f"### {k}\n{v}" for k, v in supporting_docs.items()
        )

    user_message = f"""## Encounter Note (encounter_id: {encounter_id})
{encounter_note}{docs_section}

Extract evidence into JSON with this shape:
{json.dumps(EXTRACT_SCHEMA, indent=2)}
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


if __name__ == "__main__":
    note_path = sys.argv[1]
    encounter_id = sys.argv[2] if len(sys.argv) > 2 else "cli"
    with open(note_path) as f:
        note = f.read()
    result = extract_evidence(note, encounter_id=encounter_id)
    print(json.dumps(result, indent=2))
