"""Documentation Gap Agent — identifies weak or missing documentation before drafting."""

import sys
import pathlib
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from scripts.detect_gaps import detect_gaps


class DocumentationGapAgent:
    """Flags missing evidence and returns a block/warn/continue recommendation."""

    def run(self, encounter_package: dict[str, Any]) -> dict[str, Any]:
        encounter_id = encounter_package.get("encounter_id", "unknown")
        evidence = encounter_package.get("_evidence")
        ranked_codes = encounter_package.get("_ranked_codes")

        if not evidence:
            raise ValueError(f"[{encounter_id}] No evidence found. Run EncounterEvidenceAgent first.")
        if ranked_codes is None:
            raise ValueError(f"[{encounter_id}] No ranked codes found. Run CodeSupportabilityAgent first.")

        # Use the top-ranked code as the reference if none explicitly selected
        selected_code = encounter_package.get("_selected_code")
        if not selected_code and ranked_codes:
            selected_code = ranked_codes[0].get("code")

        gap_analysis = detect_gaps(evidence, ranked_codes, selected_code)

        encounter_package["_gap_analysis"] = gap_analysis

        # Fork B: major gaps block justification drafting
        if gap_analysis.get("recommendation") == "block":
            encounter_package["_blocked"] = {
                "reason": "major_documentation_gaps",
                "message": gap_analysis.get("summary", "Critical documentation gaps detected."),
                "gaps": gap_analysis.get("gaps", []),
            }

        return encounter_package
