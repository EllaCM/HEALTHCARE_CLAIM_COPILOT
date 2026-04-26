"""Interactive chatbot for clinicians to ask coding and justification questions."""

import json
import os
from typing import Any

import anthropic

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


SYSTEM_PROMPT = """You are a clinical coding and reimbursement advisor embedded in a claim preparation tool for outpatient physical therapy.
A clinician is reviewing and editing CPT codes and justification text for a claim.

Your role:
- Answer questions about CPT codes, modifiers, documentation requirements, and billing rules.
- Help the clinician improve or rewrite justification text for specific codes.
- Challenge or defend coding choices when asked, always citing the documentation evidence.
- Flag compliance risks clearly and honestly.
- Be concise — clinicians are busy. Prefer bullet points for lists of requirements.

You must not:
- Invent clinical facts not in the encounter note.
- Recommend codes unsupported by the documentation.
- Ignore compliance issues to speed up the workflow.

When the clinician asks you to rewrite a justification, return only the new paragraph text — no preamble."""


def chat(
    user_message: str,
    note_text: str,
    evidence: dict[str, Any],
    cpt_items: list[dict[str, Any]],
    chat_history: list[dict[str, str]],
) -> str:
    """Return the agent's response given the current claim state and conversation history."""
    client = _get_client()

    # Build a concise claim state summary for context
    claim_summary = {
        "selected_cpt_codes": [
            {
                "code": item.get("code"),
                "label": item.get("label"),
                "modifier": item.get("modifier"),
                "units": item.get("units"),
                "dx_pointer": item.get("dx_pointer"),
                "justification_preview": (item.get("justification") or "")[:200],
                "missing_elements": item.get("missing_elements", []),
            }
            for item in cpt_items
            if item.get("selected", True)
        ]
    }

    context_block = f"""## Encounter Note (excerpt)
{note_text[:1500]}{"..." if len(note_text) > 1500 else ""}

## Extracted Evidence Summary
Patient condition: {evidence.get("patient_condition", "N/A")}
Functional limitation: {evidence.get("functional_limitation", "N/A")}
Treatment provided: {json.dumps(evidence.get("treatment_provided", []))}

## Current Claim State
{json.dumps(claim_summary, indent=2)}
"""

    messages = []
    # Inject context as the first user message if no history yet
    if not chat_history:
        messages.append({
            "role": "user",
            "content": f"[CLAIM CONTEXT — not a question, just context for you]\n{context_block}"
        })
        messages.append({
            "role": "assistant",
            "content": "Understood. I have reviewed the encounter note and current claim state. How can I help you?"
        })
    else:
        # Re-inject context as a system reminder in the first exchange
        messages.append({
            "role": "user",
            "content": f"[UPDATED CLAIM CONTEXT]\n{context_block}"
        })
        messages.append({
            "role": "assistant",
            "content": "Context updated."
        })
        for msg in chat_history:
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_message})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    return response.content[0].text.strip()
