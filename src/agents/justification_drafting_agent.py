"""Justification Drafting Agent — generates structured bullets and draft prose."""

import sys
import pathlib
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from scripts.generate_justification import generate_justification


class JustificationDraftingAgent:
    """Produces clinician-reviewable structured bullets and a reimbursement draft."""

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

        # Select best supportable code
        selected_code = {}
        if ranked_codes:
            top = ranked_codes[0]
            selected_code = {"code": top.get("code"), "label": top.get("label")}

        clinic_formatting = encounter_package.get("_clinic_formatting", {})
        justification = generate_justification(evidence, selected_code, gap_analysis, clinic_formatting)

        # Fork C: insufficient evidence — draft blocked by the script itself
        if justification.get("evidence_quality") == "insufficient":
            encounter_package["_blocked"] = {
                "reason": "insufficient_evidence_for_draft",
                "message": "Evidence quality is insufficient to generate reimbursement prose.",
                "warnings": justification.get("warnings", []),
            }

        encounter_package["_justification"] = justification
        return encounter_package
