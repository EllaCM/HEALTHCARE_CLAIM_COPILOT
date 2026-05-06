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

    def test_underbilling_instructs_standard_justification(self):
        result = _build_unit_defense_prompt(units=1, code="97110", is_timed=True).lower()
        assert "standard" in result or "confident" in result or "natural" in result

    def test_underbilling_does_not_instruct_defense_bullet(self):
        result = _build_unit_defense_prompt(units=1, code="97110", is_timed=True).lower()
        assert "medical_necessity" not in result or "defense" not in result.split("medical_necessity")[0]
        assert "add a" not in result or "medical_necessity" not in result

    def test_missing_per_code_time_instructs_activity_reasoning(self):
        result = _build_unit_defense_prompt(units=1, code="97110", is_timed=True).lower()
        # New behavior: reason from treatment activities, not warn about missing time
        assert "treatment activit" in result or "attributable" in result or "allocated" in result
        assert "do not warn" in result or "rarely documented" in result

    def test_different_unit_counts_reflected(self):
        for n in (1, 2, 3, 4):
            result = _build_unit_defense_prompt(units=n, code="97530", is_timed=True)
            assert f"{n} unit" in result


# ── New boundary + prose requirement tests ────────────────────────────────────

class TestEightMinuteRuleBoundaries:
    """Explicit per-boundary assertions for the 8-minute rule thresholds."""

    def test_exactly_8_minutes_gives_1_unit(self):
        assert _eight_minute_rule(8) == 1

    def test_22_minutes_gives_1_unit(self):
        assert _eight_minute_rule(22) == 1

    def test_23_minutes_gives_2_units(self):
        assert _eight_minute_rule(23) == 2

    def test_37_minutes_gives_2_units(self):
        assert _eight_minute_rule(37) == 2

    def test_38_minutes_gives_3_units(self):
        assert _eight_minute_rule(38) == 3

    def test_7_minutes_gives_0_units(self):
        assert _eight_minute_rule(7) == 0


class TestUnitDefenseProseRequirement:
    """Tests for the updated prompt requiring unit count in draft_paragraph."""

    def test_timed_prompt_contains_unit_count(self):
        result = _build_unit_defense_prompt(units=3, code="97110", is_timed=True)
        assert "3 unit" in result

    def test_timed_prompt_references_documented_minutes(self):
        result = _build_unit_defense_prompt(units=2, code="97140", is_timed=True)
        assert "documented minutes" in result.lower() or "documented" in result.lower()

    def test_timed_prompt_instructs_prose_inclusion(self):
        result = _build_unit_defense_prompt(units=1, code="97530", is_timed=True)
        assert "draft_paragraph" in result or "paragraph" in result.lower() or "MUST" in result

    def test_untimed_prompt_returns_empty_string(self):
        assert _build_unit_defense_prompt(units=1, code="97010", is_timed=False) == ""

    def test_untimed_prompt_no_eight_minute_reference(self):
        result = _build_unit_defense_prompt(units=1, code="97012", is_timed=False)
        assert "8-minute" not in result


# ── Integration tests (require both API keys) ──────────────────────────────────

def _has_chromadb() -> bool:
    try:
        import chromadb  # noqa: F401
        return True
    except ImportError:
        return False


_NEEDS_KEYS = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY")
    or not os.environ.get("VOYAGE_API_KEY")
    or not _has_chromadb(),
    reason="ANTHROPIC_API_KEY, VOYAGE_API_KEY, and chromadb required for integration tests",
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

    # LBP note: 15 min documented → max 1 unit; submitting 3 with minutes=15 = overbilling block
    result = evaluate_single_code(
        evidence, "97110", units=3, minutes=15,
        patient_id="patient-001", encounter_id="smoke-lbp", note_text=note,
    )

    assert result.get("overbilling") is True, (
        f"Expected overbilling=True early return, got: {result}"
    )
    assert result.get("draft_paragraph") is None, "Overbilling should produce no justification"
    assert result.get("max_units") == 1, f"Expected max_units=1, got {result.get('max_units')}"


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
