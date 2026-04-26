"""Tests for manual CPT code entry with auto-fill metadata.

These tests cover the flow where a clinician adds a CPT code manually
(only filling in the code field) and the system auto-fills label/modifier/units.

Unit tests: no API key required.
Integration tests: require ANTHROPIC_API_KEY, skipped otherwise.
"""

import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from scripts.rank_codes import fill_cpt_metadata, _CPT_PT_LOOKUP

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# ── Unit tests (no API key needed) ────────────────────────────────────────────

def test_known_timed_code_fills_label_and_modifier():
    result = fill_cpt_metadata("97110", evidence={}, diagnoses=[])
    assert result["code"] == "97110"
    assert result["label"] == "Therapeutic Exercise"
    assert result["modifier"] == "GP"
    assert result["auto_filled"] is True


def test_known_timed_code_defaults_to_one_unit():
    result = fill_cpt_metadata("97110", evidence={}, diagnoses=[])
    assert result["units"] == 1
    assert any("8-minute rule" in n for n in result["auto_fill_notes"])


def test_known_untimed_code_always_one_unit():
    result = fill_cpt_metadata("97010", evidence={}, diagnoses=[])
    assert result["units"] == 1
    # No timed-unit warning for untimed codes
    assert not any("8-minute" in n for n in result["auto_fill_notes"])


def test_eval_code_fills_correctly():
    for code, expected_label in [
        ("97161", "Physical Therapy Evaluation - Low Complexity"),
        ("97162", "Physical Therapy Evaluation - Moderate Complexity"),
        ("97163", "Physical Therapy Evaluation - High Complexity"),
        ("97164", "Physical Therapy Re-evaluation"),
    ]:
        result = fill_cpt_metadata(code, evidence={}, diagnoses=[])
        assert result["label"] == expected_label, f"{code}: expected '{expected_label}'"
        assert result["units"] == 1


def test_unknown_code_returns_safe_defaults():
    result = fill_cpt_metadata("99999", evidence={}, diagnoses=[])
    assert result["code"] == "99999"
    assert result["modifier"] == "GP"
    assert result["units"] == 1
    assert result["dx_pointer"] == "A"
    assert any("not in the standard PT lookup table" in n for n in result["auto_fill_notes"])


def test_multiple_diagnoses_triggers_pointer_note():
    diagnoses = [
        {"code": "M17.11", "label": "OA right knee"},
        {"code": "M79.621", "label": "Pain in right upper arm"},
    ]
    result = fill_cpt_metadata("97110", evidence={}, diagnoses=diagnoses)
    assert any("Multiple diagnoses" in n for n in result["auto_fill_notes"])


def test_single_diagnosis_no_pointer_note():
    diagnoses = [{"code": "M17.11", "label": "OA right knee"}]
    result = fill_cpt_metadata("97110", evidence={}, diagnoses=diagnoses)
    assert not any("Multiple diagnoses" in n for n in result["auto_fill_notes"])


def test_lookup_table_covers_common_pt_codes():
    required = [
        "97110", "97140", "97530", "97112", "97010",
        "97161", "97162", "97163", "97164",
        "97116", "97035", "97124",
    ]
    for code in required:
        assert code in _CPT_PT_LOOKUP, f"Common PT code {code} missing from lookup table"


def test_code_with_whitespace_is_stripped():
    result = fill_cpt_metadata("  97140  ", evidence={}, diagnoses=[])
    assert result["code"] == "97140"
    assert result["label"] == "Manual Therapy Techniques"


# ── Integration tests (require API key) ───────────────────────────────────────

pytestmark_api = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping live integration tests",
)


@pytestmark_api
def test_generate_justification_from_code_only_knee_oa():
    """Full flow: user enters only '97110', system auto-fills metadata, generates justification."""
    from scripts.extract_evidence import extract_evidence
    from scripts.generate_justification import generate_per_code_justifications

    note = (FIXTURES / "sample_knee_oa_note.txt").read_text()
    ev = extract_evidence(note, encounter_id="test-manual-knee")

    diagnoses = [{"code": "M17.11", "label": "Primary osteoarthritis, right knee"}]
    meta = fill_cpt_metadata("97110", ev, diagnoses)

    assert meta["label"] == "Therapeutic Exercise"
    assert meta["modifier"] == "GP"
    assert meta["units"] == 1  # default before clinician updates

    justifications = generate_per_code_justifications(ev, [meta])
    assert "97110" in justifications
    text = justifications["97110"]
    assert len(text) > 100, "Justification should be a meaningful paragraph"
    # Should reference evidence from the knee OA note
    assert any(kw in text.lower() for kw in ["knee", "quadriceps", "osteoarthritis", "strength", "rom"])


@pytestmark_api
def test_generate_justification_eval_code():
    """97162 (eval) with auto-filled metadata produces a valid justification."""
    from scripts.extract_evidence import extract_evidence
    from scripts.generate_justification import generate_per_code_justifications

    note = (FIXTURES / "sample_knee_oa_note.txt").read_text()
    ev = extract_evidence(note, encounter_id="test-manual-eval")

    meta = fill_cpt_metadata("97162", ev, [{"code": "M17.11", "label": ""}])
    justifications = generate_per_code_justifications(ev, [meta])

    assert "97162" in justifications
    assert len(justifications["97162"]) > 80


@pytestmark_api
def test_unknown_code_still_generates_justification():
    """An unknown CPT code still gets a justification (with a lookup warning)."""
    from scripts.extract_evidence import extract_evidence
    from scripts.generate_justification import generate_per_code_justifications

    note = (FIXTURES / "sample_encounter_note.txt").read_text()
    ev = extract_evidence(note, encounter_id="test-unknown-code")

    meta = fill_cpt_metadata("97039", ev, [{"code": "M54.5", "label": ""}])
    assert any("not in the standard PT lookup table" in n for n in meta["auto_fill_notes"])

    justifications = generate_per_code_justifications(ev, [meta])
    assert "97039" in justifications
    assert len(justifications["97039"]) > 50
