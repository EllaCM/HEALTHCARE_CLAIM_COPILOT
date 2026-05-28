"""CPT code definitions — read-only, served from the YAML-backed adapter."""

from fastapi import APIRouter, Depends

from scripts.cpt_definitions_adapter import CPTDefinitionsAdapter
from src.api.deps import get_cpt_adapter
from src.api.models import CPTDefinition

router = APIRouter(prefix="/cpt-codes", tags=["cpt-codes"])


@router.get("", response_model=dict[str, CPTDefinition])
def list_cpt_codes(adapter: CPTDefinitionsAdapter = Depends(get_cpt_adapter)) -> dict[str, dict]:
    return adapter.get_all_codes()


@router.get("/{cpt_code}", response_model=CPTDefinition)
def get_cpt_code(
    cpt_code: str,
    adapter: CPTDefinitionsAdapter = Depends(get_cpt_adapter),
) -> dict:
    return adapter.get_definition(cpt_code)
