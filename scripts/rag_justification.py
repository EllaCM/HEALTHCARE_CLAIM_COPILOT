"""RAG-powered CPT justification — replaces generate_justification.py.

Public interface is drop-in compatible. All functions accept optional
patient_id, encounter_id, note_text kwargs to enable retrieval-augmented generation.
"""

import os
import sys
from typing import Any

import anthropic

from scripts.rag_justification_prompts import _run_rag_for_code, _parse_json_rag
from scripts.billing_utils import _eight_minute_rule

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _resolve_rag_context(
    evidence: dict[str, Any],
    patient_id: str | None,
    encounter_id: str | None,
    note_text: str | None,
) -> tuple[str, str, str]:
    """Return (patient_id, encounter_id, note_text) with fallbacks from evidence dict."""
    pid = patient_id or evidence.get("_patient_id", "unknown-patient")
    eid = encounter_id or evidence.get("_encounter_id", "unknown-encounter")
    note = note_text or evidence.get("_note_text", "")
    return pid, eid, note


def generate_justification(
    evidence: dict[str, Any],
    selected_code: dict[str, Any],
    gap_analysis: dict[str, Any] | None = None,
    clinic_formatting: dict[str, Any] | None = None,
    *,
    patient_id: str | None = None,
    encounter_id: str | None = None,
    note_text: str | None = None,
) -> dict[str, Any]:
    """RAG-powered single-code justification. Drop-in replacement."""
    pid, eid, note = _resolve_rag_context(evidence, patient_id, encounter_id, note_text)
    code = selected_code.get("code", "")
    label = selected_code.get("label", "")
    units = selected_code.get("units")
    return _run_rag_for_code(evidence, code, label, gap_analysis, pid, eid, note, _get_client(), units=units)


def generate_all_justifications(
    evidence: dict[str, Any],
    ranked_codes: list[dict[str, Any]],
    gap_analysis: dict[str, Any] | None = None,
    clinic_formatting: dict[str, Any] | None = None,
    *,
    patient_id: str | None = None,
    encounter_id: str | None = None,
    note_text: str | None = None,
) -> list[dict[str, Any]]:
    """RAG-powered justification for every ranked CPT code. Drop-in replacement."""
    pid, eid, note = _resolve_rag_context(evidence, patient_id, encounter_id, note_text)
    client = _get_client()
    results = []
    for code_item in ranked_codes:
        code = code_item.get("code", "")
        label = code_item.get("label", "")
        units = code_item.get("units")
        result = _run_rag_for_code(evidence, code, label, gap_analysis, pid, eid, note, client, units=units)
        results.append(result)
    return results


def generate_per_code_justifications(
    evidence: dict[str, Any],
    cpt_codes: list[dict[str, Any]],
    gap_analysis: dict[str, Any] | None = None,
    *,
    patient_id: str | None = None,
    encounter_id: str | None = None,
    note_text: str | None = None,
) -> dict[str, str]:
    """Return {code: draft_paragraph}. Drop-in replacement for generate_per_code_justifications."""
    pid, eid, note = _resolve_rag_context(evidence, patient_id, encounter_id, note_text)
    client = _get_client()
    out: dict[str, str] = {}
    for code_item in cpt_codes:
        code = code_item.get("code", "")
        label = code_item.get("label", "")
        result = _run_rag_for_code(evidence, code, label, gap_analysis, pid, eid, note, client)
        out[code] = result.get("draft_paragraph") or ""
    return out


def evaluate_single_code(
    evidence: dict[str, Any],
    code: str,
    label: str = "",
    diagnoses: list[dict] | None = None,
    *,
    patient_id: str | None = None,
    encounter_id: str | None = None,
    note_text: str | None = None,
    units: int | None = None,
    minutes: int | None = None,
) -> dict[str, Any]:
    """RAG-powered single-code evaluation. Drop-in replacement for rank_codes.evaluate_single_code."""
    pid, eid, note = _resolve_rag_context(evidence, patient_id, encounter_id, note_text)

    # Overbilling guard: block LLM call and return warning immediately
    if units is not None and minutes is not None:
        from scripts.cpt_definitions_adapter import CPTDefinitionsAdapter
        is_timed = CPTDefinitionsAdapter().get_definition(code).get("timed", True)
        if is_timed:
            max_units = _eight_minute_rule(minutes)
            if units > max_units:
                msg = (
                    f"Max billable units for {minutes} min is {max_units} "
                    f"(8-min rule: 8-22 min=1, 23-37=2, 38-52=3, 53-67=4). "
                    f"Reduce to {max_units} or fewer before generating justification."
                )
                return {
                    "code": code,
                    "label": label,
                    "draft_paragraph": None,
                    "justification": "",
                    "compliance_warning": msg,
                    "warnings": [msg],
                    "supportability_score": None,
                    "evidence_quality": "insufficient",
                    "structured_bullets": [],
                    "retrieved_sources": [],
                    "overbilling": True,
                    "max_units": max_units,
                }

    return _run_rag_for_code(evidence, code, label, None, pid, eid, note, _get_client(), units=units, minutes=minutes)


def normalize_evaluation_result(
    matched: dict[str, Any],
    *,
    current_code: str,
    existing_item: dict[str, Any],
    existing_diagnoses: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Coerce a raw `evaluate_single_code` result into a UI-safe CPT item.

    Returns (normalized_item_fields, new_icds_to_append). Pure function:
    does not mutate inputs. Caller is responsible for merging fields back
    into its item dict and appending the returned diagnoses.
    """
    normalized = {
        "code": str(matched.get("code") or current_code).strip(),
        "label": str(matched.get("label") or existing_item.get("label") or f"CPT {current_code}").strip(),
        "modifier": str(matched.get("modifier") or "GP").strip(),
        "dx_pointer": str(
            matched.get("diagnosis_pointer") or existing_item.get("dx_pointer") or "A"
        ).strip(),
        "justification": str(
            matched.get("justification") or matched.get("draft_paragraph") or ""
        ).strip(),
        "supportability_score": float(matched.get("supportability_score") or 0),
        "compliance_warning": matched.get("compliance_warning") or (
            matched.get("warnings", [None])[0] if matched.get("warnings") else None
        ),
        "supporting_docs": matched.get("supporting_docs") or [],
        "missing_elements": matched.get("missing_elements") or [],
        "evidence_summary": str(matched.get("evidence_summary") or "").strip(),
        "auto_fill_notes": [],
    }

    existing_codes = {d["code"] for d in existing_diagnoses}
    new_icds: list[dict[str, Any]] = []
    next_idx = len(existing_diagnoses)
    for icd in matched.get("diagnosis_codes") or []:
        if icd not in existing_codes:
            new_icds.append({"code": icd, "label": "", "pointer": chr(65 + next_idx)})
            existing_codes.add(icd)
            next_idx += 1

    return normalized, new_icds


if __name__ == "__main__":
    import json

    evidence_path = sys.argv[1]
    code_path = sys.argv[2]
    with open(evidence_path) as f:
        ev = json.load(f)
    with open(code_path) as f:
        selected = json.load(f)
    print(json.dumps(generate_justification(ev, selected), indent=2))
