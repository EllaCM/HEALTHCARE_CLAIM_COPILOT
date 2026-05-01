"""Unit and integration tests for billing unit defense in RAG justification.

Unit tests (no API calls):
    pytest tests/test_unit_defense.py -k "not integration" -v

All tests (requires ANTHROPIC_API_KEY + VOYAGE_API_KEY):
    pytest tests/test_unit_defense.py -v
"""

import os
import pathlib
import sys

import pytest
from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

load_dotenv()  # populate os.environ before skipif markers are evaluated

from scripts.rag_justification_prompts import _eight_minute_rule, _build_unit_defense_prompt

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


# ── Pure function unit tests (no API) ─────────────────────────────────────────

class TestEightMinuteRule:
    def test_below_minimum_returns_zero(self):
        assert _eight_minute_rule(0) == 0
        assert _eight_minute_rule(7) == 0

    def test_one_unit_boundaries(self):
        assert _eight_minute_rule(8) == 1   # floor
        assert _eight_minute_rule(22) == 1  # ceiling

    def test_two_unit_boundaries(self):
        assert _eight_minute_rule(23) == 2  # floor
        assert _eight_minute_rule(37) == 2  # ceiling

    def test_three_unit_boundaries(self):
        assert _eight_minute_rule(38) == 3
        assert _eight_minute_rule(52) == 3

    def test_four_unit_boundaries(self):
        assert _eight_minute_rule(53) == 4
        assert _eight_minute_rule(67) == 4

    def test_five_units(self):
        assert _eight_minute_rule(68) == 5


class TestBuildUnitDefensePrompt:
    def test_untimed_code_returns_empty(self):
        result = _build_unit_defense_prompt(units=1, code="97010", is_timed=False)
        assert result == ""

    def test_untimed_regardless_of_units(self):
        # Even if someone passes units=3 for an untimed code, no defense block
        assert _build_unit_defense_prompt(units=3, code="97150", is_timed=False) == ""

    def test_timed_code_includes_submitted_units(self):
        result = _build_unit_defense_prompt(units=1, code="97110", is_timed=True)
        assert "1 unit" in result

    def test_timed_code_includes_cpt_code(self):
        result = _build_unit_defense_prompt(units=2, code="97140", is_timed=True)
        assert "97140" in result

    def test_underbilling_instructs_defense(self):
        result = _build_unit_defense_prompt(units=1, code="97110", is_timed=True).lower()
        assert "defend" in result or "defending" in result or "explain" in result

    def test_overcoding_instructs_compliance_warning(self):
        result = _build_unit_defense_prompt(units=1, code="97110", is_timed=True).lower()
        assert "exceed" in result or "compliance warning" in result

    def test_unverifiable_time_instructs_warning(self):
        result = _build_unit_defense_prompt(units=1, code="97110", is_timed=True).lower()
        assert "warning" in result or "cannot" in result or "not found" in result

    def test_different_unit_counts_reflected(self):
        for n in (1, 2, 3, 4):
            result = _build_unit_defense_prompt(units=n, code="97530", is_timed=True)
            assert f"{n} unit" in result


# ── Integration tests (require both API keys) ──────────────────────────────────

_NEEDS_KEYS = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") or not os.environ.get("VOYAGE_API_KEY"),
    reason="ANTHROPIC_API_KEY and VOYAGE_API_KEY required for integration tests",
)


@_NEEDS_KEYS
def test_overcoding_produces_units_warning():
    """Submit units=3 for a service with 15 min documented → should warn about overcoding."""
    from dotenv import load_dotenv
    load_dotenv()

    from scripts.extract_evidence import extract_evidence
    from scripts.rag_justification import evaluate_single_code

    note = (FIXTURES / "sample_encounter_note.txt").read_text()
    # Use a stable encounter so ingestion is idempotent
    evidence = extract_evidence(note, [], "test-unit-defense-overcode")

    # LBP note: core stabilization = 15 min → max 1 unit; submitting 3 = overcoding
    result = evaluate_single_code(
        evidence, "97110", units=3,
        patient_id="patient-001", encounter_id="smoke-lbp", note_text=note,
    )

    warnings = result.get("warnings", [])
    assert any("unit" in w.lower() or "exceed" in w.lower() for w in warnings), (
        f"Expected a units/overcoding warning, got: {warnings}"
    )


@_NEEDS_KEYS
def test_exact_match_produces_no_unit_defense_bullet():
    """Submit units=1 for a service with 15 min documented (max=1) → no defense bullet needed."""
    from dotenv import load_dotenv
    load_dotenv()

    from scripts.extract_evidence import extract_evidence
    from scripts.rag_justification import evaluate_single_code

    note = (FIXTURES / "sample_encounter_note.txt").read_text()
    evidence = extract_evidence(note, [], "test-unit-defense-exact")

    result = evaluate_single_code(
        evidence, "97110", units=1,
        patient_id="patient-001", encounter_id="smoke-lbp", note_text=note,
    )

    # Draft paragraph should exist (strong evidence) and not contain overcoding language
    assert result.get("draft_paragraph") is not None
    draft_lower = result["draft_paragraph"].lower()
    assert "exceed" not in draft_lower
