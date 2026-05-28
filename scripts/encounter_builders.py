"""Builders and helpers for encounter packages and CPT items.

Importable independently of Streamlit and the CLI — both `app.py` and
`run_pipeline.py` call these. New signatures take explicit args; no
`st.session_state` access.
"""

import uuid
from datetime import date, datetime, timezone


_ADMIN_DOC_TERMS = {
    "prior authorization", "prior auth", "insurance", "referral number",
    "auth number", "coverage", "benefit", "copay", "deductible", "network",
    "billing", "authorization", "payer", "claim number",
}


def _pointer(idx: int) -> str:
    return chr(65 + idx)


def _pointer_from_codes(icd_codes: list[str], diagnoses: list[dict]) -> str:
    pointers = []
    for icd in icd_codes:
        for i, d in enumerate(diagnoses):
            if d["code"] == icd:
                pointers.append(_pointer(i))
    return "".join(pointers) or "A"


def build_minimal_package(
    *,
    note_text: str,
    encounter_id: str,
    clinician_id: str,
    patient_id: str,
) -> dict:
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


def make_cpt_item(ranked: dict, idx: int, diagnoses: list[dict]) -> dict:
    return {
        "id": f"cpt-{idx}-{uuid.uuid4().hex[:4]}",
        "selected": True,
        "code": ranked.get("code", ""),
        "modifier": ranked.get("modifier", "GP"),
        "label": ranked.get("label", ""),
        "units": int(ranked.get("units", 1)),
        "minutes": 0,
        "dx_pointer": ranked.get("diagnosis_pointer") or _pointer_from_codes(
            ranked.get("diagnosis_codes", []), diagnoses
        ),
        "justification": ranked.get("justification", ""),
        "supportability_score": float(ranked.get("supportability_score", 0)),
        "compliance_warning": ranked.get("compliance_warning"),
        "supporting_docs": ranked.get("supporting_docs", []),
        "missing_elements": ranked.get("missing_elements", []),
        "evidence_summary": ranked.get("evidence_summary", ""),
        "auto_fill_notes": ranked.get("auto_fill_notes", []),
    }


def is_clinical_doc(requirement: str) -> bool:
    """Return True when the requirement is a clinical documentation item, not an admin/billing one."""
    req_lower = requirement.lower()
    return not any(term in req_lower for term in _ADMIN_DOC_TERMS)
