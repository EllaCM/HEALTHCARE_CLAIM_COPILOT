"""Local JSON file storage for encounter packages and per-agent outputs."""

import json
import pathlib
from datetime import datetime, timezone
from typing import Any

OUTPUTS_DIR = pathlib.Path(__file__).parent.parent / "outputs"


def _encounter_dir(encounter_id: str) -> pathlib.Path:
    d = OUTPUTS_DIR / encounter_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_json(encounter_id: str, filename: str, data: Any) -> pathlib.Path:
    path = _encounter_dir(encounter_id) / filename
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def load_json(encounter_id: str, filename: str) -> Any:
    path = _encounter_dir(encounter_id) / filename
    with open(path) as f:
        return json.load(f)


def append_log(encounter_id: str, entry: dict[str, Any]) -> None:
    log_path = _encounter_dir(encounter_id) / "pipeline_log.json"
    log: list[dict] = []
    if log_path.exists():
        with open(log_path) as f:
            log = json.load(f)
    entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    log.append(entry)
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2)
