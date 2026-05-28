"""Runtime configuration — env-driven, no secrets baked in."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    cors_origins: tuple[str, ...]
    require_auth_header: bool
    server_anthropic_key: str | None
    voyage_api_key: str | None
    outputs_dir: str
    cpt_definitions_path: str | None
    chat_history_persisted: bool


def load_settings() -> Settings:
    origins = os.environ.get("CLAIM_COPILOT_CORS", "*").split(",")
    return Settings(
        cors_origins=tuple(o.strip() for o in origins if o.strip()),
        require_auth_header=os.environ.get("CLAIM_COPILOT_REQUIRE_AUTH", "true").lower() == "true",
        server_anthropic_key=os.environ.get("ANTHROPIC_API_KEY"),
        voyage_api_key=os.environ.get("VOYAGE_API_KEY"),
        outputs_dir=os.environ.get("CLAIM_COPILOT_OUTPUTS_DIR", "outputs"),
        cpt_definitions_path=os.environ.get("CPT_DEFINITIONS_PATH"),
        chat_history_persisted=os.environ.get("CLAIM_COPILOT_PERSIST_CHAT", "false").lower() == "true",
    )
