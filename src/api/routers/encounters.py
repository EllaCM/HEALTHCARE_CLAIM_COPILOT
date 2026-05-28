"""Encounter CRUD, screening, diagnosis list, and finalize endpoints."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends

from scripts.claim_builder import build_cms1500_text
from scripts.encounter_builders import build_minimal_package
from scripts.extract_evidence import extract_evidence
from scripts.validate_payload import validate_payload
from src.api.deps import anthropic_key_scope, get_encounter_repo
from src.api.errors import upstream_llm_error, validation_failed
from src.api.models import (
    Diagnosis,
    EncounterCreate,
    EncounterPatch,
    EncounterSummary,
    Evidence,
    FinalizeRequest,
    FinalizeResponse,
    ScreenRequest,
    ScreenResponse,
)
from src.api.repositories import EncounterRepo

router = APIRouter(prefix="/encounters", tags=["encounters"])


def _new_id() -> str:
    return f"enc-{uuid.uuid4().hex[:8]}"


# ── CRUD ────────────────────────────────────────────────────────────────────
@router.post("", response_model=dict)
def create_encounter(
    body: EncounterCreate,
    repo: EncounterRepo = Depends(get_encounter_repo),
) -> dict:
    encounter_id = body.encounter_id or _new_id()
    pkg = build_minimal_package(
        note_text=body.note_text,
        encounter_id=encounter_id,
        clinician_id=body.clinician_id,
        patient_id=body.patient_id,
    )
    errors = validate_payload(pkg)
    if errors:
        raise validation_failed(errors)
    return repo.create_package(encounter_id, pkg)


@router.get("/{encounter_id}", response_model=dict)
def get_encounter(
    encounter_id: str,
    repo: EncounterRepo = Depends(get_encounter_repo),
) -> dict:
    return repo.get_package(encounter_id)


@router.patch("/{encounter_id}", response_model=dict)
def patch_encounter(
    encounter_id: str,
    patch: EncounterPatch,
    repo: EncounterRepo = Depends(get_encounter_repo),
) -> dict:
    return repo.patch_package(encounter_id, patch.model_dump(exclude_unset=True))


@router.get("", response_model=list[EncounterSummary])
def list_encounters(
    limit: int = 50,
    repo: EncounterRepo = Depends(get_encounter_repo),
) -> list[EncounterSummary]:
    out: list[EncounterSummary] = []
    for eid in repo.list_encounter_ids(limit=limit):
        try:
            pkg = repo.get_package(eid)
        except Exception:
            continue
        out.append(
            EncounterSummary(
                encounter_id=eid,
                date_of_service=pkg.get("date_of_service"),
                patient_id=pkg.get("patient_id"),
                clinician_id=pkg.get("clinician_id"),
            )
        )
    return out


# ── screen (extract_evidence + ICD seed) ────────────────────────────────────
@router.post("/screen", response_model=ScreenResponse, dependencies=[Depends(anthropic_key_scope)])
def screen_encounter(
    body: ScreenRequest,
    repo: EncounterRepo = Depends(get_encounter_repo),
) -> ScreenResponse:
    encounter_id = body.encounter_id or _new_id()
    try:
        ev = extract_evidence(body.note_text, encounter_id=encounter_id)
    except Exception as exc:
        raise upstream_llm_error(str(exc))

    repo.save_evidence(encounter_id, ev)
    repo.log(encounter_id, {"step": "screen", "status": "ok"})
    return ScreenResponse(encounter_id=encounter_id, evidence=Evidence.model_validate(ev))


# ── diagnoses ───────────────────────────────────────────────────────────────
@router.get("/{encounter_id}/diagnoses", response_model=list[Diagnosis])
def get_diagnoses(
    encounter_id: str,
    repo: EncounterRepo = Depends(get_encounter_repo),
) -> list[Diagnosis]:
    return [Diagnosis(**d) for d in repo.get_diagnoses(encounter_id)]


@router.put("/{encounter_id}/diagnoses", response_model=list[Diagnosis])
def put_diagnoses(
    encounter_id: str,
    diagnoses: list[Diagnosis],
    repo: EncounterRepo = Depends(get_encounter_repo),
) -> list[Diagnosis]:
    repo.put_diagnoses(encounter_id, [d.model_dump() for d in diagnoses])
    return diagnoses


# ── finalize (CMS-1500 builder) ─────────────────────────────────────────────
@router.post("/{encounter_id}/finalize", response_model=FinalizeResponse)
def finalize_encounter(
    encounter_id: str,
    body: FinalizeRequest,
    repo: EncounterRepo = Depends(get_encounter_repo),
) -> FinalizeResponse:
    pkg = repo.get_package(encounter_id)
    text = build_cms1500_text(
        encounter_id=encounter_id,
        date_of_service=body.date_of_service or date.today().isoformat(),
        patient_name=body.patient_name,
        dob=body.dob,
        patient_id=pkg.get("patient_id", ""),
        clinician_id=pkg.get("clinician_id", ""),
        diagnoses=[d.model_dump() for d in body.diagnoses],
        items=[i.model_dump() for i in body.items],
    )
    # Persist the formatted document so a React client can re-fetch later.
    from src import storage
    storage.save_json(encounter_id, "cms1500.txt", text)  # JSON-encoded string; raw text variant is a follow-up
    repo.log(encounter_id, {"step": "finalize", "status": "ok"})
    return FinalizeResponse(encounter_id=encounter_id, cms1500_text=text)
