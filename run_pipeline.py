#!/usr/bin/env python3
"""CLI entry point: run the full claim copilot pipeline on a plain-text encounter note."""

import argparse
import json
import os
import pathlib
import sys
import uuid
from datetime import date, datetime, timezone

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from src.orchestrator import run_pipeline


def build_minimal_package(note_text: str, encounter_id: str, clinician_id: str, patient_id: str) -> dict:
    doc_id = f"doc-{encounter_id}"
    return {
        "encounter_id": encounter_id,
        "date_of_service": date.today().isoformat(),
        "patient_id": patient_id,
        "clinician_id": clinician_id,
        "source_documents": {
            "uploaded_treatment_note": {
                "document_id": doc_id,
                "file_name": "encounter_note.txt",
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Healthcare Claim Copilot — run the full pipeline.")
    parser.add_argument("note_file", help="Path to a plain-text encounter note file.")
    parser.add_argument("--encounter-id", default=None, help="Encounter ID (auto-generated if omitted).")
    parser.add_argument("--clinician-id", default="cli-user", help="Clinician ID.")
    parser.add_argument("--patient-id", default="patient-001", help="Patient ID.")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set. Add it to a .env file or export it.", file=sys.stderr)
        sys.exit(1)

    note_path = pathlib.Path(args.note_file)
    if not note_path.exists():
        print(f"ERROR: Note file not found: {note_path}", file=sys.stderr)
        sys.exit(1)

    note_text = note_path.read_text()
    encounter_id = args.encounter_id or f"enc-{uuid.uuid4().hex[:8]}"
    package = build_minimal_package(note_text, encounter_id, args.clinician_id, args.patient_id)

    print(f"\n=== Healthcare Claim Copilot ===")
    print(f"Encounter ID : {encounter_id}")
    print(f"Note file    : {note_path}")
    print(f"Output dir   : outputs/{encounter_id}/\n")

    print("[ 1/5 ] Validating payload...")
    print("[ 2/5 ] Extracting encounter evidence...")
    print("[ 3/5 ] Ranking code options...")
    print("[ 4/5 ] Detecting documentation gaps...")
    print("[ 5/5 ] Drafting justification...\n")

    result = run_pipeline(package)

    if result.warnings:
        print("WARNINGS:")
        for w in result.warnings:
            print(f"  ⚠  {w}")
        print()

    if result.blocked:
        blocked = result.encounter_package.get("_blocked", {})
        print(f"PIPELINE BLOCKED: {blocked.get('reason')}")
        print(f"  {blocked.get('message')}")
        if gaps := blocked.get("gaps"):
            print("\n  Required actions:")
            for g in gaps:
                if g.get("severity") == "high":
                    print(f"    [HIGH] {g.get('description')} — {g.get('suggested_action')}")
        print(f"\nPartial outputs saved to: outputs/{encounter_id}/")
        sys.exit(2)

    j = result.justification or {}
    quality = j.get("evidence_quality", "unknown")
    print(f"Evidence quality : {quality}")
    print(f"Gaps detected    : {len(result.gap_analysis.get('gaps', []))}")
    print(f"Codes ranked     : {len(result.ranked_codes or [])}")

    if result.ranked_codes:
        top = result.ranked_codes[0]
        print(f"\nTop code : {top.get('code')} — {top.get('label')}")
        print(f"  Supportability score : {top.get('supportability_score', 'n/a')}")
        if top.get("compliance_warning"):
            print(f"  Compliance warning   : {top['compliance_warning']}")

    if draft := j.get("draft_paragraph"):
        print(f"\n--- Draft Justification ---\n{draft}\n---")
    else:
        print("\nNo draft paragraph generated (evidence quality insufficient).")
        for w in j.get("warnings", []):
            print(f"  {w}")

    print(f"\nAll outputs saved to: outputs/{encounter_id}/")


if __name__ == "__main__":
    main()
