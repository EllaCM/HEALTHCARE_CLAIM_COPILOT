"""RAG prompts, context builder, and per-code pipeline for justification generation."""

import json
import os
from typing import Any

import anthropic

from scripts.cpt_definitions_adapter import CPTDefinitionsAdapter
from scripts.ingest_patient_docs import ingest_encounter, retrieve_chunks

_cpt_adapter = CPTDefinitionsAdapter()

RAG_SYSTEM_PROMPT = """You are a physical therapy clinical documentation specialist.
Generate a reimbursement justification for the CPT code provided.
Base your reasoning on the RETRIEVED CHART SECTIONS — every factual claim must trace back to a retrieved chunk.
Return valid JSON only.

Rules:
- Write in first-person clinical tone as the treating therapist.
- Each structured_bullet must reference its source via the section name in source_evidence.
- Do not add clinical facts absent from the retrieved chunks or encounter evidence summary.
- If retrieved context lacks sufficient support, set draft_paragraph to null and populate warnings.
- evidence_quality: "strong" = direct retrieved evidence for all bullets; "partial" = some inferred; "insufficient" = no direct support."""

RAG_OUTPUT_SCHEMA = {
    "code": "CPT code string",
    "label": "service label string",
    "structured_bullets": [
        {
            "section": "patient_condition | functional_limitation | objective_findings | prior_treatment_history | treatment_provided | medical_necessity | missing_documentation | other",
            "label": "string",
            "content": "string",
            "source_evidence": [{"source_type": "chart_section", "document_id": "encounter_note", "text_span": "string"}],
            "confidence_score": "number 0-1",
        }
    ],
    "draft_paragraph": "string or null",
    "warnings": ["string"],
    "evidence_quality": "strong | partial | insufficient",
    "retrieved_sources": [
        {
            "section": "string — note section label",
            "chunk_index": "integer",
            "text_span": "string — first 120 chars of retrieved chunk",
        }
    ],
}


def _eight_minute_rule(minutes: int) -> int:
    """Return max billable units for a timed code given documented service minutes."""
    if minutes < 8:
        return 0
    return (minutes - 8) // 15 + 1


def _build_unit_defense_prompt(units: int, code: str, is_timed: bool) -> str:
    """Return the billing-unit defense block to inject into the user message.

    Returns empty string for untimed codes — they are always 1 unit by CMS definition.
    """
    if not is_timed:
        return ""
    return f"""
## Submitted Billing Units
The clinician has submitted {units} unit(s) for CPT {code} (a timed code).

Billing Unit Instructions:
- Identify the documented service time for CPT {code} from the retrieved chart sections.
- Apply the 8-minute rule: 8-22 min = 1 unit, 23-37 min = 2, 38-52 min = 3, 53-67 min = 4.
- Compute the maximum supportable units from that documented time.
- If submitted ({units}) < max supportable: add a 'medical_necessity' structured_bullet defending
  why {units} unit(s) is appropriate (e.g., conservative billing, partial time attribution to this
  code). Reference this defense explicitly in draft_paragraph.
- If submitted ({units}) = max supportable: standard justification, no special defense needed.
- If submitted ({units}) > max supportable: add a compliance warning stating submitted units exceed
  what the documented service time supports and must be reviewed before submitting.
- If service time for this code cannot be found in the retrieved sections: add a warning noting
  that units could not be independently verified from the chart.
"""


def _build_rag_context(chunks: list[dict[str, Any]], cpt_definition: dict[str, Any]) -> str:
    """Format retrieved chunks and CPT definition into a prompt context block."""
    timed_label = "timed" if cpt_definition.get("timed", True) else "untimed (always 1 unit)"
    lines = [
        "## CPT Code Definition",
        f"Description: {cpt_definition.get('description', 'N/A')}",
        f"Typical Indication: {cpt_definition.get('typical_indication', 'N/A')}",
        f"Timing: {timed_label}",
        "",
        "## Retrieved Chart Sections (ranked by relevance)",
    ]
    for i, chunk in enumerate(chunks, 1):
        lines.append(f"### Chunk {i} — Section: {chunk['section']}")
        lines.append(chunk["text"])
        lines.append("")
    return "\n".join(lines)


def _run_rag_for_code(
    evidence: dict[str, Any],
    code: str,
    label: str,
    gap_analysis: dict[str, Any] | None,
    patient_id: str,
    encounter_id: str,
    note_text: str,
    client: anthropic.Anthropic,
    units: int | None = None,
) -> dict[str, Any]:
    """Full per-code RAG pipeline: ingest → retrieve → prompt → parse."""
    cpt_def = _cpt_adapter.get_definition(code)
    resolved_label = label or cpt_def.get("label") or f"CPT {code}"

    # Ingest note (idempotent)
    if note_text and patient_id != "unknown-patient":
        ingest_encounter(patient_id, encounter_id, note_text)

    # Retrieve relevant chunks
    query = f"{resolved_label}: {cpt_def.get('description', '')} {cpt_def.get('typical_indication', '')}"
    chunks = retrieve_chunks(patient_id, encounter_id, query, n_results=5)

    rag_context = _build_rag_context(chunks, cpt_def)
    is_timed = cpt_def.get("timed", True)
    unit_defense = _build_unit_defense_prompt(units, code, is_timed) if units is not None else ""

    user_message = f"""## Code to Justify
Code: {code}
Label: {resolved_label}

{rag_context}

## Full Structured Evidence (extracted metadata)
{json.dumps(evidence, indent=2)}

## Documentation Gap Notes
{json.dumps(gap_analysis or {}, indent=2)}
{unit_defense}
Generate structured bullets and a draft paragraph. Return JSON matching this schema exactly:
{json.dumps(RAG_OUTPUT_SCHEMA, indent=2)}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=RAG_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text
    result = _parse_json_rag(raw)
    if isinstance(result, list):
        result = result[0]

    # Ensure required fields exist
    result.setdefault("code", code)
    result.setdefault("label", resolved_label)
    result.setdefault("retrieved_sources", [
        {"section": c["section"], "chunk_index": c["chunk_index"], "text_span": c["text"][:120]}
        for c in chunks
    ])
    return result


def _parse_json_rag(raw: str) -> Any:
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
