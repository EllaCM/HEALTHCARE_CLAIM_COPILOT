"""Integration test for the full pipeline — requires ANTHROPIC_API_KEY."""

import os
import pathlib
import sys
import uuid
from datetime import date, datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping live integration test",
)


def _build_package(note_text: str) -> dict:
    encounter_id = f"test-{uuid.uuid4().hex[:8]}"
    doc_id = f"doc-{encounter_id}"
    return {
        "encounter_id": encounter_id,
        "date_of_service": date.today().isoformat(),
        "patient_id": "test-patient",
        "clinician_id": "test-clinician",
        "source_documents": {
            "uploaded_treatment_note": {
                "document_id": doc_id,
                "file_name": "sample_note.txt",
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "parsed_text": note_text,
            },
            "backend_document_ids": [],
        },
        "suggested_treatments": [],
        "chat_session": {
            "session_id": f"session-{encounter_id}",
            "interaction_mode": "justification_help",
            "messages": [],
            "activity_log": [],
        },
        "final_output_document": {
            "document_id": f"output-{encounter_id}",
            "sections": [],
            "all_required_fields_complete": False,
        },
        "submission_state": {"status": "draft"},
    }


def test_full_pipeline_with_sample_note():
    from src.orchestrator import run_pipeline

    note_path = FIXTURES / "sample_encounter_note.txt"
    assert note_path.exists(), f"Fixture not found: {note_path}"
    note_text = note_path.read_text()

    package = _build_package(note_text)
    result = run_pipeline(package)

    assert result.evidence is not None, "Evidence should be populated"
    assert result.ranked_codes is not None, "Ranked codes should be populated"
    assert result.gap_analysis is not None, "Gap analysis should be populated"

    if not result.blocked:
        assert result.justification is not None, "Justification should be populated when not blocked"
        assert "structured_bullets" in result.justification
        assert "evidence_quality" in result.justification
