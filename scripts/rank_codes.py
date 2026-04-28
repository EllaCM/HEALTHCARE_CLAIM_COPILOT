"""Rank CPT codes by supportability and return CMS-1500-ready metadata."""

import json
import os
import sys
from typing import Any

import anthropic

_client: anthropic.Anthropic | None = None


def _parse_json(raw: str) -> Any:
    """Parse JSON from a model response. Handles fences, preamble, and multiple objects."""
    raw = raw.strip()
    # Strip markdown fences
    if "```" in raw:
        for part in raw.split("```"):
            candidate = part.lstrip("json").strip()
            if candidate.startswith(("{", "[")):
                raw = candidate
                break
    # Skip any preamble text before the first JSON structure
    for ch in ("{", "["):
        idx = raw.find(ch)
        if idx != -1:
            raw = raw[idx:]
            break
    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        if "Extra data" not in str(e):
            raise ValueError(f"JSON parse failed: {e}\n\nResponse (first 500 chars):\n{raw[:500]}") from e
    # "Extra data" means the model returned multiple objects — collect them into a list
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
        return objects
    raise ValueError(f"Could not parse JSON from response (first 500 chars):\n{raw[:500]}")


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


SYSTEM_PROMPT = """You are a clinical coding advisor for outpatient physical therapy reimbursement.
Given structured encounter evidence, recommend ALL applicable CPT codes ready for CMS-1500 submission.
A typical PT session documents 3-8 distinct billable services — return a separate code object for EACH service.
Return valid JSON only — an array of ranked code objects.

Rules:
- Return ALL CPT codes supported by the note, not just the top one. Each distinct service gets its own entry.
- Use GP modifier by default for all PT services delivered under a plan of care.
- Add modifier 59 only when a service is genuinely distinct and would otherwise be bundled.
- For timed codes use the 8-minute rule: 8-22 min = 1 unit, 23-37 min = 2, 38-52 min = 3, 53-67 min = 4.
- For untimed codes (e.g. 97010, 97012) always set units to 1.
- diagnosis_pointer maps to the letter of the relevant ICD-10 in the diagnosis list (A = first, B = second).
- supporting_docs must ONLY list clinical documentation items: objective findings, evaluation records,
  treatment notes, physician referral/plan of care, functional tests, ROM/strength measurements, outcome
  measures. Do NOT include administrative, billing, insurance, or prior-authorization requirements.
- Never recommend units beyond what is documented.
- Never hide compliance issues."""

# ── Static lookup table for common PT CPT codes (no API needed) ──────────────
_CPT_PT_LOOKUP: dict[str, dict] = {
    "97110": {"label": "Therapeutic Exercise",                         "timed": True},
    "97140": {"label": "Manual Therapy Techniques",                    "timed": True},
    "97530": {"label": "Therapeutic Activities",                       "timed": True},
    "97112": {"label": "Neuromuscular Reeducation",                    "timed": True},
    "97116": {"label": "Gait Training",                                "timed": True},
    "97124": {"label": "Massage",                                      "timed": True},
    "97032": {"label": "Electrical Stimulation (manual)",              "timed": True},
    "97033": {"label": "Iontophoresis",                                "timed": True},
    "97034": {"label": "Contrast Baths",                               "timed": True},
    "97035": {"label": "Ultrasound",                                   "timed": True},
    "97036": {"label": "Hubbard Tank",                                 "timed": True},
    "97750": {"label": "Physical Performance Test",                    "timed": True},
    "97760": {"label": "Orthotic Management and Training",             "timed": True},
    "97010": {"label": "Hot or Cold Packs",                            "timed": False},
    "97012": {"label": "Mechanical Traction",                          "timed": False},
    "97016": {"label": "Vasopneumatic Devices",                        "timed": False},
    "97018": {"label": "Paraffin Bath",                                "timed": False},
    "97022": {"label": "Whirlpool",                                    "timed": False},
    "97150": {"label": "Therapeutic Exercises - Group",                "timed": False},
    "97161": {"label": "Physical Therapy Evaluation - Low Complexity",      "timed": False},
    "97162": {"label": "Physical Therapy Evaluation - Moderate Complexity", "timed": False},
    "97163": {"label": "Physical Therapy Evaluation - High Complexity",     "timed": False},
    "97164": {"label": "Physical Therapy Re-evaluation",               "timed": False},
}


def fill_cpt_metadata(
    code: str,
    evidence: dict[str, Any],
    diagnoses: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Fill in CPT item metadata for a user-entered code.
    Uses the static lookup table for known PT codes — no API call needed.
    Returns a partial item dict with auto_filled=True and a notes list explaining
    any fields that still require clinician confirmation.
    """
    diagnoses = diagnoses or []
    info = _CPT_PT_LOOKUP.get(code.strip())

    notes: list[str] = []
    if info:
        label = info["label"]
        timed = info["timed"]
        units = 1
        if timed:
            notes.append(
                f"{code} is a timed code — units are set to 1 (default). "
                "Update based on documented minutes using the 8-minute rule: "
                "8-22 min = 1, 23-37 min = 2, 38-52 min = 3, 53-67 min = 4."
            )
    else:
        label = f"CPT {code}"
        timed = True
        units = 1
        notes.append(
            f"{code} is not in the standard PT lookup table. "
            "Verify the label, modifier, and unit count before submitting."
        )

    dx_pointer = "A"
    if len(diagnoses) > 1:
        notes.append(
            f"Multiple diagnoses on file ({', '.join(d['code'] for d in diagnoses)}). "
            "Confirm which diagnosis pointer applies to this code."
        )

    return {
        "code": code.strip(),
        "label": label,
        "modifier": "GP",
        "units": units,
        "dx_pointer": dx_pointer,
        "justification": "",
        "supportability_score": 0.0,
        "compliance_warning": None,
        "supporting_docs": [],
        "missing_elements": [],
        "evidence_summary": "",
        "auto_filled": True,
        "auto_fill_notes": notes,
    }


SINGLE_CODE_EVAL_PROMPT = """You are a clinical coding advisor for outpatient physical therapy reimbursement.
The clinician has identified a specific CPT code they believe applies to this encounter.
Your job is to evaluate THAT code against the encounter evidence and return CMS-1500-ready metadata.

Return a SINGLE JSON object (not an array) — exactly for the code specified. Do not add other codes.

Required fields — every field MUST be filled with a real value, never null or an empty string:
- modifier: always "GP" unless the service is genuinely distinct from others billed same day, then "GP-59"
- diagnosis_pointer: the letter(s) matching the relevant ICD-10 position (A = first diagnosis, B = second, AB = both)
- justification: 3-5 sentences in first-person clinician voice referencing documented objective findings,
  the specific intervention provided, the time spent, and why skilled PT judgment was required.
  Reference the maximum billable units from the documented service time using the 8-minute rule.
  Example tone: "The patient presented with [finding]. I provided [X minutes of service], warranting [N units].
  Skilled PT was required to [reason]."
- units: use documented service time and 8-minute rule (8-22 min=1, 23-37 min=2, 38-52 min=3, 53-67 min=4).
  For untimed codes, always 1. Use the MAXIMUM supportable units the documentation supports.
- supportability_score: 0.0-1.0 reflecting how well the evidence supports this code
- supporting_docs: clinical documentation items only (ROM, strength, functional tests, treatment notes,
  physician referral). Never list administrative, billing, or insurance requirements.
- compliance_warning: null if no issues; otherwise a brief warning string"""

SINGLE_CODE_EVAL_SCHEMA = {
    "code": "97110",
    "label": "Therapeutic Exercise",
    "modifier": "GP",
    "units": 2,
    "supportability_score": 0.85,
    "diagnosis_codes": ["M17.11"],
    "diagnosis_pointer": "A",
    "evidence_summary": "Patient demonstrates right knee ROM deficit and quad weakness supporting skilled exercise need.",
    "missing_elements": ["documented start/stop time for this specific service"],
    "compliance_warning": None,
    "supporting_docs": [
        {"requirement": "ROM measurement documenting deficit", "present": True, "note": "Right knee flexion 95 degrees"},
        {"requirement": "Documented service time for unit calculation", "present": False, "note": None}
    ],
    "justification": "The patient presented with right knee flexion limited to 95 degrees and quadriceps strength of 3+/5, significantly below functional norms required for stair negotiation and sit-to-stand transfers. I provided 30 minutes of therapeutic exercise targeting quadriceps strengthening, hip abductor activation, and terminal knee extension, warranting 2 units under the 8-minute rule. Skilled PT intervention was required to design a progressive loading program that protects the medial compartment while restoring functional muscle balance."
}


def evaluate_single_code(
    evidence: dict[str, Any],
    code: str,
    label: str = "",
    diagnoses: list[dict] | None = None,
) -> dict[str, Any]:
    """Evaluate a single clinician-specified CPT code against encounter evidence.
    Returns a single object with modifier, units, dx pointer, justification, and supporting docs.
    """
    client = _get_client()

    static = _CPT_PT_LOOKUP.get(code.strip(), {})
    resolved_label = label or static.get("label") or f"CPT {code}"
    timed_hint = "timed" if static.get("timed", True) else "untimed (always 1 unit)"

    user_message = f"""## Encounter Evidence
{json.dumps(evidence, indent=2)}

## Code to Evaluate
Code: {code}
Label: {resolved_label}
Timing type: {timed_hint}

## Diagnoses on File
{json.dumps(diagnoses or [], indent=2)}

Evaluate this specific CPT code against the evidence above.
Return a single JSON object matching this schema exactly (use real values, not descriptions):
{json.dumps(SINGLE_CODE_EVAL_SCHEMA, indent=2)}
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SINGLE_CODE_EVAL_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    result = _parse_json(response.content[0].text)
    if isinstance(result, list):
        result = result[0]
    return result


RANK_OUTPUT_SCHEMA = [
    {
        "code": "CPT string e.g. 97110",
        "label": "string e.g. Therapeutic Exercise",
        "modifier": "string e.g. GP or GP-59",
        "units": "integer",
        "rank": "integer starting at 1",
        "supportability_score": "number 0-1",
        "diagnosis_codes": ["ICD-10 string e.g. M17.11"],
        "diagnosis_pointer": "string e.g. A or AB",
        "evidence_summary": "1-2 sentence summary of supporting evidence",
        "missing_elements": ["string — what is absent from the note"],
        "compliance_warning": "string or null",
        "supporting_docs": [
            {
                "requirement": "string — what is needed for this code",
                "present": "boolean",
                "note": "string or null — brief quote or reference from chart"
            }
        ],
        "justification": "3-5 sentence justification in clinician's first-person tone"
    }
]

COMBINED_SYSTEM_PROMPT = """You are a clinical coding advisor and documentation specialist for outpatient physical therapy reimbursement.
Given structured encounter evidence, do two things in one response:
1. Return ALL applicable CPT codes with CMS-1500-ready metadata. A typical PT session has 3-8 codes — include every distinct service documented.
2. For each code, write a 3-5 sentence justification paragraph in first-person clinician's tone.

Return valid JSON only — a single array of objects.

Coding rules:
- Return ALL CPT codes supported by the note, not just the top one. Each distinct service gets its own entry.
- Use GP modifier by default; add 59 only when a service is genuinely distinct from others billed same day.
- For timed codes apply the 8-minute rule: 8-22 min = 1 unit, 23-37 min = 2, 38-52 min = 3, 53-67 min = 4.
- For untimed codes always set units = 1.
- diagnosis_pointer maps to the letter of the ICD-10 position (A = first, B = second).
- supporting_docs must ONLY list clinical documentation items: objective findings, evaluation records,
  treatment notes, physician referral/plan of care, functional tests, ROM/strength measurements, outcome
  measures. Do NOT include administrative, billing, insurance, or prior-authorization requirements.
- Never recommend units beyond what is documented. Never hide compliance issues.

Justification rules:
- Write in first person as the treating clinician: "The patient presented with..."
- Directly reference objective findings, ROM measurements, strength scores, functional tests.
- State why the service requires skilled PT judgment.
- Do not invent facts not in the evidence. Do not exaggerate severity."""


def rank_codes_with_justifications(
    evidence: dict[str, Any],
    candidate_codes: list[dict[str, str]] | None = None,
    clinic_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Single API call returning ranked codes WITH per-code justification text.
    Replaces the separate rank_codes + generate_per_code_justifications round-trips.
    """
    client = _get_client()

    user_message = f"""## Extracted Encounter Evidence
{json.dumps(evidence, indent=2)}

## Candidate Codes (optional hints)
{json.dumps(candidate_codes or [], indent=2)}

## Clinic Configuration
{json.dumps(clinic_config or {}, indent=2)}

Return a JSON array. Each element must match this schema exactly:
{json.dumps(RANK_OUTPUT_SCHEMA, indent=2)}
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=COMBINED_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    return _parse_json(response.content[0].text)


def rank_codes(
    evidence: dict[str, Any],
    candidate_codes: list[dict[str, str]] | None = None,
    clinic_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return CMS-1500-ready ranked CPT options with modifiers, units, dx pointers, and supporting docs."""
    client = _get_client()

    user_message = f"""## Extracted Encounter Evidence
{json.dumps(evidence, indent=2)}

## Candidate Codes (optional hints)
{json.dumps(candidate_codes or [], indent=2)}

## Clinic Configuration
{json.dumps(clinic_config or {}, indent=2)}

Return a JSON array of ranked code objects matching this schema exactly:
{json.dumps(RANK_OUTPUT_SCHEMA, indent=2)}
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    return _parse_json(response.content[0].text)


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
