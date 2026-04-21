"""Validate an encounter package dict against the canonical JSON schema."""

import json
import pathlib
from typing import Any

import jsonschema

SCHEMA_PATH = pathlib.Path(__file__).parent.parent / "schemas" / "encounter_package.schema.json"


def load_schema() -> dict:
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def validate_payload(payload: dict[str, Any]) -> list[str]:
    """Return a list of validation error messages, empty on success."""
    schema = load_schema()
    validator = jsonschema.Draft7Validator(schema, format_checker=jsonschema.FormatChecker())
    return [e.message for e in sorted(validator.iter_errors(payload), key=str)]


def validate_or_raise(payload: dict[str, Any]) -> None:
    errors = validate_payload(payload)
    if errors:
        raise ValueError(f"Invalid encounter package ({len(errors)} error(s)):\n" + "\n".join(f"  - {e}" for e in errors))


if __name__ == "__main__":
    import sys
    with open(sys.argv[1]) as f:
        data = json.load(f)
    errors = validate_payload(data)
    if errors:
        print("INVALID:")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    print("OK")
