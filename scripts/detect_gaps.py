"""Detect missing or weak documentation gaps against code requirements."""

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


SYSTEM_PROMPT = """You are a clinical documentation auditor for outpatient reimbursement.
Given encounter evidence and selected code requirements, identify documentation gaps.
Return valid JSON only.
Severity definitions:
  low    - helpful but not required for basic support
  medium - likely to improve supportability and reduce edits
  high   - required to justify the selected code or timed billing
Rules:
- Never fill in missing chart content.
- Never downgrade high compliance risks to lower severity to preserve workflow speed.
- Group related gaps into one action item where possible.
- recommendation must be one of: continue, warn, block."""

GAP_OUTPUT_SCHEMA = {
    "gaps": [
        {
            "gap_id": "string",
            "description": "string",
            "severity": "low | medium | high",
            "suggested_action": "string",
            "affected_sections": ["string"],
        }
    ],
    "recommendation": "continue | warn | block",
    "summary": "string",
}


def _strip_fences(raw: str) -> str:
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def detect_gaps(
    evidence: dict[str, Any],
    ranked_codes: list[dict[str, Any]],
    selected_code: str | None = None,
) -> dict[str, Any]:
    """Return structured gap analysis with a block/warn/continue recommendation."""
    client = _get_client()

    user_message = f"""## Extracted Evidence
{json.dumps(evidence, indent=2)}

## Ranked Code Options
{json.dumps(ranked_codes, indent=2)}

## Selected Code
{selected_code or "None selected yet — use the top-ranked code as reference"}

Identify gaps and return JSON matching this shape:
{json.dumps(GAP_OUTPUT_SCHEMA, indent=2)}
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
    codes_path = sys.argv[2]
    selected_code = sys.argv[3] if len(sys.argv) > 3 else None
    with open(evidence_path) as f:
        evidence = json.load(f)
    with open(codes_path) as f:
        codes = json.load(f)
    print(json.dumps(detect_gaps(evidence, codes, selected_code), indent=2))
