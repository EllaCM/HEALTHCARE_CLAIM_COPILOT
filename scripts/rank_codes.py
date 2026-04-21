"""Rank CPT/ICD codes by supportability against extracted encounter evidence."""

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


SYSTEM_PROMPT = """You are a clinical coding advisor for outpatient reimbursement.
Given structured encounter evidence and candidate codes, rank them by documentation supportability.
Return valid JSON only — an array of ranked code objects.
Rules:
- Rank by evidence support first, then workflow usefulness.
- Flag any code that would require upcoding or unsupported rationale.
- Always include a compliance_warning field (null if none).
- Never recommend a code solely because it is common for the specialty.
- Never hide uncertainty or missing evidence."""

RANK_OUTPUT_SCHEMA = [
    {
        "code": "CPT or ICD string",
        "label": "string",
        "supportability_score": "number 0-1",
        "rank": "integer starting at 1",
        "evidence_summary": "string",
        "missing_elements": ["string"],
        "compliance_warning": "string or null",
    }
]


def _strip_fences(raw: str) -> str:
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def rank_codes(
    evidence: dict[str, Any],
    candidate_codes: list[dict[str, str]] | None = None,
    clinic_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return a ranked list of code options with supportability annotations."""
    client = _get_client()

    user_message = f"""## Extracted Evidence
{json.dumps(evidence, indent=2)}

## Candidate Codes
{json.dumps(candidate_codes or [], indent=2)}

## Clinic Configuration
{json.dumps(clinic_config or {}, indent=2)}

Rank these codes and return a JSON array matching this shape:
{json.dumps(RANK_OUTPUT_SCHEMA, indent=2)}
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    return json.loads(_strip_fences(response.content[0].text))


if __name__ == "__main__":
    evidence_path = sys.argv[1]
    codes_path = sys.argv[2] if len(sys.argv) > 2 else None
    with open(evidence_path) as f:
        evidence = json.load(f)
    codes = None
    if codes_path:
        with open(codes_path) as f:
            codes = json.load(f)
    print(json.dumps(rank_codes(evidence, codes), indent=2))
