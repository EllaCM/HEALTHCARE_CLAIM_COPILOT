"""Dependency injection for routers.

Anthropic API key is per-request: extracted from the `Authorization: Bearer
<key>` header. We hand the existing `scripts/*` functions an env-var
because that is how their internal `_get_client()` reads the key. Using a
short-lived `os.environ` mutation inside a context-managed dependency
keeps the change isolated to one boundary; concurrent requests with
different keys are serialized — fine for clinic-scale traffic, revisit if
we ever multiplex multiple keys per process.
"""

import contextlib
import os
import threading
from typing import Iterator

from fastapi import Depends, Header, Request

from src.api.errors import missing_anthropic_key
from src.api.repositories import EncounterRepo
from src.api.settings import Settings


_env_lock = threading.Lock()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_cpt_adapter(request: Request):
    return request.app.state.cpt_adapter


def get_encounter_repo() -> EncounterRepo:
    return EncounterRepo()


@contextlib.contextmanager
def _anthropic_key_in_env(key: str) -> Iterator[None]:
    with _env_lock:
        prev = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = key
        try:
            yield
        finally:
            if prev is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = prev


def anthropic_key_scope(
    settings: Settings = Depends(get_settings),
    authorization: str | None = Header(default=None),
) -> Iterator[None]:
    """Yield a request scope where ANTHROPIC_API_KEY is set in env.

    Header takes precedence over server-side env. Raises if neither is
    available and auth is required.
    """
    header_key = None
    if authorization and authorization.lower().startswith("bearer "):
        header_key = authorization.split(" ", 1)[1].strip() or None

    effective = header_key or settings.server_anthropic_key
    if not effective:
        if settings.require_auth_header:
            raise missing_anthropic_key()
        yield
        return

    with _anthropic_key_in_env(effective):
        yield
