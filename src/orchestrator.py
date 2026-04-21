"""Orchestrator — sequences all agents and enforces pipeline fork logic."""

import sys
import pathlib
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from scripts.validate_payload import validate_payload
from src.agents.encounter_evidence_agent import EncounterEvidenceAgent
from src.agents.code_supportability_agent import CodeSupportabilityAgent
from src.agents.documentation_gap_agent import DocumentationGapAgent
from src.agents.justification_drafting_agent import JustificationDraftingAgent
from src import storage


class PipelineResult:
    def __init__(self, encounter_package: dict[str, Any], blocked: bool, warnings: list[str]):
        self.encounter_package = encounter_package
        self.blocked = blocked
        self.warnings = warnings
        self.encounter_id: str = encounter_package.get("encounter_id", "unknown")

    @property
    def evidence(self) -> dict | None:
        return self.encounter_package.get("_evidence")

    @property
    def ranked_codes(self) -> list | None:
        return self.encounter_package.get("_ranked_codes")

    @property
    def gap_analysis(self) -> dict | None:
        return self.encounter_package.get("_gap_analysis")

    @property
    def justification(self) -> dict | None:
        return self.encounter_package.get("_justification")


def run_pipeline(encounter_package: dict[str, Any]) -> PipelineResult:
    """
    Execute the full post-visit pipeline.

    Steps (per orchestrator-playbook.md):
      1. Validate input payload.
      2. Encounter Evidence Agent.
      3. Code Supportability Agent.
      4. Documentation Gap Agent.
      5. Justification Drafting Agent (if not blocked).
      6. Persist outputs.
    """
    encounter_id = encounter_package.get("encounter_id", "unknown")
    warnings: list[str] = []

    # Step 1 — validate
    errors = validate_payload(encounter_package)
    if errors:
        storage.append_log(encounter_id, {"step": "validate", "status": "failed", "errors": errors})
        raise ValueError(
            f"[{encounter_id}] Invalid encounter package:\n" + "\n".join(f"  - {e}" for e in errors)
        )
    storage.append_log(encounter_id, {"step": "validate", "status": "ok"})

    # Step 2 — evidence extraction
    encounter_package = EncounterEvidenceAgent().run(encounter_package)
    if warn := encounter_package.get("_evidence", {}).get("_low_confidence_warning"):
        warnings.append(warn)
    storage.save_json(encounter_id, "evidence.json", encounter_package["_evidence"])
    storage.append_log(encounter_id, {"step": "encounter_evidence_agent", "status": "ok"})

    # Step 3 — code supportability
    encounter_package = CodeSupportabilityAgent().run(encounter_package)
    if escalation := encounter_package.get("_escalation"):
        warnings.append(escalation["message"])
    storage.save_json(encounter_id, "ranked_codes.json", encounter_package.get("_ranked_codes", []))
    storage.append_log(encounter_id, {"step": "code_supportability_agent", "status": "ok"})

    # Step 4 — documentation gap detection
    encounter_package = DocumentationGapAgent().run(encounter_package)
    gap_rec = encounter_package.get("_gap_analysis", {}).get("recommendation", "continue")
    storage.save_json(encounter_id, "gaps.json", encounter_package.get("_gap_analysis", {}))
    storage.append_log(encounter_id, {"step": "documentation_gap_agent", "status": "ok", "recommendation": gap_rec})

    if encounter_package.get("_blocked"):
        storage.append_log(encounter_id, {"step": "pipeline", "status": "blocked", "reason": encounter_package["_blocked"]})
        storage.save_json(encounter_id, "encounter_package.json", _serializable(encounter_package))
        return PipelineResult(encounter_package, blocked=True, warnings=warnings)

    # Step 5 — justification drafting
    if gap_rec == "warn":
        warnings.append(encounter_package.get("_gap_analysis", {}).get("summary", "Documentation gaps present."))

    encounter_package = JustificationDraftingAgent().run(encounter_package)
    storage.save_json(encounter_id, "justification.json", encounter_package.get("_justification", {}))
    storage.append_log(encounter_id, {"step": "justification_drafting_agent", "status": "ok"})

    # Step 6 — persist full package
    storage.save_json(encounter_id, "encounter_package.json", _serializable(encounter_package))
    storage.append_log(encounter_id, {"step": "pipeline", "status": "complete"})

    return PipelineResult(encounter_package, blocked=bool(encounter_package.get("_blocked")), warnings=warnings)


def _serializable(package: dict[str, Any]) -> dict[str, Any]:
    """Strip private processing keys that start with underscore before persisting."""
    return {k: v for k, v in package.items() if not k.startswith("_")}
