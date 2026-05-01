"""Adapter for CPT code definitions. Today: local YAML. Future: authoritative API."""

import pathlib
from typing import Any

import yaml

_DEFAULT_YAML = pathlib.Path(__file__).parent.parent / "data" / "cpt_definitions" / "pt_cpt_codes.yaml"

_STUB = {
    "label": "",
    "timed": True,
    "description": "No definition available for this code.",
    "typical_indication": "No indication information available.",
}


class CPTDefinitionsAdapter:
    """Stable interface for CPT code definitions.

    Swap in an API-backed subclass when the authoritative license is acquired —
    callers reference only get_definition() and get_all_codes().
    """

    def __init__(self, yaml_path: str | pathlib.Path | None = None) -> None:
        self._yaml_path = pathlib.Path(yaml_path) if yaml_path else _DEFAULT_YAML
        self._data: dict[str, dict] | None = None

    def _load(self) -> None:
        if self._data is None:
            with open(self._yaml_path) as f:
                raw = yaml.safe_load(f)
            # YAML keys may be ints if unquoted — normalize to str
            self._data = {str(k): v for k, v in (raw or {}).items()}

    def get_definition(self, cpt_code: str) -> dict[str, Any]:
        """Return definition dict with keys: label, timed, description, typical_indication.

        Never raises — returns a stub dict for unknown codes.
        """
        self._load()
        code = str(cpt_code).strip()
        return dict(self._data.get(code, {**_STUB, "label": f"CPT {code}"}))

    def get_all_codes(self) -> dict[str, dict[str, Any]]:
        """Return the full code table keyed by CPT code string."""
        self._load()
        return dict(self._data)
