"""Justification Drafting Agent — generates structured bullets and draft prose."""

import sys
import pathlib
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from scripts.rag_justification import generate_all_justifications

_QUALITY_RANK = {"insufficient": 0, "partial": 1, "strong": 2}


class JustificationDraftingAgent:
    """Produces per-code structured bullets and draft prose for every ranked CPT code."""

    def run(self, encounter_package: dict[str, Any]) -> dict[str, Any]:
        encounter_id = encounter_package.get("encounter_id", "unknown")

        if encounter_package.get("_blocked"):
            raise RuntimeError(
                f"[{encounter_id}] Pipeline is blocked — justification draft cannot be generated. "
                f"Reason: {encounter_package['_blocked'].get('message')}"
            )

        evidence = encounter_package.get("_evidence")
        ranked_codes = encounter_package.get("_ranked_codes", [])
        gap_analysis = encounter_package.get("_gap_analysis")

        if not evidence:
            raise ValueError(f"[{encounter_id}] No evidence found. Run EncounterEvidenceAgent first.")

        clinic_formatting = encounter_package.get("_clinic_formatting", {})
        patient_id = encounter_package.get("patient_id", "unknown-patient")
        note_text = (
            encounter_package.get("source_documents", {})
            .get("uploaded_treatment_note", {})
            .get("parsed_text", "")
        )
        per_code = generate_all_justifications(
            evidence, ranked_codes, gap_analysis, clinic_formatting,
            patient_id=patient_id, encounter_id=encounter_id, note_text=note_text,
        )

        qualities = [e.get("evidence_quality", "insufficient") for e in per_code]
        overall = min(qualities, key=lambda q: _QUALITY_RANK.get(q, 0), default="insufficient")

        # Fork C: block only when every code lacks sufficient evidence
        if overall == "insufficient":
            all_warnings = [w for e in per_code for w in e.get("warnings", [])]
            encounter_package["_blocked"] = {
                "reason": "insufficient_evidence_for_draft",
                "message": "Evidence quality is insufficient to generate reimbursement prose.",
                "warnings": all_warnings,
            }

        encounter_package["_justification"] = {"per_code": per_code, "overall_evidence_quality": overall}
        return encounter_package
