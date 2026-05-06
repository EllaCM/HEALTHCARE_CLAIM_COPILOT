"""Billing math utilities for CMS-1500 timed-code unit calculations."""


def _eight_minute_rule(minutes: int) -> int:
    """Return max billable units for a timed code given documented service minutes.

    CMS federal rule: 8-22 min = 1, 23-37 min = 2, 38-52 min = 3, 53-67 min = 4, ...
    # EXTENSION POINT: state-specific overrides can replace this function.
    """
    if minutes < 8:
        return 0
    return (minutes - 8) // 15 + 1


def compute_timed_units(minutes: int) -> int:
    """Units for a timed CPT code given documented service minutes (8-minute rule)."""
    return _eight_minute_rule(minutes)


def compute_available_minutes(
    total_minutes: int,
    cpt_items: list[dict],
    exclude_id: str | None = None,
) -> int:
    """Return total_minutes minus minutes already allocated to timed CPT items.

    exclude_id: skip this item's minutes (used when validating the item being edited).
    Untimed codes (97010, 97012, etc.) are excluded — they don't consume timed minutes.
    # EXTENSION POINT: state-specific billing rules go here; currently CMS federal only.
    """
    from scripts.cpt_definitions_adapter import CPTDefinitionsAdapter
    adapter = CPTDefinitionsAdapter()
    used = 0
    for item in cpt_items:
        if not item.get("selected") or item.get("id") == exclude_id:
            continue
        if adapter.get_definition(item.get("code", "")).get("timed", False):
            used += item.get("minutes", 0) or 0
    return total_minutes - used


def validate_minutes_allocation(minutes: int, available: int) -> str | None:
    """Return a warning string when minutes exceeds available, else None."""
    if minutes > available:
        return (
            f"Minutes entered ({minutes}) exceed available billable "
            f"minutes ({available}). Justification cleared."
        )
    return None
