"""RAG-powered CPT justification — replaces generate_justification.py.

Public interface is drop-in compatible. All functions accept optional
patient_id, encounter_id, note_text kwargs to enable retrieval-augmented generation.
"""

import os
import sys
from typing import Any

import anthropic

from scripts.rag_justification_prompts import _run_rag_for_code, _parse_json_rag

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
) -> dict[str, Any]:
    """RAG-powered single-code evaluation. Drop-in replacement for rank_codes.evaluate_single_code."""
    pid, eid, note = _resolve_rag_context(evidence, patient_id, encounter_id, note_text)
    return _run_rag_for_code(evidence, code, label, None, pid, eid, note, _get_client(), units=units)


if __name__ == "__main__":
    import json

    evidence_path = sys.argv[1]
    code_path = sys.argv[2]
    with open(evidence_path) as f:
        ev = json.load(f)
    with open(code_path) as f:
        selected = json.load(f)
    print(json.dumps(generate_justification(ev, selected), indent=2))
