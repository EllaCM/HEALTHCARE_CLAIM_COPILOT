"""Smoke test: RAG justification pipeline with explicit CPT code + treatment minutes.

Covers four scenarios for a given encounter note:
  1. Correct billing    — units match documented minutes (no warning expected)
  2. Overcoding         — units exceed what the documented minutes support
  3. Underbilling       — units below what the documented minutes support
  4. Untimed code       — always 1 unit regardless of minutes

Usage:
    python tests/test_justification_with_units.py
    
    python tests/test_justification_with_units.py --encounter smoke-lbp --cpt 97110 --minutes 30 --units 3
    python tests/test_justification_with_units.py --all
"""

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent
_FIXTURES = _PROJECT_ROOT / "tests" / "fixtures"

_ENCOUNTER_PATIENT_MAP = {
    "smoke-lbp": "patient-001",
    "smoke-knee": "patient-002",
}

_FIXTURE_MAP = {
    "smoke-lbp": "sample_encounter_note.txt",
    "smoke-knee": "sample_knee_oa_note.txt",
}

SEP = "─" * 70


def _load_note(patient_id: str, encounter_id: str) -> str:
    patient_path = _PROJECT_ROOT / "data" / "patients" / patient_id / "encounters" / encounter_id / "note.txt"
    if patient_path.exists():
        return patient_path.read_text()
    fixture_name = _FIXTURE_MAP.get(encounter_id)
    if fixture_name:
        fixture_path = _FIXTURES / fixture_name
        if fixture_path.exists():
            print(f"[load] falling back to fixture: {fixture_path.name}")
            return fixture_path.read_text()
    raise FileNotFoundError(f"No note found for patient='{patient_id}' encounter='{encounter_id}'")


def _load_or_extract_evidence(encounter_id: str, note_text: str) -> dict:
    cache = _PROJECT_ROOT / "outputs" / encounter_id / "evidence.json"
    if cache.exists():
        print(f"[evidence] cached at {cache}")
        return json.loads(cache.read_text())
    print("[evidence] extracting from note...")
    from scripts.extract_evidence import extract_evidence
    ev = extract_evidence(note_text, [], encounter_id)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(ev, indent=2))
    print(f"[evidence] saved to {cache}")
    return ev


def _compute_expected_units(minutes: int) -> int:
    from scripts.billing_utils import compute_timed_units
    return compute_timed_units(minutes)


def _print_result(label: str, cpt_code: str, minutes: int | None, units: int | None,
                  is_timed: bool, result: dict) -> None:
    print(f"\n{SEP}")
    print(f"SCENARIO : {label}")
    print(f"CPT Code : {cpt_code}  |  Minutes: {minutes}  |  Units submitted: {units}  |  Timed: {is_timed}")
    if minutes is not None and is_timed:
        expected = _compute_expected_units(minutes)
        print(f"Expected units (8-min rule): {expected}  →  ", end="")
        if units is None:
            print("(no units submitted)")
        elif units == expected:
            print("✅ CORRECT BILLING")
        elif units > expected:
            print(f"⚠️  OVERCODING  (+{units - expected} unit(s))")
        else:
            print(f"ℹ️  UNDERBILLING  (-{expected - units} unit(s))")
    print(SEP)

    if result.get("overbilling"):
        print(f"\n⛔ OVERBILLING BLOCKED")
        print(f"  {result.get('compliance_warning')}")
        print("  Justification: (not generated)")
    else:
        draft = result.get("draft_paragraph") or result.get("justification")
        print("\nDRAFT PARAGRAPH:")
        print(draft if draft else "(none — evidence quality insufficient)")

    warnings = result.get("warnings", [])
    if warnings:
        print(f"\nWARNINGS ({len(warnings)}):")
        for i, w in enumerate(warnings, 1):
            print(f"  {i}. {w}")
    else:
        print("\nWARNINGS: none")

    score = result.get("supportability_score")
    quality = result.get("evidence_quality", "unknown")
    print(f"\nEVIDENCE QUALITY: {quality}  |  SCORE: {score}")
    print(SEP)


def run_single(encounter_id: str, patient_id: str, cpt_code: str,
               minutes: int | None, units: int | None, label: str = "Custom") -> None:
    note_text = _load_note(patient_id, encounter_id)
    evidence = _load_or_extract_evidence(encounter_id, note_text)

    from scripts.ingest_patient_docs import ingest_encounter
    ingest_encounter(patient_id, encounter_id, note_text)
    print(f"[ingest] done for encounter={encounter_id}")

    from scripts.rag_justification import evaluate_single_code
    from scripts.cpt_definitions_adapter import CPTDefinitionsAdapter

    cpt_def = CPTDefinitionsAdapter().get_definition(cpt_code)
    is_timed = cpt_def.get("timed", True)

    # Derive units from minutes if not explicitly provided
    effective_units = units
    if effective_units is None and minutes is not None and is_timed:
        effective_units = _compute_expected_units(minutes)

    result = evaluate_single_code(
        evidence, cpt_code,
        units=effective_units,
        minutes=minutes,
        patient_id=patient_id,
        encounter_id=encounter_id,
        note_text=note_text,
    )

    _print_result(label, cpt_code, minutes, effective_units, is_timed, result)


def run_all_scenarios(encounter_id: str, patient_id: str) -> None:
    """Run the four canonical billing scenarios against the smoke-lbp note."""
    note_text = _load_note(patient_id, encounter_id)
    evidence = _load_or_extract_evidence(encounter_id, note_text)

    from scripts.ingest_patient_docs import ingest_encounter
    from scripts.rag_justification import evaluate_single_code
    from scripts.cpt_definitions_adapter import CPTDefinitionsAdapter

    ingest_encounter(patient_id, encounter_id, note_text)
    print(f"\n[ingest] done  |  encounter={encounter_id}  patient={patient_id}")

    adapter = CPTDefinitionsAdapter()

    scenarios = [
        # (label, cpt_code, minutes, units_override)
        # 97110 therapeutic exercise — note documents 15 min → max 1 unit
        ("1. Correct billing (15 min → 1 unit)",   "97110", 15, 1),
        ("2. Overcoding    (15 min → submitting 3 units)", "97110", 15, 3),
        ("3. Underbilling  (30 min → submitting 1 unit)",  "97110", 30, 1),
        # 97010 hot pack — untimed, always 1 unit regardless of minutes
        ("4. Untimed code  (97010 hot pack, 15 min)", "97010", 15, None),
    ]

    for label, cpt_code, minutes, units_override in scenarios:
        cpt_def = adapter.get_definition(cpt_code)
        is_timed = cpt_def.get("timed", True)
        effective_units = units_override if units_override is not None else (
            _compute_expected_units(minutes) if is_timed else 1
        )
        result = evaluate_single_code(
            evidence, cpt_code,
            units=effective_units if is_timed else None,
            minutes=minutes,
            patient_id=patient_id,
            encounter_id=encounter_id,
            note_text=note_text,
        )
        _print_result(label, cpt_code, minutes, effective_units, is_timed, result)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke test: RAG justification with CPT code + treatment minutes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--encounter", default="smoke-lbp", help="Encounter ID (default: smoke-lbp)")
    parser.add_argument("--patient",   default=None,        help="Patient ID (inferred if omitted)")
    parser.add_argument("--cpt",       default="97110",     help="CPT code (default: 97110)")
    parser.add_argument("--minutes",   type=int, default=None, help="Treatment minutes for this code")
    parser.add_argument("--units",     type=int, default=None, help="Units to submit (overrides auto-calc)")
    parser.add_argument("--all",       action="store_true",   help="Run all four canonical scenarios")
    args = parser.parse_args()

    patient_id = args.patient or _ENCOUNTER_PATIENT_MAP.get(args.encounter, f"patient-{args.encounter}")

    if args.all:
        run_all_scenarios(args.encounter, patient_id)
    else:
        if args.minutes is None and args.units is None:
            parser.error("Provide --minutes, --units, or --all")
        run_single(
            encounter_id=args.encounter,
            patient_id=patient_id,
            cpt_code=args.cpt,
            minutes=args.minutes,
            units=args.units,
            label="Custom",
        )


if __name__ == "__main__":
    main()
