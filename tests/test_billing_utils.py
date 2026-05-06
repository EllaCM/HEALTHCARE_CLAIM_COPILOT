"""Tests for scripts/billing_utils.py — billing math utilities."""
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from scripts.billing_utils import (
    compute_timed_units,
    compute_available_minutes,
    validate_minutes_allocation,
)


# ── compute_timed_units ───────────────────────────────────────────────────────

def test_compute_timed_units_delegates_to_eight_minute_rule():
    """Delegates correctly — 23 minutes maps to 2 units."""
    assert compute_timed_units(23) == 2


def test_compute_timed_units_below_8_returns_zero():
    assert compute_timed_units(7) == 0


def test_compute_timed_units_boundary_8():
    assert compute_timed_units(8) == 1


def test_compute_timed_units_boundary_22_to_23():
    assert compute_timed_units(22) == 1
    assert compute_timed_units(23) == 2


def test_compute_timed_units_higher_range():
    assert compute_timed_units(38) == 3
    assert compute_timed_units(53) == 4


# ── compute_available_minutes ─────────────────────────────────────────────────

def _timed_item(iid: str, minutes: int, selected: bool = True) -> dict:
    return {"id": iid, "code": "97110", "selected": selected, "minutes": minutes}


def _untimed_item(iid: str, minutes: int, selected: bool = True) -> dict:
    return {"id": iid, "code": "97010", "selected": selected, "minutes": minutes}


def test_compute_available_basic():
    items = [_timed_item("a", 20), _timed_item("b", 15)]
    assert compute_available_minutes(60, items) == 25


def test_compute_available_single_item():
    items = [_timed_item("a", 30)]
    assert compute_available_minutes(45, items) == 15


def test_compute_available_exclude_id_skips_that_item():
    items = [_timed_item("a", 20), _timed_item("b", 15)]
    # Excluding "b" means only "a"'s 20 min counts against 60
    assert compute_available_minutes(60, items, exclude_id="b") == 40


def test_compute_available_missing_minutes_key_treated_as_zero():
    items = [{"id": "a", "code": "97110", "selected": True}]  # no "minutes" key
    assert compute_available_minutes(60, items) == 60


def test_compute_available_unselected_items_ignored():
    items = [_timed_item("a", 20), _timed_item("b", 15, selected=False)]
    assert compute_available_minutes(60, items) == 40


def test_compute_available_untimed_codes_excluded():
    """Untimed codes (97010) must NOT consume timed billable minutes."""
    items = [_timed_item("a", 20), _untimed_item("b", 30)]
    assert compute_available_minutes(60, items) == 40


def test_compute_available_empty_list():
    assert compute_available_minutes(60, []) == 60


def test_compute_available_can_go_negative():
    items = [_timed_item("a", 70)]
    assert compute_available_minutes(60, items) == -10


# ── validate_minutes_allocation ───────────────────────────────────────────────

def test_validate_minutes_ok_returns_none():
    assert validate_minutes_allocation(20, 30) is None


def test_validate_minutes_exact_boundary_returns_none():
    assert validate_minutes_allocation(30, 30) is None


def test_validate_minutes_over_returns_warning_string():
    result = validate_minutes_allocation(31, 30)
    assert result is not None
    assert "31" in result
    assert "30" in result


def test_validate_minutes_zero_ok():
    assert validate_minutes_allocation(0, 30) is None


def test_validate_minutes_warning_contains_both_values():
    result = validate_minutes_allocation(45, 20)
    assert result is not None
    assert "45" in result
    assert "20" in result
