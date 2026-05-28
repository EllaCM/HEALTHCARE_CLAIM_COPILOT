"""Healthcare Claim Copilot — Streamlit UI."""

import json
import os
import pathlib
import sys
import uuid
from datetime import date, datetime, timezone

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import streamlit as st
from scripts.cpt_definitions_adapter import CPTDefinitionsAdapter
from scripts.billing_utils import compute_timed_units, compute_available_minutes, validate_minutes_allocation

st.set_page_config(page_title="Claim Copilot", page_icon="🏥", layout="wide")

_cpt_adapter = CPTDefinitionsAdapter()

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.cpt-card {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 1rem 1.25rem;
    margin-bottom: 1rem;
}
.cpt-card.warning { border-left: 4px solid #f59e0b; }
.cpt-card.ok      { border-left: 4px solid #10b981; }
.doc-ok   { color: #10b981; font-weight: 500; }
.doc-miss { color: #ef4444; font-weight: 500; }
.chat-user  { background:#dbeafe; padding:.5rem .75rem; border-radius:8px; margin:.25rem 0; }
.chat-agent { background:#f1f5f9; padding:.5rem .75rem; border-radius:8px; margin:.25rem 0; }
.stage-badge {
    display:inline-block; padding:.2rem .6rem; border-radius:999px;
    font-size:.75rem; font-weight:600; margin-bottom:.5rem;
}
.stage-upload { background:#e0f2fe; color:#0369a1; }
.stage-edit   { background:#dcfce7; color:#15803d; }
.stage-confirm{ background:#fef9c3; color:#854d0e; }

</style>
""", unsafe_allow_html=True)

# ── Session state ──────────────────────────────────────────────────────────────
_DEFAULTS = {
    "stage": "upload",           # upload | ready | edit | confirm
    "mode": "both",              # justification | codes | both
    "note_text": "",
    "encounter_id": f"enc-{uuid.uuid4().hex[:8]}",
    "patient_id": "patient-001",
    "clinician_id": "clinician-001",
    "patient_name": "",
    "dob": "",
    "evidence": None,
    "diagnoses": [],             # [{code, label, pointer}]
    "cpt_items": [],             # list of editable CPT dicts
    "deleted_ids": set(),        # set of item IDs removed by clinician
    "chat_history": [],          # [{role, content}]
    "processing_done": False,
    "extra_docs": {},            # {item_id+req: uploaded bytes}
    "session_duration_minutes": None,  # extracted from encounter note
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ── Helpers ────────────────────────────────────────────────────────────────────

def _api_key() -> str:
    return st.session_state.get("api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")


def _set_api_key(key: str) -> None:
    st.session_state["api_key"] = key
    os.environ["ANTHROPIC_API_KEY"] = key


def _pointer(idx: int) -> str:
    return chr(65 + idx)  # A, B, C ...


def _pointer_from_codes(icd_codes: list[str], diagnoses: list[dict]) -> str:
    pointers = []
    for icd in icd_codes:
        for i, d in enumerate(diagnoses):
            if d["code"] == icd:
                pointers.append(_pointer(i))
    return "".join(pointers) or "A"


def _severity_color(score: float) -> str:
    if score >= 0.8:
        return "#10b981"
    if score >= 0.5:
        return "#f59e0b"
    return "#ef4444"


from scripts.encounter_builders import (
    build_minimal_package as _build_minimal_package_impl,
    make_cpt_item as _make_cpt_item,
    is_clinical_doc as _is_clinical_doc,
)


def _build_minimal_package(note_text: str) -> dict:
    return _build_minimal_package_impl(
        note_text=note_text,
        encounter_id=st.session_state.encounter_id,
        clinician_id=st.session_state.clinician_id,
        patient_id=st.session_state.patient_id,
    )


def _active_items() -> list[dict]:
    return [
        item for item in st.session_state.cpt_items
        if item["id"] not in st.session_state.deleted_ids and item.get("selected", True)
    ]


def _read_widget_edits() -> None:
    """Sync text/number widget values back into cpt_items before saving."""
    for item in st.session_state.cpt_items:
        iid = item["id"]
        for field, key in [
            ("code", f"w_code_{iid}"),
            ("modifier", f"w_mod_{iid}"),
            ("dx_pointer", f"w_dx_{iid}"),
            ("justification", f"w_just_{iid}"),
        ]:
            if key in st.session_state:
                item[field] = st.session_state[key]
        if f"w_minutes_{iid}" in st.session_state:
            item["minutes"] = int(st.session_state[f"w_minutes_{iid}"] or 0)
        defn = _cpt_adapter.get_definition(item.get("code", "")) if item.get("code") else {}
        is_timed = defn.get("timed", False)
        if is_timed and item.get("minutes", 0) > 0:
            item["units"] = compute_timed_units(item["minutes"])
        elif not is_timed:
            item["units"] = 1


def _generate_output_doc() -> str:
    from scripts.claim_builder import build_cms1500_text
    _read_widget_edits()
    return build_cms1500_text(
        encounter_id=st.session_state.encounter_id,
        date_of_service=date.today().isoformat(),
        patient_name=st.session_state.patient_name,
        dob=st.session_state.dob,
        patient_id=st.session_state.patient_id,
        clinician_id=st.session_state.clinician_id,
        diagnoses=st.session_state.diagnoses,
        items=_active_items(),
    )


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏥 Claim Copilot")

    stage = st.session_state.stage
    badge_class = {"upload": "stage-upload", "ready": "stage-upload",
                   "edit": "stage-edit", "confirm": "stage-confirm"}.get(stage, "stage-upload")
    stage_label = {"upload": "Upload", "ready": "Ready", "edit": "Editing", "confirm": "Review"}.get(stage, stage)
    st.markdown(f'<span class="stage-badge {badge_class}">{stage_label}</span>', unsafe_allow_html=True)

    st.divider()
    api_key_input = st.text_input(
        "Anthropic API Key",
        value=st.session_state.get("api_key", os.environ.get("ANTHROPIC_API_KEY", "")),
        type="password",
        help="Loaded from .env automatically if present.",
    )
    if api_key_input:
        _set_api_key(api_key_input)

    st.divider()
    st.markdown("#### Encounter Details")
    st.session_state.patient_name = st.text_input("Patient Name", value=st.session_state.patient_name)
    st.session_state.dob = st.text_input("Date of Birth", value=st.session_state.dob, placeholder="YYYY-MM-DD")
    st.session_state.patient_id = st.text_input("Patient ID", value=st.session_state.patient_id)
    st.session_state.clinician_id = st.text_input("Clinician", value=st.session_state.clinician_id)

    if stage in ("edit", "confirm"):
        st.divider()
        st.markdown("#### Diagnoses (ICD-10)")
        diagnoses = st.session_state.diagnoses
        for i, dx in enumerate(diagnoses):
            c1, c2 = st.columns([1, 3])
            dx["code"] = c1.text_input("ICD Code", value=dx["code"], key=f"dx_code_{i}", label_visibility="collapsed")
            dx["label"] = c2.text_input("Description", value=dx.get("label", ""), key=f"dx_label_{i}", label_visibility="collapsed")
        if st.button("＋ Add Diagnosis"):
            diagnoses.append({"code": "", "label": "", "pointer": _pointer(len(diagnoses))})
            st.rerun()

    if stage != "upload":
        st.divider()
        if st.button("↩ Start Over", use_container_width=True):
            for k, v in _DEFAULTS.items():
                st.session_state[k] = v
            st.session_state.encounter_id = f"enc-{uuid.uuid4().hex[:8]}"
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# STAGE: UPLOAD
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.stage == "upload":
    st.title("Healthcare Claim Copilot")
    st.caption("Upload a treatment note and let the AI help you prepare a CMS-1500-ready claim.")
    st.divider()

    tab_up, tab_paste = st.tabs(["📎 Upload file", "✏️ Paste text"])
    note_from_upload = ""
    note_from_paste = ""

    with tab_up:
        f = st.file_uploader("Upload plain-text treatment note (.txt)", type=["txt"])
        if f:
            note_from_upload = f.read().decode("utf-8")
            st.success(f"Loaded: {f.name} ({len(note_from_upload)} chars)")

    with tab_paste:
        sample = pathlib.Path("tests/fixtures/sample_encounter_note.txt")
        placeholder = sample.read_text() if sample.exists() else "Paste encounter note here..."
        note_from_paste = st.text_area("Encounter note", height=280, placeholder=placeholder[:300] + "...")

    note_text = note_from_upload or note_from_paste

    st.divider()
    col_btn, col_warn = st.columns([1, 3])
    with col_btn:
        screen_clicked = st.button("🔍 Screen Note", type="primary", disabled=not note_text.strip())
    with col_warn:
        if not _api_key():
            st.warning("Set your API key in the sidebar first.")
        elif not note_text.strip():
            st.info("Upload or paste a note to begin.")

    if screen_clicked and note_text.strip():
        with st.spinner("Screening your note — extracting evidence..."):
            from scripts.extract_evidence import extract_evidence
            try:
                ev = extract_evidence(note_text, encounter_id=st.session_state.encounter_id)
                st.session_state.evidence = ev
                st.session_state.session_duration_minutes = ev.get("session_duration_minutes")

                # Seed diagnosis list — will be refined by rank_codes output in edit stage
                cond = ev.get("patient_condition", "")
                seeds = ev.get("seed_icd_codes") or []
                icd_seed = seeds[0] if seeds else "See note"
                st.session_state.diagnoses = [
                    {"code": icd_seed, "label": cond[:80] if cond else "", "pointer": "A"}
                ]

                st.session_state.note_text = note_text
                st.session_state.stage = "ready"
                st.rerun()
            except Exception as e:
                st.error(f"Screening failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# STAGE: READY (mode selection)
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.stage == "ready":
    ev = st.session_state.evidence or {}
    st.title("Ready to file your claim")

    col_l, col_r = st.columns([3, 2])
    with col_l:
        st.success("✅ Your note has been screened. Here's what we found:")
        if ev.get("patient_condition"):
            st.markdown(f"**Patient condition:** {ev['patient_condition']}")
        if ev.get("functional_limitation"):
            st.markdown(f"**Functional limitation:** {ev['functional_limitation']}")
        treatments = ev.get("treatment_provided", [])
        if treatments:
            st.markdown(f"**Treatments detected ({len(treatments)}):**")
            for t in treatments:
                st.markdown(f"  - {t}")
        missing = ev.get("missing_information", [])
        if missing:
            st.warning(f"**{len(missing)} potential documentation gap(s):** " + "; ".join(missing[:3]))

    with col_r:
        st.markdown("#### Select a mode to continue")
        mode = st.radio(
            "How would you like the AI to help?",
            options=["both", "codes", "justification"],
            format_func=lambda x: {
                "both": "📋 Propose CPT codes + justifications",
                "codes": "🏷️ Propose ranked CPT codes only",
                "justification": "✍️ Write justification text only",
            }[x],
            index=0,
        )
        st.session_state.mode = mode
        st.caption({
            "both": "AI ranks codes and writes a justification paragraph for each.",
            "codes": "AI ranks codes with modifiers and supporting docs. You write justifications.",
            "justification": "AI writes justification text for each treatment found. You confirm codes.",
        }[mode])

        if st.button("▶ Start", type="primary", use_container_width=True):
            st.session_state.stage = "edit"
            st.session_state.processing_done = False
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# STAGE: EDIT
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.stage == "edit":

    # ── First-time processing ────────────────────────────────────────────────
    if not st.session_state.processing_done:
        mode = st.session_state.mode
        progress = st.status("Generating coding recommendations...", expanded=True)
        try:
            with progress:
                from scripts.pipeline import run_initial_screening
                st.write(
                    "🏷️ Ranking codes & writing justifications (parallel with gap detection)..."
                    if mode in ("both", "justification")
                    else "🏷️ Ranking CPT codes (parallel with gap detection)..."
                )
                result = run_initial_screening(
                    mode=mode,
                    evidence=st.session_state.evidence,
                    diagnoses=st.session_state.diagnoses,
                )
                st.session_state.diagnoses = result["diagnoses"]
                st.session_state.cpt_items = result["items"]
                st.session_state.deleted_ids = set()
                st.session_state.processing_done = True
                progress.update(label="Ready — review and edit below", state="complete")

            st.rerun()
        except Exception as exc:
            progress.update(label="Processing failed", state="error")
            st.error(f"**Error during processing:** {exc}")
            if st.button("↩ Go back and try again"):
                st.session_state.stage = "ready"
                st.rerun()
            st.stop()

    # ── Layout: main (2/3) + chatbot (1/3) ──────────────────────────────────
    st.markdown(f"### Encounter `{st.session_state.encounter_id}` — Review & Edit")
    st.caption("Edit codes, modifiers, units, and justification text directly. Use the chatbot on the right for questions.")

    # Sticky chatbot column + billing header styles
    st.markdown("""
    <style>
    section[data-testid="stMain"]
        [data-testid="stHorizontalBlock"]:not(
            [data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"]
        ) {
        align-items: flex-start !important;
    }
    section[data-testid="stMain"]
        [data-testid="stHorizontalBlock"]:not(
            [data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"]
        ) > [data-testid="column"]:last-child {
        position: sticky !important;
        top: 3.75rem !important;
        align-self: flex-start !important;
        max-height: calc(100vh - 4.5rem);
        overflow-y: auto;
    }
    .billing-header {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 10px 20px;
        margin-bottom: 14px;
        display: flex;
        gap: 48px;
        align-items: center;
    }
    .bh-label { color: #94a3b8; font-size: 0.72rem; text-transform: uppercase; letter-spacing: .05em; }
    .bh-value { font-size: 1.1rem; font-weight: 700; color: #f1f5f9; }
    .bh-value.warn { color: #f97316; }
    </style>
    """, unsafe_allow_html=True)

    # Apply any widget value updates queued by the Generate handler in the previous run.
    # Must happen before any widget is instantiated — setting session_state after a widget
    # renders in the same run raises a Streamlit error.
    if "_pending_widget_updates" in st.session_state:
        for _k, _v in st.session_state.pop("_pending_widget_updates").items():
            st.session_state[_k] = _v

    # ── Billing header — full-width, above columns ────────────────────────────
    _read_widget_edits()
    total_min = st.session_state.session_duration_minutes
    used_min = sum(
        int(st.session_state.get(f"w_minutes_{item['id']}", item.get("minutes", 0)) or 0)
        for item in st.session_state.cpt_items
        if item.get("selected") and item["id"] not in st.session_state.deleted_ids
    )
    if total_min is not None:
        avail_min = total_min - used_min
        warn_cls = "warn" if avail_min < 0 else ""
        st.markdown(
            f'<div class="billing-header">'
            f'<div><div class="bh-label">Total Treatment Time</div>'
            f'<div class="bh-value">{total_min} min</div></div>'
            f'<div><div class="bh-label">Available Billable Time</div>'
            f'<div class="bh-value {warn_cls}">{avail_min} min</div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        warn_cls = "warn" if used_min > 0 else ""
        st.markdown(
            f'<div class="billing-header">'
            f'<div><div class="bh-label">Total Treatment Time</div>'
            f'<div class="bh-value" style="color:#94a3b8">Not detected</div></div>'
            f'<div><div class="bh-label">Time Allocated to Codes</div>'
            f'<div class="bh-value">{used_min} min</div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    col_main, col_chat = st.columns([2, 1], gap="large")

    # ── MAIN WINDOW ──────────────────────────────────────────────────────────
    with col_main:
        active = _active_items()

        if not active:
            st.info("No CPT codes selected. Add one below.")

        for item in active:
            iid = item["id"]
            score = item.get("supportability_score", 0)
            card_class = "ok" if score >= 0.7 else "warning"
            has_warn = bool(item.get("compliance_warning"))
            missing_docs = [d for d in item.get("supporting_docs", []) if not d.get("present")]

            # Card header
            score_color = _severity_color(score)
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:.75rem;margin-bottom:.25rem">'
                f'<span style="font-size:1.1rem;font-weight:700">{item["code"]}</span>'
                f'<span style="color:#64748b">{item["label"]}</span>'
                f'<span style="margin-left:auto;color:{score_color};font-weight:600">'
                f'Support: {score:.0%}</span></div>',
                unsafe_allow_html=True,
            )

            with st.expander("Edit details", expanded=True):
                # Code fields row: CPT | Modifier | Tx Min | Units(computed) | Dx Pointer | (gap) | Delete
                c1, c2, c3, c4, c5, c6, c7 = st.columns([2.2, 1.5, 1.3, 1.3, 1.5, 0.3, 0.6])
                c1.text_input("CPT Code", value=item["code"], key=f"w_code_{iid}")
                c2.text_input("Modifier", value=item["modifier"], key=f"w_mod_{iid}")

                # Resolve timed status using current widget value if available
                current_code_widget = st.session_state.get(f"w_code_{iid}", item["code"]).strip()
                item_defn = _cpt_adapter.get_definition(current_code_widget) if current_code_widget else {}
                item_is_timed = item_defn.get("timed", False)

                with c3:
                    if item_is_timed:
                        st.number_input(
                            "Tx Min",
                            min_value=0,
                            max_value=600,
                            value=item.get("minutes", 0),
                            step=1,
                            key=f"w_minutes_{iid}",
                            help="Documented treatment minutes for this code",
                        )
                    else:
                        st.caption("Untimed\n(1 unit)")

                with c4:
                    live_min = int(st.session_state.get(f"w_minutes_{iid}", item.get("minutes", 0)) or 0)
                    if item_is_timed and 0 < live_min < 8:
                        st.markdown(
                            '<span style="color:#ef4444;font-size:.9rem">0 units<br>(&lt;8 min)</span>',
                            unsafe_allow_html=True,
                        )
                    elif item_is_timed:
                        units_display = compute_timed_units(live_min) if live_min >= 8 else item.get("units", 1)
                        label = f"**{units_display}** unit{'s' if units_display != 1 else ''}"
                        st.markdown(label, help="Auto-calculated via 8-min rule")
                    else:
                        st.markdown("**1** unit", help="Untimed code — always 1 unit")

                c5.text_input("Dx Pointer", value=item["dx_pointer"], key=f"w_dx_{iid}")
                if c7.button("🗑", key=f"del_{iid}", help="Remove this code"):
                    st.session_state.deleted_ids.add(iid)
                    st.rerun()

                if has_warn:
                    st.warning(f"⚠️ {item['compliance_warning']}")

                # Justification
                st.text_area(
                    "Justification (clinician-reviewed)",
                    value=item.get("justification", ""),
                    height=140,
                    key=f"w_just_{iid}",
                    help="Edit freely. Ask the chatbot to rewrite or improve this text.",
                )

                # ── Generate button ───────────────────────────────────────────
                current_code = current_code_widget
                missing_minutes = item_is_timed and item.get("minutes", 0) == 0 and not item.get("justification")

                if not current_code:
                    st.info("Enter a CPT code above, then click Generate.")
                elif missing_minutes:
                    st.button(
                        "⚡ Generate",
                        key=f"gen_{iid}",
                        disabled=True,
                        help="Enter treatment minutes (Tx Min) before generating justification",
                    )
                    st.caption("Enter treatment minutes (Tx Min) for this timed code first.")
                else:
                    if st.button("⚡ Generate", key=f"gen_{iid}",
                                 help="AI-generate justification, modifier, units, and dx pointer for this code"):
                        from scripts.rag_justification import (
                            evaluate_single_code as rag_evaluate_single_code,
                            normalize_evaluation_result,
                        )

                        try:
                            with st.spinner("Generating recommendation..."):
                                matched = rag_evaluate_single_code(
                                    st.session_state.evidence or {},
                                    current_code,
                                    label=item.get("label", ""),
                                    units=item.get("units") or None,
                                    minutes=item.get("minutes") or None,
                                    note_text=st.session_state.get("note_text") or None,
                                    patient_id=st.session_state.get("patient_id") or None,
                                    encounter_id=st.session_state.get("encounter_id") or None,
                                )

                            normalized, new_icds = normalize_evaluation_result(
                                matched,
                                current_code=current_code,
                                existing_item=item,
                                existing_diagnoses=st.session_state.diagnoses,
                            )
                            item.update(normalized)
                            st.session_state.diagnoses.extend(new_icds)

                            st.session_state["_pending_widget_updates"] = {
                                f"w_code_{iid}": item["code"],
                                f"w_mod_{iid}": item["modifier"],
                                f"w_dx_{iid}": item["dx_pointer"],
                                f"w_just_{iid}": item["justification"],
                            }
                            st.rerun()
                        except Exception as _gen_err:
                            st.error(f"Generation failed: {_gen_err}")

                # Show auto-fill notes (if any) as compact info
                for note in item.get("auto_fill_notes", []):
                    st.info(f"ℹ️ {note}")

                # Supporting docs checklist (clinical items only — no admin/billing requirements)
                st.markdown("**Supporting Documentation**")
                docs = [d for d in item.get("supporting_docs", [])
                        if _is_clinical_doc(d.get("requirement", ""))]
                if docs:
                    for di, doc in enumerate(docs):
                        doc_key = f"upload_{iid}_{di}"
                        if doc.get("present"):
                            note_str = f" — *{doc['note']}*" if doc.get("note") else ""
                            st.markdown(f'<span class="doc-ok">✅ {doc["requirement"]}{note_str}</span>', unsafe_allow_html=True)
                        else:
                            dc1, dc2 = st.columns([3, 2])
                            dc1.markdown(f'<span class="doc-miss">❌ {doc["requirement"]}</span>', unsafe_allow_html=True)
                            uploaded = dc2.file_uploader(
                                "Upload supporting doc",
                                key=doc_key,
                                label_visibility="collapsed",
                            )
                            if uploaded:
                                st.session_state.extra_docs[doc_key] = uploaded.read()
                                doc["present"] = True
                                doc["note"] = f"Uploaded: {uploaded.name}"
                                st.rerun()
                else:
                    st.caption("No supporting docs checklist available for this code.")

            st.markdown("---")

        # Add CPT code button
        if st.button("＋ Add CPT Code"):
            new_item = _make_cpt_item(
                {"code": "", "label": "New code", "modifier": "GP", "units": 1,
                 "supportability_score": 0, "supporting_docs": [], "missing_elements": []},
                len(st.session_state.cpt_items),
                st.session_state.diagnoses,
            )
            st.session_state.cpt_items.append(new_item)
            st.rerun()

        st.divider()
        all_reviewed = all(
            st.session_state[f"w_just_{item['id']}"].strip()
            for item in active
            if f"w_just_{item['id']}" in st.session_state
        )
        confirm_disabled = len(active) == 0
        if st.button("✅ Review & Confirm Claim", type="primary", disabled=confirm_disabled, use_container_width=True):
            _read_widget_edits()
            st.session_state.stage = "confirm"
            st.rerun()

    # ── CHATBOT ──────────────────────────────────────────────────────────────
    with col_chat:
        st.markdown("#### 💬 Ask the Copilot")
        st.caption("Ask about codes, challenge a justification, or request a rewrite.")

        chat_container = st.container(height=420)
        with chat_container:
            if not st.session_state.chat_history:
                st.markdown('<div class="chat-agent">👋 I\'ve reviewed your note. Ask me anything about the codes or justifications.</div>', unsafe_allow_html=True)
            for msg in st.session_state.chat_history:
                css = "chat-user" if msg["role"] == "user" else "chat-agent"
                prefix = "You" if msg["role"] == "user" else "Copilot"
                st.markdown(f'<div class="{css}"><strong>{prefix}:</strong> {msg["content"]}</div>', unsafe_allow_html=True)

        with st.form("chat_form", clear_on_submit=True):
            user_input = st.text_area("Your question", height=80, label_visibility="collapsed",
                                      placeholder="e.g. Can I bill 97140 and 97110 together? Or: Rewrite the justification for 97110.")
            submitted = st.form_submit_button("Send →", use_container_width=True)

        if submitted and user_input.strip():
            _read_widget_edits()
            from scripts.chatbot import chat as agent_chat
            try:
                with st.spinner("Thinking..."):
                    response = agent_chat(
                        user_message=user_input,
                        note_text=st.session_state.note_text,
                        evidence=st.session_state.evidence or {},
                        cpt_items=_active_items(),
                        chat_history=st.session_state.chat_history,
                    )
                st.session_state.chat_history.append({"role": "user", "content": user_input})
                st.session_state.chat_history.append({"role": "assistant", "content": response})
            except Exception as _chat_err:
                st.session_state.chat_history.append({"role": "user", "content": user_input})
                st.session_state.chat_history.append({"role": "assistant", "content": f"⚠️ Error: {_chat_err}"})
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# STAGE: CONFIRM
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.stage == "confirm":
    _read_widget_edits()
    active = _active_items()
    diagnoses = st.session_state.diagnoses

    st.title("Claim Review")
    st.caption("Final check before download. Go back to make edits.")

    col_back, col_dl = st.columns([1, 2])
    with col_back:
        if st.button("← Back to Edit"):
            st.session_state.stage = "edit"
            st.rerun()

    # Summary table
    st.markdown("#### Procedure Lines")
    for ln, item in enumerate(active, 1):
        missing_docs = [d for d in item.get("supporting_docs", []) if not d.get("present")]
        warn = item.get("compliance_warning")
        with st.expander(f"Line {ln}: {item['code']} — {item['label']}", expanded=True):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("CPT", item["code"])
            c2.metric("Modifier", item["modifier"])
            c3.metric("Units", item["units"])
            c4.metric("Dx Pointer", item["dx_pointer"])

            if item.get("justification"):
                st.markdown(f"**Justification:** {item['justification']}")
            else:
                st.warning("No justification text — go back and add one.")

            if warn:
                st.warning(f"⚠️ {warn}")

            if missing_docs:
                st.error(f"❌ {len(missing_docs)} missing documentation item(s):")
                for d in missing_docs:
                    st.markdown(f"  - {d['requirement']}")

    # Diagnoses
    st.markdown("#### Diagnoses (Box 21)")
    for i, dx in enumerate(diagnoses):
        st.markdown(f"**{_pointer(i)}.** `{dx['code']}` — {dx.get('label', '')}")

    # Download
    st.divider()
    output_doc = _generate_output_doc()

    # Save to outputs dir
    from src import storage
    storage.save_json(
        st.session_state.encounter_id,
        "claim_package.json",
        {
            "encounter_id": st.session_state.encounter_id,
            "diagnoses": diagnoses,
            "cpt_lines": [
                {k: v for k, v in item.items() if k not in ("id", "supporting_docs")}
                for item in active
            ],
        }
    )

    st.download_button(
        "⬇️ Download CMS-1500 Claim Support Package (.txt)",
        data=output_doc,
        file_name=f"claim_{st.session_state.encounter_id}.txt",
        mime="text/plain",
        type="primary",
        use_container_width=True,
    )

    with st.expander("Preview document"):
        st.code(output_doc, language=None)
