"""Code Supportability Agent — ranks CPT/ICD options by documentation support."""

import sys
import pathlib
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from scripts.rank_codes import rank_codes

SUPPORTABILITY_THRESHOLD = 0.5


class CodeSupportabilityAgent:
    """Maps extracted evidence to ranked, compliance-annotated code options."""

    def run(self, encounter_package: dict[str, Any]) -> dict[str, Any]:
        encounter_id = encounter_package.get("encounter_id", "unknown")
        evidence = encounter_package.get("_evidence")
        if not evidence:
            raise ValueError(f"[{encounter_id}] No evidence found. Run EncounterEvidenceAgent first.")

        # Build candidate list from the encounter package suggested_treatments
        candidates: list[dict[str, str]] = []
        for treatment in encounter_package.get("suggested_treatments", []):
            for cpt in treatment.get("potential_cpt_codes", []):
                candidates.append({"code": cpt["code"], "label": cpt.get("label", "")})

        clinic_config = encounter_package.get("_clinic_config", {})
        ranked = rank_codes(evidence, candidates or None, clinic_config)

        # Fork D: no supportable code found
        top_score = ranked[0].get("supportability_score", 0) if ranked else 0
        if top_score < SUPPORTABILITY_THRESHOLD:
            encounter_package["_escalation"] = {
                "reason": "no_supportable_code",
                "message": (
                    f"Top code supportability score {top_score:.2f} is below threshold "
                    f"{SUPPORTABILITY_THRESHOLD}. Escalating to clinician review."
                ),
                "ranked_codes": ranked,
            }

        encounter_package["_ranked_codes"] = ranked
        return encounter_package
