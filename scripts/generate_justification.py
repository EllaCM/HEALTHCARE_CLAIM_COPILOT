"""Generate per-CPT justifications and overall draft prose in clinician's tone."""

import json
import os
import sys
from typing import Any

import anthropic

_client: anthropic.Anthropic | None = None


def _parse_json(raw: str) -> Any:
    raw = raw.strip()
    if "```" in raw:
        for part in raw.split("```"):
            candidate = part.lstrip("json").strip()
            if candidate.startswith(("{", "[")):
                raw = candidate
                break
    for ch in ("{", "["):
        idx = raw.find(ch)
        if idx != -1:
            raw = raw[idx:]
            break
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        if "Extra data" not in str(e):
            raise ValueError(f"JSON parse failed: {e}\n\nResponse (first 500 chars):\n{raw[:500]}") from e
    decoder = json.JSONDecoder()
    objects: list = []
    pos = 0
    while pos < len(raw):
        remaining = raw[pos:].lstrip()
        if not remaining:
            break
        pos += len(raw[pos:]) - len(remaining)
        try:
            obj, end = decoder.raw_decode(remaining)
            objects.append(obj)
            pos += end
        except json.JSONDecodeError:
            break
    if objects:
        return objects[0] if len(objects) == 1 else objects
    raise ValueError(f"Could not parse JSON from response (first 500 chars):\n{raw[:500]}")


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client



PER_CODE_SYSTEM_PROMPT = """You are a physical therapy clinical documentation specialist.
Write reimbursement justification text for each CPT code provided.
Return valid JSON only — an object mapping each CPT code to its justification paragraph.

Rules:
- Write in first-person clinical tone as the treating therapist.
- Each justification must directly reference objective findings, functional deficits,
  and skilled interventions documented in the evidence.
- Do not invent facts not found in the evidence.
- Keep each paragraph to 3-5 sentences — concise, reimbursement-ready.
- Clearly state medical necessity using documented evidence.
- Do not exaggerate severity or duration beyond what is documented."""

PER_CODE_SCHEMA = {
    "97110": "Justification paragraph for this code referencing the specific evidence...",
    "97140": "Justification paragraph for this code...",
}


def generate_per_code_justifications(
    evidence: dict[str, Any],
    cpt_codes: list[dict[str, Any]],
    gap_analysis: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Return a dict mapping each CPT code to a clinician-tone justification paragraph."""
    client = _get_client()

    codes_summary = [
        {"code": c.get("code"), "label": c.get("label"), "units": c.get("units")}
        for c in cpt_codes
    ]

    user_message = f"""## Encounter Evidence
{json.dumps(evidence, indent=2)}

## CPT Codes to Justify
{json.dumps(codes_summary, indent=2)}

## Documentation Gap Notes
{json.dumps(gap_analysis or {}, indent=2)}

Write one justification paragraph per CPT code. Return JSON matching this shape:
{json.dumps({c.get("code", "XXXXX"): "justification text" for c in cpt_codes}, indent=2)}
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=PER_CODE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    return _parse_json(response.content[0].text)


FULL_DRAFT_SYSTEM_PROMPT = """You are a clinical reimbursement writer for outpatient clinics.
Given structured evidence and a selected code, produce structured bullets and a concise draft paragraph.
Return valid JSON only.
Rules:
- Every bullet must include at least one source_evidence reference.
- Do not add clinical facts not found in the evidence.
- If evidence_quality is insufficient, set draft_paragraph to null and populate warnings.
- section must be one of: patient_condition, functional_limitation, objective_findings,
  prior_treatment_history, treatment_provided, medical_necessity, missing_documentation, other."""

ALL_CODES_SYSTEM_PROMPT = """You are a clinical reimbursement writer for outpatient clinics.
Given structured evidence and a list of CPT codes, produce structured bullets and a draft paragraph for EACH code.
Return valid JSON only — a single array with one object per CPT code.
Rules:
- Every bullet must include at least one source_evidence reference.
- Do not add clinical facts not found in the evidence.
- Each code's justification must be distinct and directly tied to the specific service billed.
- If a code lacks sufficient evidence, set its draft_paragraph to null, populate its warnings, and set evidence_quality to "insufficient".
- section must be one of: patient_condition, functional_limitation, objective_findings,
  prior_treatment_history, treatment_provided, medical_necessity, missing_documentation, other."""

ALL_CODES_ITEM_SCHEMA = {
    "code": "CPT code string",
    "label": "service label string",
    "structured_bullets": [
        {
            "section": "patient_condition | functional_limitation | objective_findings | prior_treatment_history | treatment_provided | medical_necessity | missing_documentation | other",
            "label": "string",
            "content": "string",
            "source_evidence": [{"source_type": "string", "document_id": "string", "text_span": "string"}],
            "confidence_score": "number 0-1",
        }
    ],
    "draft_paragraph": "string or null",
    "warnings": ["string"],
    "evidence_quality": "strong | partial | insufficient",
}

DRAFT_OUTPUT_SCHEMA = {
    "structured_bullets": [
        {
            "section": "patient_condition | functional_limitation | objective_findings | prior_treatment_history | treatment_provided | medical_necessity | missing_documentation | other",
            "label": "string",
            "content": "string",
            "source_evidence": [{"source_type": "string", "document_id": "string", "text_span": "string"}],
            "confidence_score": "number 0-1",
        }
    ],
    "draft_paragraph": "string or null",
    "warnings": ["string"],
    "evidence_quality": "strong | partial | insufficient",
}


def generate_justification(
    evidence: dict[str, Any],
    selected_code: dict[str, Any],
    gap_analysis: dict[str, Any] | None = None,
    clinic_formatting: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return structured bullets and optional draft prose for the selected code (legacy full-draft path)."""
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
        system=FULL_DRAFT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    return _parse_json(response.content[0].text)


def generate_all_justifications(
    evidence: dict[str, Any],
    ranked_codes: list[dict[str, Any]],
    gap_analysis: dict[str, Any] | None = None,
    clinic_formatting: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Single API call returning structured bullets + draft prose for every ranked CPT code."""
    client = _get_client()

    codes_context = [
        {
            "code": c.get("code"),
            "label": c.get("label"),
            "units": c.get("units"),
            "evidence_summary": c.get("evidence_summary", ""),
            "missing_elements": c.get("missing_elements", []),
        }
        for c in ranked_codes
    ]

    user_message = f"""## Extracted Evidence
{json.dumps(evidence, indent=2)}

## CPT Codes to Justify
{json.dumps(codes_context, indent=2)}

## Gap Analysis
{json.dumps(gap_analysis or {}, indent=2)}

## Clinic Formatting Preferences
{json.dumps(clinic_formatting or {}, indent=2)}

Return a JSON array with one object per CPT code. Each object must match this schema:
{json.dumps(ALL_CODES_ITEM_SCHEMA, indent=2)}
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=ALL_CODES_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    result = _parse_json(response.content[0].text)
    return result if isinstance(result, list) else [result]


if __name__ == "__main__":
    evidence_path = sys.argv[1]
    code_path = sys.argv[2]
    with open(evidence_path) as f:
        evidence = json.load(f)
    with open(code_path) as f:
        selected_code = json.load(f)
    print(json.dumps(generate_justification(evidence, selected_code), indent=2))
