"""Encounter-scoped chatbot.

Unary JSON for now — the underlying `scripts.chatbot.chat` is non-streaming.
When the scripts layer gains a streaming variant, swap this endpoint to
`StreamingResponse` using `src.api.streaming.sse_pack`.
"""

from fastapi import APIRouter, Depends

from scripts.chatbot import chat as agent_chat
from src.api.deps import anthropic_key_scope, get_encounter_repo, get_settings
from src.api.errors import upstream_llm_error
from src.api.models import ChatMessage, ChatRequest, ChatResponse
from src.api.repositories import EncounterRepo
from src.api.settings import Settings

router = APIRouter(prefix="/encounters/{encounter_id}", tags=["chat"])


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(anthropic_key_scope)])
def chat(
    encounter_id: str,
    body: ChatRequest,
    settings: Settings = Depends(get_settings),
    repo: EncounterRepo = Depends(get_encounter_repo),
) -> ChatResponse:
    history = (
        [ChatMessage(**m) for m in repo.get_chat_history(encounter_id)]
        if settings.chat_history_persisted
        else body.history
    )
    try:
        reply = agent_chat(
            user_message=body.user_message,
            note_text=body.note_text,
            evidence=body.evidence,
            cpt_items=[it.model_dump() for it in body.cpt_items],
            chat_history=[m.model_dump() for m in history],
        )
    except Exception as exc:
        raise upstream_llm_error(str(exc))

    updated = list(history) + [
        ChatMessage(role="user", content=body.user_message),
        ChatMessage(role="assistant", content=reply),
    ]

    if settings.chat_history_persisted:
        repo.append_chat(encounter_id, "user", body.user_message)
        repo.append_chat(encounter_id, "assistant", reply)

    return ChatResponse(response=reply, history=updated)
