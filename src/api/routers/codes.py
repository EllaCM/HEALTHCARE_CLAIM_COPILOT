"""Ranking + per-code evaluation + code-items CRUD."""

from fastapi import APIRouter, Depends, Query

from scripts.rag_justification import (
    evaluate_single_code,
    generate_per_code_justifications,
    normalize_evaluation_result,
)
from scripts.rank_codes import rank_codes, rank_codes_with_justifications
from src.api.deps import anthropic_key_scope, get_encounter_repo
from src.api.errors import upstream_llm_error
from src.api.models import (
    CodeEvaluateRequest,
    CodeEvaluateResponse,
    CodeItem,
    Diagnosis,
    RankRequest,
    RankResponse,
    RankedCode,
)
from src.api.repositories import EncounterRepo

router = APIRouter(prefix="/encounters/{encounter_id}", tags=["codes"])


# ── ranking ─────────────────────────────────────────────────────────────────
@router.post("/rank", response_model=RankResponse, dependencies=[Depends(anthropic_key_scope)])
def rank_for_encounter(
    encounter_id: str,
    body: RankRequest,
    include_justifications: bool = Query(default=False),
    repo: EncounterRepo = Depends(get_encounter_repo),
) -> RankResponse:
    try:
        if include_justifications:
            ranked = rank_codes_with_justifications(
                body.evidence, body.candidate_codes, body.clinic_config
            )
        else:
            ranked = rank_codes(body.evidence, body.candidate_codes, body.clinic_config)
    except Exception as exc:
        raise upstream_llm_error(str(exc))

    repo.save_ranked_codes(encounter_id, ranked)
    repo.log(encounter_id, {"step": "rank", "status": "ok", "with_justifications": include_justifications})
    return RankResponse(ranked=[RankedCode.model_validate(r) for r in ranked])


# ── per-code evaluate (RAG single-code) ─────────────────────────────────────
@router.post(
    "/codes/{cpt_code}/evaluate",
    response_model=CodeEvaluateResponse,
    dependencies=[Depends(anthropic_key_scope)],
)
def evaluate_code(
    encounter_id: str,
    cpt_code: str,
    body: CodeEvaluateRequest,
) -> CodeEvaluateResponse:
    try:
        matched = evaluate_single_code(
            body.evidence,
            cpt_code,
            label=body.label or "",
            units=body.units,
            minutes=body.minutes,
            note_text=body.note_text,
            patient_id=body.patient_id,
            encounter_id=encounter_id,
        )
    except Exception as exc:
        raise upstream_llm_error(str(exc))

    normalized, new_icds = normalize_evaluation_result(
        matched,
        current_code=cpt_code,
        existing_item=body.existing_item.model_dump(),
        existing_diagnoses=[d.model_dump() for d in body.existing_diagnoses],
    )
    return CodeEvaluateResponse(
        normalized=normalized,
        new_icds=[Diagnosis(**d) for d in new_icds],
    )


# ── single-code justification (re-run only) ─────────────────────────────────
@router.post(
    "/codes/{cpt_code}/justify",
    response_model=dict,
    dependencies=[Depends(anthropic_key_scope)],
)
def justify_code(
    encounter_id: str,
    cpt_code: str,
    body: dict,
) -> dict:
    try:
        result = generate_per_code_justifications(
            body.get("evidence", {}),
            [{"code": cpt_code, "label": body.get("label", "")}],
            gap_analysis=body.get("gap_analysis"),
            encounter_id=encounter_id,
        )
    except Exception as exc:
        raise upstream_llm_error(str(exc))
    return result


# ── code-items CRUD (stateful) ──────────────────────────────────────────────
@router.get("/code-items", response_model=list[CodeItem])
def get_code_items(
    encounter_id: str,
    repo: EncounterRepo = Depends(get_encounter_repo),
) -> list[CodeItem]:
    return [CodeItem.model_validate(it) for it in repo.get_code_items(encounter_id)]


@router.put("/code-items", response_model=list[CodeItem])
def put_code_items(
    encounter_id: str,
    items: list[CodeItem],
    repo: EncounterRepo = Depends(get_encounter_repo),
) -> list[CodeItem]:
    repo.put_code_items(encounter_id, [i.model_dump() for i in items])
    return items


@router.delete("/code-items/{item_id}", response_model=list[CodeItem])
def delete_code_item(
    encounter_id: str,
    item_id: str,
    repo: EncounterRepo = Depends(get_encounter_repo),
) -> list[CodeItem]:
    """Soft-delete (mirrors `deleted_ids` in app.py — sets selected=False)."""
    items = repo.soft_delete_code_item(encounter_id, item_id)
    return [CodeItem.model_validate(it) for it in items]
