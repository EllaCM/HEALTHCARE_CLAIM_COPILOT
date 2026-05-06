"""RAG prompts, context builder, and per-code pipeline for justification generation."""

import json
import os
from typing import Any

import anthropic

from scripts.billing_utils import _eight_minute_rule
from scripts.cpt_definitions_adapter import CPTDefinitionsAdapter

_cpt_adapter = CPTDefinitionsAdapter()

RAG_SYSTEM_PROMPT = """You are a physical therapy clinical documentation specialist.
Generate a reimbursement justification for the CPT code provided.
Base your reasoning on the RETRIEVED CHART SECTIONS — every factual claim must trace back to a retrieved chunk.
Return valid JSON only.

Rules:
- Write in first-person clinical tone as the treating therapist.
- Each structured_bullet must reference its source via the section name in source_evidence.
- Do not add clinical facts absent from the retrieved chunks or encounter evidence summary.
- If retrieved chart sections are absent, fall back to the Full Structured Evidence section and
  any note text provided to generate a best-effort justification. Only set draft_paragraph to null
  when there is truly no clinical information at all (empty evidence AND empty retrieved sections).
  Always generate a draft paragraph when any clinical context is available.
- evidence_quality: "strong" = direct retrieved evidence for all bullets; "partial" = some inferred; "insufficient" = no direct support.

Time segmentation guidance:
- Outpatient PT notes routinely describe total session treatments without segmenting time per CPT code.
  The ABSENCE of per-code time documentation is normal and expected — never penalize, warn, or lower
  supportability_score for this reason alone.
- When per-code time is not explicit, interpret each treatment activity described in the note and
  identify which activities are reasonably attributable to the CPT code being justified. Acknowledge
  that the clinician has allocated the submitted units from the documented session activities.
- Multiple described treatment items (e.g., quad sets, SLR, bike, resistance band exercises) can
  be grouped and billed together under a single CPT code such as 97110 (therapeutic exercise).
  A justification may reference any or all of these activities as contributing to the submitted units."""

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


def _build_unit_defense_prompt(units: int, code: str, is_timed: bool, minutes: int | None = None) -> str:
    """Return the billing-unit defense block to inject into the user message.

    Returns empty string for untimed codes — they are always 1 unit by CMS definition.
    """
    if not is_timed:
        return ""
    minutes_str = f"{minutes} minutes" if minutes is not None else "the clinician-entered treatment time"
    return f"""
## Submitted Billing Units
The clinician has submitted {units} unit(s) for CPT {code} (a timed code), representing {minutes_str} of treatment time allocated to this service.

Billing Unit Instructions:
- The clinician has allocated {minutes_str} to CPT {code}. Use this as the authoritative time for this service.
- Apply the 8-minute rule: 8-22 min = 1 unit, 23-37 min = 2, 38-52 min = 3, 53-67 min = 4.
- Per-code time is rarely documented separately in outpatient PT notes — do NOT warn or lower the score
  because the note lacks an explicit "{minutes_str} for {code}" statement.
- If submitted ({units}) ≤ max supportable for {minutes_str}: provide a standard, confident clinical
  justification for {units} unit(s). Do NOT mention billing quantities, time-based comparisons, or
  "conservative billing". Write as if {units} unit(s) over {minutes_str} is the natural billing.
- Identify treatment activities in the note attributable to CPT {code} and cite them as the basis
  for the {minutes_str} / {units} unit(s) allocation.
- In the final draft_paragraph, you MUST include the phrase "{units} unit(s) based on {minutes_str}"
  and reference at least one specific treatment activity from the note. Do not omit either.
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
    minutes: int | None = None,
) -> dict[str, Any]:
    """Full per-code RAG pipeline: ingest → retrieve → prompt → parse."""
    cpt_def = _cpt_adapter.get_definition(code)
    resolved_label = label or cpt_def.get("label") or f"CPT {code}"

    from scripts.ingest_patient_docs import ingest_encounter, retrieve_chunks, _parse_sections  # lazy

    # Ingest note into vector index (idempotent; skip if no real patient ID or note)
    _rag_error: str | None = None
    if note_text and patient_id != "unknown-patient":
        try:
            ingest_encounter(patient_id, encounter_id, note_text)
        except Exception as e:
            _rag_error = str(e)

    # Retrieve semantically relevant chunks
    chunks: list[dict] = []
    if not _rag_error:
        query = f"{resolved_label}: {cpt_def.get('description', '')} {cpt_def.get('typical_indication', '')}"
        try:
            chunks = retrieve_chunks(patient_id, encounter_id, query, n_results=5)
        except Exception:
            pass

    # Fallback: parse note_text into section chunks directly (no embeddings required)
    if not chunks and note_text:
        chunks = [
            {"section": s["section"], "text": s["text"], "chunk_index": i, "distance": None}
            for i, s in enumerate(_parse_sections(note_text))
        ]

    rag_context = _build_rag_context(chunks, cpt_def)
    is_timed = cpt_def.get("timed", True)

    if units is not None and is_timed:
        unit_defense = _build_unit_defense_prompt(units, code, is_timed, minutes=minutes)
    elif minutes is not None and is_timed:
        # Minutes entered but no explicit units submitted — still inject so output varies with minutes
        unit_defense = f"\n## Clinician-Entered Treatment Time\nThe clinician entered {minutes} minutes of treatment time for CPT {code}. Reference this time allocation in the justification draft.\n"
    else:
        unit_defense = ""

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
