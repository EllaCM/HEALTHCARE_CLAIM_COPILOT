"""Interactive-request screening pipeline.

Parallelizes rank-codes + detect-gaps as a single composite call for the
"first-time processing" path. Does NOT touch `src/storage.py` — that side
effect belongs to `src/orchestrator.py`'s batch CLI path. This module is
safe to call from a UI callback or an HTTP request handler.
"""

import concurrent.futures
from typing import Any

from scripts.encounter_builders import make_cpt_item


def _merge_icd_codes(ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in ranked:
        for c in r.get("diagnosis_codes", []):
            if c not in seen:
                out.append({"code": c, "label": "", "pointer": chr(65 + len(out))})
                seen.add(c)
    return out


def run_initial_screening(
    *,
    mode: str,
    evidence: dict[str, Any],
    diagnoses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run ranking + gap detection in parallel and assemble CPT items.

    Returns {"ranked", "gaps", "items", "diagnoses"}. `diagnoses` will be
    the merged list (incorporating new ICDs from ranked output) if the
    ranked codes contribute any new ones, else the original input.

    Mode: "both" | "justification" → uses `rank_codes_with_justifications`
    so the justification text comes back in the same call. "codes" → uses
    `rank_codes` (no justifications).
    """
    from scripts.rank_codes import rank_codes_with_justifications, rank_codes
    from scripts.detect_gaps import detect_gaps

    def _run_gaps_no_codes() -> dict[str, Any]:
        return detect_gaps(evidence, [])

    if mode in ("both", "justification"):
        def _run_combined() -> list[dict[str, Any]]:
            return rank_codes_with_justifications(evidence)
        worker = _run_combined
    else:
        def _run_rank() -> list[dict[str, Any]]:
            return rank_codes(evidence)
        worker = _run_rank

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_rank = executor.submit(worker)
        f_gaps = executor.submit(_run_gaps_no_codes)
        ranked = f_rank.result()
        gaps = f_gaps.result()

    merged = _merge_icd_codes(ranked)
    effective_diagnoses = merged if merged else diagnoses

    items = [make_cpt_item(r, i, effective_diagnoses) for i, r in enumerate(ranked)]

    if mode in ("both", "justification"):
        for item, r in zip(items, ranked):
            if not item.get("justification"):
                item["justification"] = r.get("justification", "")

    return {
        "ranked": ranked,
        "gaps": gaps,
        "items": items,
        "diagnoses": effective_diagnoses,
    }
