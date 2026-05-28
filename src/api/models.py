"""Pydantic request/response schemas for the FastAPI surface.

Most response shapes mirror what the underlying `scripts/*` functions
already return; we declare the contract explicitly so OpenAPI is useful
and so the React client gets typed bindings via `openapi-typescript`.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


# ── common ───────────────────────────────────────────────────────────────────
class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# ── encounter package ───────────────────────────────────────────────────────
class EncounterCreate(BaseModel):
    note_text: str = Field(..., min_length=1)
    patient_id: str = "patient-001"
    clinician_id: str = "clinician-001"
    encounter_id: str | None = None  # server generates if absent


class EncounterPatch(BaseModel):
    patient_name: str | None = None
    dob: str | None = None
    patient_id: str | None = None
    clinician_id: str | None = None
    date_of_service: str | None = None


class EncounterSummary(BaseModel):
    encounter_id: str
    date_of_service: str | None = None
    patient_id: str | None = None
    clinician_id: str | None = None


# ── evidence / screen ───────────────────────────────────────────────────────
class ScreenRequest(BaseModel):
    note_text: str
    patient_id: str = "patient-001"
    clinician_id: str = "clinician-001"
    encounter_id: str | None = None


class Evidence(BaseModel):
    patient_condition: str | None = None
    symptoms: list[str] = []
    functional_limitation: str | None = None
    objective_findings: list[str] = []
    prior_treatment_history: list[str] = []
    treatment_provided: list[str] = []
    medical_necessity_signals: list[str] = []
    missing_information: list[str] = []
    confidence_score: float | None = None
    session_duration_minutes: int | None = None
    seed_icd_codes: list[str] = []
    # Allow extra keys that the LLM may emit; OpenAPI clients should treat as Any.
    model_config = {"extra": "allow"}


class ScreenResponse(BaseModel):
    encounter_id: str
    evidence: Evidence


# ── ranking ─────────────────────────────────────────────────────────────────
class SupportingDoc(BaseModel):
    requirement: str
    present: bool = False
    note: str | None = None


class RankedCode(BaseModel):
    code: str
    label: str
    modifier: str | None = "GP"
    units: int = 1
    rank: int | None = None
    supportability_score: float = 0.0
    diagnosis_codes: list[str] = []
    diagnosis_pointer: str | None = "A"
    evidence_summary: str = ""
    missing_elements: list[str] = []
    compliance_warning: str | None = None
    supporting_docs: list[SupportingDoc] = []
    justification: str = ""
    model_config = {"extra": "allow"}


class RankRequest(BaseModel):
    evidence: dict[str, Any]
    candidate_codes: list[dict[str, str]] | None = None
    clinic_config: dict[str, Any] | None = None


class RankResponse(BaseModel):
    ranked: list[RankedCode]


# ── gaps ────────────────────────────────────────────────────────────────────
class Gap(BaseModel):
    gap_id: str | None = None
    description: str
    severity: Literal["low", "medium", "high"] = "medium"
    suggested_action: str | None = None
    affected_sections: list[str] = []


class GapsRequest(BaseModel):
    evidence: dict[str, Any]
    ranked_codes: list[dict[str, Any]] = []
    selected_code: str | None = None


class GapsResponse(BaseModel):
    gaps: list[Gap] = []
    recommendation: Literal["continue", "warn", "block"] = "continue"
    summary: str = ""


# ── code items (UI-shaped editable list) ────────────────────────────────────
class Diagnosis(BaseModel):
    code: str
    label: str = ""
    pointer: str = "A"


class CodeItem(BaseModel):
    id: str
    selected: bool = True
    code: str
    modifier: str = "GP"
    label: str = ""
    units: int = 1
    minutes: int = 0
    dx_pointer: str = "A"
    justification: str = ""
    supportability_score: float = 0.0
    compliance_warning: str | None = None
    supporting_docs: list[SupportingDoc] = []
    missing_elements: list[str] = []
    evidence_summary: str = ""
    auto_fill_notes: list[str] = []


# ── initial-screening (coarse pipeline endpoint) ────────────────────────────
class InitialScreeningRequest(BaseModel):
    mode: Literal["both", "codes", "justification"] = "both"
    evidence: dict[str, Any]
    diagnoses: list[Diagnosis] = []


class InitialScreeningResponse(BaseModel):
    ranked: list[RankedCode]
    gaps: GapsResponse
    items: list[CodeItem]
    diagnoses: list[Diagnosis]


# ── per-code evaluate ───────────────────────────────────────────────────────
class CodeEvaluateRequest(BaseModel):
    evidence: dict[str, Any]
    label: str | None = ""
    units: int | None = None
    minutes: int | None = None
    note_text: str | None = None
    patient_id: str | None = None
    existing_item: CodeItem
    existing_diagnoses: list[Diagnosis] = []


class CodeEvaluateResponse(BaseModel):
    normalized: dict[str, Any]
    new_icds: list[Diagnosis]


# ── chat ────────────────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    user_message: str
    note_text: str = ""
    evidence: dict[str, Any] = {}
    cpt_items: list[CodeItem] = []
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    response: str
    history: list[ChatMessage]


# ── ingest (RAG corpus) ─────────────────────────────────────────────────────
class IngestRequest(BaseModel):
    note_text: str


class IngestResponse(BaseModel):
    collection: str
    status: Literal["queued", "indexed", "unavailable"] = "queued"


# ── finalize / CMS-1500 ─────────────────────────────────────────────────────
class FinalizeRequest(BaseModel):
    patient_name: str = ""
    dob: str = ""
    date_of_service: str
    diagnoses: list[Diagnosis]
    items: list[CodeItem]


class FinalizeResponse(BaseModel):
    encounter_id: str
    cms1500_text: str


# ── CPT definitions ─────────────────────────────────────────────────────────
class CPTDefinition(BaseModel):
    label: str = ""
    timed: bool = False
    description: str = ""
    typical_indication: str = ""
    model_config = {"extra": "allow"}
