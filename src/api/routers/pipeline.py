"""Coarse initial-screening + standalone gaps endpoint.

`/initial-screening` mirrors the Streamlit first-load — one round-trip
for rank+gaps+items. Use this from the React client on entry to the edit
stage. Use `/encounters/{id}/rank` and `/encounters/{id}/gaps` only when
the user explicitly re-runs one agent.
"""

from fastapi import APIRouter, Depends

from scripts.detect_gaps import detect_gaps
from scripts.pipeline import run_initial_screening
from src.api.deps import anthropic_key_scope, get_encounter_repo
from src.api.errors import upstream_llm_error
from src.api.models import (
    CodeItem,
    Diagnosis,
    GapsRequest,
    GapsResponse,
    InitialScreeningRequest,
    InitialScreeningResponse,
    RankedCode,
)
from src.api.repositories import EncounterRepo

router = APIRouter(prefix="/encounters/{encounter_id}", tags=["pipeline"])


@router.post(
    "/initial-screening",
    response_model=InitialScreeningResponse,
    dependencies=[Depends(anthropic_key_scope)],
)
def initial_screening(
    encounter_id: str,
    body: InitialScreeningRequest,
    repo: EncounterRepo = Depends(get_encounter_repo),
) -> InitialScreeningResponse:
    try:
        result = run_initial_screening(
            mode=body.mode,
            evidence=body.evidence,
            diagnoses=[d.model_dump() for d in body.diagnoses],
        )
    except Exception as exc:
        raise upstream_llm_error(str(exc))

    repo.save_ranked_codes(encounter_id, result["ranked"])
    repo.save_gaps(encounter_id, result["gaps"])
    repo.put_diagnoses(encounter_id, result["diagnoses"])
    repo.put_code_items(encounter_id, result["items"])
    repo.log(encounter_id, {"step": "initial_screening", "mode": body.mode, "status": "ok"})

    return InitialScreeningResponse(
        ranked=[RankedCode.model_validate(r) for r in result["ranked"]],
        gaps=GapsResponse.model_validate(result["gaps"]),
        items=[CodeItem.model_validate(it) for it in result["items"]],
        diagnoses=[Diagnosis.model_validate(d) for d in result["diagnoses"]],
    )


@router.post("/gaps", response_model=GapsResponse, dependencies=[Depends(anthropic_key_scope)])
def gaps(
    encounter_id: str,
    body: GapsRequest,
    repo: EncounterRepo = Depends(get_encounter_repo),
) -> GapsResponse:
    try:
        result = detect_gaps(body.evidence, body.ranked_codes, body.selected_code)
    except Exception as exc:
        raise upstream_llm_error(str(exc))
    repo.save_gaps(encounter_id, result)
    return GapsResponse.model_validate(result)
