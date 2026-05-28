"""Filesystem-backed repository for encounter records.

Wraps `src/storage.py` with typed CRUD. All state lives under
`outputs/{encounter_id}/`. Each logical record is one JSON file:

    encounter_package.json   — full package (from scripts.encounter_builders.build_minimal_package)
    evidence.json            — extract_evidence output
    ranked_codes.json        — rank_codes output
    gaps.json                — detect_gaps output
    code_items.json          — UI-shaped CPT items (the editable list)
    diagnoses.json           — ordered ICD-10 diagnosis list
    chat.json                — chat history (if CLAIM_COPILOT_PERSIST_CHAT=true)
    cms1500.txt              — final formatted claim document
    pipeline_log.json        — append-only audit log

Swap this module for a SQLite-backed implementation later; routers depend
only on the public interface defined here.
"""

from typing import Any

from src import storage
from src.api.errors import encounter_not_found


class EncounterRepo:
    def __init__(self) -> None:
        # `src/storage.py` currently hard-codes the outputs/ directory.
        # If we add a CLAIM_COPILOT_OUTPUTS_DIR-aware variant, accept it here.
        pass

    # ── core record ──────────────────────────────────────────────────────────
    def create_package(self, encounter_id: str, package: dict[str, Any]) -> dict[str, Any]:
        storage.save_json(encounter_id, "encounter_package.json", package)
        storage.append_log(encounter_id, {"step": "create_package", "status": "ok"})
        return package

    def get_package(self, encounter_id: str) -> dict[str, Any]:
        try:
            return storage.load_json(encounter_id, "encounter_package.json")
        except FileNotFoundError:
            raise encounter_not_found(encounter_id)

    def patch_package(self, encounter_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        pkg = self.get_package(encounter_id)
        pkg.update(patch)
        storage.save_json(encounter_id, "encounter_package.json", pkg)
        return pkg

    # ── derived artifacts ────────────────────────────────────────────────────
    def save_evidence(self, encounter_id: str, evidence: dict[str, Any]) -> None:
        storage.save_json(encounter_id, "evidence.json", evidence)

    def get_evidence(self, encounter_id: str) -> dict[str, Any]:
        try:
            return storage.load_json(encounter_id, "evidence.json")
        except FileNotFoundError:
            raise encounter_not_found(encounter_id)

    def save_ranked_codes(self, encounter_id: str, ranked: list[dict[str, Any]]) -> None:
        storage.save_json(encounter_id, "ranked_codes.json", ranked)

    def save_gaps(self, encounter_id: str, gaps: dict[str, Any]) -> None:
        storage.save_json(encounter_id, "gaps.json", gaps)

    # ── editable lists ───────────────────────────────────────────────────────
    def get_diagnoses(self, encounter_id: str) -> list[dict[str, Any]]:
        try:
            return storage.load_json(encounter_id, "diagnoses.json")
        except FileNotFoundError:
            return []

    def put_diagnoses(self, encounter_id: str, diagnoses: list[dict[str, Any]]) -> None:
        storage.save_json(encounter_id, "diagnoses.json", diagnoses)

    def get_code_items(self, encounter_id: str) -> list[dict[str, Any]]:
        try:
            return storage.load_json(encounter_id, "code_items.json")
        except FileNotFoundError:
            return []

    def put_code_items(self, encounter_id: str, items: list[dict[str, Any]]) -> None:
        storage.save_json(encounter_id, "code_items.json", items)

    def soft_delete_code_item(self, encounter_id: str, item_id: str) -> list[dict[str, Any]]:
        items = self.get_code_items(encounter_id)
        for it in items:
            if it.get("id") == item_id:
                it["selected"] = False
                break
        self.put_code_items(encounter_id, items)
        return items

    # ── chat ─────────────────────────────────────────────────────────────────
    def get_chat_history(self, encounter_id: str) -> list[dict[str, str]]:
        try:
            return storage.load_json(encounter_id, "chat.json")
        except FileNotFoundError:
            return []

    def append_chat(self, encounter_id: str, role: str, content: str) -> None:
        history = self.get_chat_history(encounter_id)
        history.append({"role": role, "content": content})
        storage.save_json(encounter_id, "chat.json", history)

    # ── audit ────────────────────────────────────────────────────────────────
    def log(self, encounter_id: str, entry: dict[str, Any]) -> None:
        storage.append_log(encounter_id, entry)

    # ── listing (file-scan; revisit when moving to SQLite) ───────────────────
    def list_encounter_ids(self, limit: int = 50) -> list[str]:
        import os
        out_dir = "outputs"
        if not os.path.isdir(out_dir):
            return []
        names = sorted(
            (n for n in os.listdir(out_dir) if not n.startswith(".")),
            reverse=True,
        )
        return names[:limit]
