"""Unit tests for validate_payload.py — no API key required."""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from scripts.validate_payload import validate_payload

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _minimal_valid_package(encounter_id: str = "enc-test-001") -> dict:
    return {
        "encounter_id": encounter_id,
        "date_of_service": "2026-04-20",
        "patient_id": "patient-001",
        "clinician_id": "clinician-001",
        "source_documents": {
            "uploaded_treatment_note": {
                "document_id": "doc-001",
                "file_name": "note.txt",
                "uploaded_at": "2026-04-20T10:00:00Z",
                "parsed_text": "Sample note text.",
            },
            "backend_document_ids": [],
        },
        "suggested_treatments": [],
        "chat_session": {
            "session_id": "session-001",
            "interaction_mode": "justification_help",
            "messages": [],
            "activity_log": [],
        },
        "final_output_document": {
            "document_id": "output-001",
            "sections": [],
            "all_required_fields_complete": False,
        },
        "submission_state": {"status": "draft"},
    }


def test_valid_minimal_package():
    errors = validate_payload(_minimal_valid_package())
    assert errors == [], f"Expected no errors, got: {errors}"


def test_missing_required_field():
    pkg = _minimal_valid_package()
    del pkg["encounter_id"]
    errors = validate_payload(pkg)
    assert any("encounter_id" in e for e in errors)


def test_invalid_submission_status():
    pkg = _minimal_valid_package()
    pkg["submission_state"]["status"] = "unknown_status"
    errors = validate_payload(pkg)
    assert errors, "Expected validation errors for invalid submission status"


def test_invalid_date_format():
    pkg = _minimal_valid_package()
    pkg["date_of_service"] = "April 20 2026"
    errors = validate_payload(pkg)
    assert errors, "Expected validation errors for invalid date format"


def test_extra_top_level_property_rejected():
    pkg = _minimal_valid_package()
    pkg["unexpected_field"] = "should_fail"
    errors = validate_payload(pkg)
    assert errors, "Expected validation error for additional properties"


def test_valid_package_with_suggested_treatment():
    pkg = _minimal_valid_package()
    pkg["suggested_treatments"] = [
        {
            "treatment_id": "t-001",
            "treatment_name": "Therapeutic Exercise",
            "detection_status": "detected",
            "selection_state": "selected",
        }
    ]
    errors = validate_payload(pkg)
    assert errors == [], f"Unexpected errors: {errors}"
