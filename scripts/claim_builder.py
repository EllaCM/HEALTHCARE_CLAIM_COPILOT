"""CMS-1500 claim text formatter — pure function, no Streamlit dependency."""

from datetime import datetime


def _pointer(idx: int) -> str:
    return chr(65 + idx)


def build_cms1500_text(
    *,
    encounter_id: str,
    date_of_service: str,
    patient_name: str,
    dob: str,
    patient_id: str,
    clinician_id: str,
    diagnoses: list[dict],
    items: list[dict],
) -> str:
    lines = [
        "=" * 60,
        "  HEALTHCARE CLAIM SUPPORT PACKAGE",
        "  CMS-1500 Ready — Clinician Reviewed",
        "=" * 60,
        f"Encounter ID    : {encounter_id}",
        f"Date of Service : {date_of_service}",
        f"Patient         : {patient_name or patient_id}",
        f"Date of Birth   : {dob or 'N/A'}",
        f"Clinician       : {clinician_id}",
        "",
        "─" * 60,
        "BOX 21 — DIAGNOSIS CODES",
        "─" * 60,
    ]
    for i, dx in enumerate(diagnoses):
        lines.append(f"  {_pointer(i)}.  {dx['code']}  —  {dx.get('label', '')}")

    lines += ["", "─" * 60, "BOX 24 — SERVICE LINE ITEMS", "─" * 60]
    for ln, item in enumerate(items, 1):
        lines += [
            f"\nLine {ln}",
            f"  24D. CPT Code : {item['code']}    Modifier : {item['modifier']}",
            f"  24E. Dx Ptr   : {item['dx_pointer']}",
            f"  24G. Units    : {item['units']}",
            f"  Desc          : {item['label']}",
            "",
            "  Justification:",
        ]
        for para in (item.get("justification") or "").split("\n"):
            lines.append(f"    {para}")

        present = [d for d in item.get("supporting_docs", []) if d.get("present")]
        missing = [d for d in item.get("supporting_docs", []) if not d.get("present")]
        if present or missing:
            lines.append("\n  Supporting Documentation:")
            for d in present:
                lines.append(f"    ✅  {d['requirement']}")
            for d in missing:
                lines.append(f"    ❌  {d['requirement']} — MISSING")

        if item.get("compliance_warning"):
            lines.append(f"\n  ⚠  COMPLIANCE: {item['compliance_warning']}")
        lines.append("")

    lines += [
        "─" * 60,
        "COMPLIANCE SUMMARY",
        "─" * 60,
    ]
    warnings = [item.get("compliance_warning") for item in items if item.get("compliance_warning")]
    if warnings:
        for w in warnings:
            lines.append(f"  ⚠  {w}")
    else:
        lines.append("  No compliance warnings.")

    lines += [
        "",
        "─" * 60,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Review required before submission.",
        "=" * 60,
    ]
    return "\n".join(lines)
