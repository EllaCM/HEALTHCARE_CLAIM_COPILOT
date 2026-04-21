"""Generate structured bullets and reimbursement justification draft prose."""

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


SYSTEM_PROMPT = """You are a clinical reimbursement writer for outpatient clinics.
Given structured evidence and a selected code, produce structured bullets and a concise draft paragraph.
Return valid JSON only.
Rules:
- Every bullet must include at least one source_evidence reference with source_type and document_id.
- Do not add clinical facts not found in the evidence.
- Do not exaggerate severity, duration, frequency, or medical necessity.
- If evidence_quality is insufficient, set draft_paragraph to null and populate warnings.
- section must be one of: patient_condition, functional_limitation, objective_findings,
  prior_treatment_history, treatment_provided, medical_necessity, missing_documentation, other."""

DRAFT_OUTPUT_SCHEMA = {
    "structured_bullets": [
        {
            "section": "patient_condition | functional_limitation | objective_findings | prior_treatment_history | treatment_provided | medical_necessity | missing_documentation | other",
            "label": "string",
            "content": "string",
            "source_evidence": [
                {"source_type": "string", "document_id": "string", "text_span": "string"}
            ],
            "confidence_score": "number 0-1",
        }
    ],
    "draft_paragraph": "string or null",
    "warnings": ["string"],
    "evidence_quality": "strong | partial | insufficient",
}


def _strip_fences(raw: str) -> str:
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def generate_justification(
    evidence: dict[str, Any],
    selected_code: dict[str, Any],
    gap_analysis: dict[str, Any] | None = None,
    clinic_formatting: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return structured bullets and optional draft prose for the selected code."""
    client = _get_client()

    user_message = f"""## Extracted Evidence
{json.dumps(evidence, indent=2)}

## Selected Code
{json.dumps(selected_code, indent=2)}

## Gap Analysis
{json.dumps(gap_analysis or {}, indent=2)}

## Clinic Formatting Preferences
{json.dumps(clinic_formatting or {}, indent=2)}

Generate structured bullets and a draft paragraph. Return JSON matching this shape:
{json.dumps(DRAFT_OUTPUT_SCHEMA, indent=2)}
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    return json.loads(_strip_fences(response.content[0].text))


if __name__ == "__main__":
    evidence_path = sys.argv[1]
    code_path = sys.argv[2]
    with open(evidence_path) as f:
        evidence = json.load(f)
    with open(code_path) as f:
        selected_code = json.load(f)
    print(json.dumps(generate_justification(evidence, selected_code), indent=2))
