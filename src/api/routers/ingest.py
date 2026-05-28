"""RAG corpus ingest — Chroma + Voyage embedding via a background task.

Returns 202 immediately; the embedding write happens out-of-band so the
client doesn't wait on Voyage latency. Production: replace `BackgroundTasks`
with a real queue (Cloud Tasks / SQS).
"""

from fastapi import APIRouter, BackgroundTasks

from scripts.ingest_patient_docs import ingest_encounter
from src.api.models import IngestRequest, IngestResponse

router = APIRouter(prefix="/patients/{patient_id}/encounters/{encounter_id}", tags=["ingest"])


def _do_ingest(patient_id: str, encounter_id: str, note_text: str) -> None:
    try:
        ingest_encounter(patient_id, encounter_id, note_text)
    except Exception:
        # Background failures should surface via /health or an audit endpoint;
        # not via the original request (which has already returned 202).
        pass


@router.post("/ingest", response_model=IngestResponse, status_code=202)
def ingest(
    patient_id: str,
    encounter_id: str,
    body: IngestRequest,
    background: BackgroundTasks,
) -> IngestResponse:
    background.add_task(_do_ingest, patient_id, encounter_id, body.note_text)
    return IngestResponse(
        collection=f"patient-{patient_id}-encounter-{encounter_id}",
        status="queued",
    )
