"""CLI test for RAG-powered CPT justification.

Usage:
    python tests/test_rag_justification.py --encounter smoke-lbp --cpt 97110
    python tests/test_rag_justification.py --encounter smoke-knee --cpt 97140
    python tests/test_rag_justification.py --patient patient-001 --encounter smoke-lbp --cpt 97110
"""

import argparse
import json
import pathlib
import sys

# Allow running from project root without installing the package
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent

_ENCOUNTER_PATIENT_MAP: dict[str, str] = {
    "smoke-lbp": "patient-001",
    "smoke-knee": "patient-002",
}

_FIXTURE_MAP: dict[str, str] = {
    "smoke-lbp": "sample_encounter_note.txt",
    "smoke-knee": "sample_knee_oa_note.txt",
}


def _infer_patient(encounter_id: str) -> str:
    return _ENCOUNTER_PATIENT_MAP.get(encounter_id, f"patient-{encounter_id}")


def _load_note(patient_id: str, encounter_id: str) -> str:
    patient_path = _PROJECT_ROOT / "data" / "patients" / patient_id / "encounters" / encounter_id / "note.txt"
    if patient_path.exists():
        return patient_path.read_text()
    fixture_name = _FIXTURE_MAP.get(encounter_id)
    if fixture_name:
        fixture_path = _PROJECT_ROOT / "tests" / "fixtures" / fixture_name
        if fixture_path.exists():
            print(f"[load] patient data not found, falling back to fixture: {fixture_path.name}")
            return fixture_path.read_text()
    raise FileNotFoundError(
        f"No note found for patient '{patient_id}' encounter '{encounter_id}'. "
        f"Expected: {patient_path}"
    )


def _load_or_extract_evidence(encounter_id: str, note_text: str) -> dict:
    evidence_path = _PROJECT_ROOT / "outputs" / encounter_id / "evidence.json"
    if evidence_path.exists():
        print(f"[evidence] loaded from {evidence_path}")
        return json.loads(evidence_path.read_text())
    print("[evidence] no cached evidence found, running extract_evidence...")
    from scripts.extract_evidence import extract_evidence
    return extract_evidence(note_text, [], encounter_id)


def _print_result(result: dict, cpt_code: str, cpt_def: dict) -> None:
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"CPT CODE: {cpt_code} — {cpt_def.get('label', '')}")
    print(f"Description : {cpt_def.get('description', 'N/A')}")
    print(f"Indication  : {cpt_def.get('typical_indication', 'N/A')}")
    print(sep)

    sources = result.get("retrieved_sources", [])
    if sources:
        print(f"\nRETRIEVED CHART SECTIONS ({len(sources)} chunks):")
        for s in sources:
            print(f"  [{s['section']}] {s['text_span'][:100]}...")
    else:
        print("\n(no retrieved chunks — ingestion may have been skipped)")

    bullets = result.get("structured_bullets", [])
    if bullets:
        print(f"\nSTRUCTURED BULLETS ({len(bullets)}):")
        for b in bullets:
            print(f"  [{b.get('section')}] {b.get('label', '')}: {b.get('content', '')}")

    print(f"\nEVIDENCE QUALITY: {result.get('evidence_quality', 'unknown')}")

    warnings = result.get("warnings", [])
    if warnings:
        print(f"WARNINGS: {'; '.join(warnings)}")

    draft = result.get("draft_paragraph")
    print(f"\nDRAFT PARAGRAPH:")
    print(draft if draft else "(none — evidence quality insufficient)")
    print(sep)


def main() -> None:
    parser = argparse.ArgumentParser(description="Test RAG-powered CPT justification.")
    parser.add_argument("--encounter", required=True, help="Encounter ID, e.g. smoke-lbp")
    parser.add_argument("--cpt", required=True, help="CPT code, e.g. 97110")
    parser.add_argument("--patient", default=None, help="Patient ID (inferred if omitted)")
    args = parser.parse_args()

    patient_id = args.patient or _infer_patient(args.encounter)
    encounter_id = args.encounter
    cpt_code = args.cpt

    print(f"[config] patient={patient_id}  encounter={encounter_id}  cpt={cpt_code}")

    note_text = _load_note(patient_id, encounter_id)
    print(f"[load] note loaded ({len(note_text)} chars)")

    evidence = _load_or_extract_evidence(encounter_id, note_text)

    # Ingest (idempotent)
    from scripts.ingest_patient_docs import ingest_encounter
    collection_name = ingest_encounter(patient_id, encounter_id, note_text)
    print(f"[ingest] collection: {collection_name}")

    # RAG justification for the single code
    from scripts.rag_justification import evaluate_single_code
    result = evaluate_single_code(
        evidence, cpt_code,
        patient_id=patient_id, encounter_id=encounter_id, note_text=note_text,
    )

    # Print CPT definition for context
    from scripts.cpt_definitions_adapter import CPTDefinitionsAdapter
    cpt_def = CPTDefinitionsAdapter().get_definition(cpt_code)

    _print_result(result, cpt_code, cpt_def)


if __name__ == "__main__":
    main()
