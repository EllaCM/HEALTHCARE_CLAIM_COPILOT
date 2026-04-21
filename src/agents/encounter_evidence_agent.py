"""Encounter Evidence Agent — extracts structured evidence from raw visit inputs."""

import sys
import pathlib
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from scripts.extract_evidence import extract_evidence

CONFIDENCE_THRESHOLD = 0.4


class EncounterEvidenceAgent:
    """Transforms fragmented visit inputs into a structured evidence section."""

    def run(self, encounter_package: dict[str, Any]) -> dict[str, Any]:
        encounter_id = encounter_package.get("encounter_id", "unknown")
        source_docs = encounter_package.get("source_documents", {})

        note_text = source_docs.get("uploaded_treatment_note", {}).get("parsed_text", "")
        if not note_text:
            raise ValueError(f"[{encounter_id}] No parsed note text found in source_documents.")

        # Collect any supplementary backend documents (text stored inline for MVP)
        supporting = {
            doc_id: encounter_package.get("_backend_doc_texts", {}).get(doc_id, "")
            for doc_id in source_docs.get("backend_document_ids", [])
            if encounter_package.get("_backend_doc_texts", {}).get(doc_id)
        }

        evidence = extract_evidence(note_text, supporting or None, encounter_id=encounter_id)

        # Fork B: flag low overall confidence
        overall_confidence = evidence.get("confidence_score", 1.0)
        if isinstance(overall_confidence, (int, float)) and overall_confidence < CONFIDENCE_THRESHOLD:
            evidence["_low_confidence_warning"] = (
                f"Overall evidence confidence {overall_confidence:.2f} is below threshold "
                f"{CONFIDENCE_THRESHOLD}. Downstream agents should treat outputs as weak."
            )

        encounter_package["_evidence"] = evidence
        return encounter_package
