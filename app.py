"""Streamlit UI for the Healthcare Claim Copilot pipeline."""

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

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Healthcare Claim Copilot",
    page_icon="🏥",
    layout="wide",
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_package(note_text: str, encounter_id: str, clinician_id: str, patient_id: str) -> dict:
    doc_id = f"doc-{encounter_id}"
    return {
        "encounter_id": encounter_id,
        "date_of_service": date.today().isoformat(),
        "patient_id": patient_id,
        "clinician_id": clinician_id,
        "source_documents": {
            "uploaded_treatment_note": {
                "document_id": doc_id,
                "file_name": "encounter_note.txt",
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "parsed_text": note_text,
            },
            "backend_document_ids": [],
        },
        "suggested_treatments": [],
        "chat_session": {
            "session_id": f"session-{encounter_id}",
            "interaction_mode": "justification_help",
            "messages": [],
            "activity_log": [],
        },
        "final_output_document": {
            "document_id": f"output-{encounter_id}",
            "sections": [],
            "all_required_fields_complete": False,
        },
        "submission_state": {"status": "draft"},
    }


def _severity_badge(severity: str) -> str:
    colors = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    return colors.get(severity, "⚪")


def _quality_badge(quality: str) -> str:
    badges = {"strong": "✅ Strong", "partial": "⚠️ Partial", "insufficient": "❌ Insufficient"}
    return badges.get(quality, quality)


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🏥 Claim Copilot")
    st.caption("Post-visit reimbursement assistant")
    st.divider()

    st.subheader("Encounter Details")
    encounter_id_input = st.text_input("Encounter ID", value=f"enc-{uuid.uuid4().hex[:8]}")
    clinician_id_input = st.text_input("Clinician ID", value="clinician-001")
    patient_id_input = st.text_input("Patient ID", value="patient-001")

    st.divider()
    api_key = st.text_input(
        "Anthropic API Key",
        value=os.environ.get("ANTHROPIC_API_KEY", ""),
        type="password",
        help="Loaded from .env automatically if present.",
    )
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key

    st.divider()
    st.caption("Outputs saved to `outputs/<encounter_id>/`")

# ── Main ───────────────────────────────────────────────────────────────────────
st.title("Healthcare Claim Copilot")
st.caption("Upload or paste an encounter note to generate a reimbursement justification draft.")

# Note input
tab_upload, tab_paste = st.tabs(["📎 Upload note", "✏️ Paste note"])

with tab_upload:
    uploaded_file = st.file_uploader("Upload a plain-text encounter note (.txt)", type=["txt"])
    note_from_upload = uploaded_file.read().decode("utf-8") if uploaded_file else ""

with tab_paste:
    sample_path = pathlib.Path(__file__).parent / "tests" / "fixtures" / "sample_encounter_note.txt"
    placeholder = sample_path.read_text() if sample_path.exists() else "Paste your encounter note here..."
    note_from_paste = st.text_area("Encounter note", height=300, placeholder=placeholder)

note_text = note_from_upload or note_from_paste

# Run button
st.divider()
col_btn, col_status = st.columns([1, 4])
with col_btn:
    run_clicked = st.button("▶ Run Pipeline", type="primary", disabled=not note_text.strip())
with col_status:
    if not note_text.strip():
        st.info("Upload or paste an encounter note to get started.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.warning("No API key set — add it in the sidebar or .env file.")

# ── Pipeline execution ─────────────────────────────────────────────────────────
if run_clicked and note_text.strip():
    # Import here so missing anthropic package shows a clear error
    from src.orchestrator import run_pipeline

    encounter_id = encounter_id_input.strip() or f"enc-{uuid.uuid4().hex[:8]}"
    package = _build_package(note_text, encounter_id, clinician_id_input, patient_id_input)

    st.divider()
    st.subheader(f"Pipeline run — `{encounter_id}`")

    result = None
    error = None

    with st.status("Running pipeline...", expanded=True) as status:
        try:
            st.write("✅ Validating encounter payload...")
            from scripts.validate_payload import validate_payload
            errors = validate_payload(package)
            if errors:
                st.error("Validation failed:\n" + "\n".join(f"- {e}" for e in errors))
                status.update(label="Pipeline failed — invalid payload", state="error")
                st.stop()

            st.write("🔍 Extracting encounter evidence...")
            from src.agents.encounter_evidence_agent import EncounterEvidenceAgent
            package = EncounterEvidenceAgent().run(package)

            st.write("🏷️ Ranking CPT/ICD code options...")
            from src.agents.code_supportability_agent import CodeSupportabilityAgent
            package = CodeSupportabilityAgent().run(package)

            st.write("🔎 Detecting documentation gaps...")
            from src.agents.documentation_gap_agent import DocumentationGapAgent
            package = DocumentationGapAgent().run(package)

            if package.get("_blocked"):
                status.update(label="Pipeline blocked — major documentation gaps", state="error")
            else:
                st.write("✍️ Drafting justification...")
                from src.agents.justification_drafting_agent import JustificationDraftingAgent
                package = JustificationDraftingAgent().run(package)
                status.update(label="Pipeline complete", state="complete")

        except Exception as exc:
            error = exc
            status.update(label=f"Pipeline error: {exc}", state="error")

    if error:
        st.error(f"**Error:** {error}")
        st.stop()

    # Save outputs
    from src import storage
    storage.save_json(encounter_id, "encounter_package.json", {k: v for k, v in package.items() if not k.startswith("_")})
    for key, filename in [("_evidence", "evidence.json"), ("_ranked_codes", "ranked_codes.json"), ("_gap_analysis", "gaps.json"), ("_justification", "justification.json")]:
        if package.get(key):
            storage.save_json(encounter_id, filename, package[key])

    # ── Results ────────────────────────────────────────────────────────────────
    st.divider()

    # Warnings banner
    warnings = []
    if package.get("_evidence", {}).get("_low_confidence_warning"):
        warnings.append(package["_evidence"]["_low_confidence_warning"])
    if package.get("_escalation"):
        warnings.append(package["_escalation"]["message"])
    if package.get("_gap_analysis", {}).get("recommendation") == "warn":
        warnings.append(package["_gap_analysis"].get("summary", "Documentation gaps present."))
    for w in warnings:
        st.warning(w)

    # Blocked banner
    if package.get("_blocked"):
        blocked = package["_blocked"]
        st.error(f"**Blocked:** {blocked.get('message')}")
        high_gaps = [g for g in blocked.get("gaps", []) if g.get("severity") == "high"]
        if high_gaps:
            st.markdown("**Required actions before proceeding:**")
            for g in high_gaps:
                st.markdown(f"- 🔴 **{g['description']}** — {g['suggested_action']}")
        st.stop()

    # Result tabs
    tab_evidence, tab_codes, tab_gaps, tab_draft = st.tabs([
        "🔍 Evidence", "🏷️ Codes", "⚠️ Gaps", "✍️ Draft"
    ])

    # Evidence tab
    with tab_evidence:
        evidence = package.get("_evidence", {})
        if not evidence:
            st.info("No evidence extracted.")
        else:
            score = evidence.get("confidence_score")
            if score is not None:
                st.metric("Overall Confidence", f"{float(score):.0%}")

            sections = [
                ("Patient Condition", evidence.get("patient_condition")),
                ("Functional Limitation", evidence.get("functional_limitation")),
                ("Symptoms", evidence.get("symptoms")),
                ("Objective Findings", evidence.get("objective_findings")),
                ("Prior Treatment History", evidence.get("prior_treatment_history")),
                ("Treatment Provided", evidence.get("treatment_provided")),
                ("Medical Necessity Signals", evidence.get("medical_necessity_signals")),
                ("Missing Information", evidence.get("missing_information")),
            ]
            for label, value in sections:
                if value:
                    with st.expander(label, expanded=True):
                        if isinstance(value, list):
                            for item in value:
                                st.markdown(f"- {item}")
                        else:
                            st.markdown(value)

    # Codes tab
    with tab_codes:
        ranked = package.get("_ranked_codes", [])
        if not ranked:
            st.info("No codes ranked.")
        else:
            for code in ranked:
                score = code.get("supportability_score", 0)
                rank = code.get("rank", "?")
                label = f"#{rank} — **{code.get('code')}** {code.get('label', '')}"
                with st.expander(label, expanded=(rank == 1)):
                    col1, col2 = st.columns(2)
                    col1.metric("Supportability", f"{float(score):.0%}")
                    missing = code.get("missing_elements", [])
                    col2.metric("Missing elements", len(missing))

                    st.markdown(f"**Evidence summary:** {code.get('evidence_summary', '—')}")

                    if missing:
                        st.markdown("**Missing elements:**")
                        for m in missing:
                            st.markdown(f"- {m}")

                    if code.get("compliance_warning"):
                        st.warning(f"**Compliance:** {code['compliance_warning']}")

    # Gaps tab
    with tab_gaps:
        gap_analysis = package.get("_gap_analysis", {})
        gaps = gap_analysis.get("gaps", [])
        rec = gap_analysis.get("recommendation", "—")
        summary = gap_analysis.get("summary", "")

        rec_color = {"continue": "✅", "warn": "⚠️", "block": "🚫"}.get(rec, "")
        st.markdown(f"**Recommendation:** {rec_color} `{rec}`")
        if summary:
            st.caption(summary)

        if not gaps:
            st.success("No documentation gaps detected.")
        else:
            high = [g for g in gaps if g.get("severity") == "high"]
            medium = [g for g in gaps if g.get("severity") == "medium"]
            low = [g for g in gaps if g.get("severity") == "low"]

            for group, items in [("High", high), ("Medium", medium), ("Low", low)]:
                if items:
                    st.markdown(f"#### {_severity_badge(group.lower())} {group} severity")
                    for g in items:
                        with st.expander(g.get("description", "Gap")):
                            st.markdown(f"**Action:** {g.get('suggested_action', '—')}")
                            if g.get("affected_sections"):
                                st.markdown(f"**Affected sections:** {', '.join(g['affected_sections'])}")

    # Draft tab
    with tab_draft:
        justification = package.get("_justification", {})
        if not justification:
            st.info("No justification generated.")
        else:
            quality = justification.get("evidence_quality", "unknown")
            st.markdown(f"**Evidence quality:** {_quality_badge(quality)}")

            draft_warnings = justification.get("warnings", [])
            for w in draft_warnings:
                st.warning(w)

            draft = justification.get("draft_paragraph")
            if draft:
                st.markdown("#### Draft Justification")
                st.markdown(
                    f'<div style="background:#f0f4f8;padding:1rem 1.25rem;border-left:4px solid #2563eb;border-radius:4px;font-size:0.95rem;line-height:1.7">{draft}</div>',
                    unsafe_allow_html=True,
                )
                st.download_button(
                    "⬇️ Download draft (.txt)",
                    data=draft,
                    file_name=f"justification_{encounter_id}.txt",
                    mime="text/plain",
                )
            else:
                st.error("Draft paragraph not generated — evidence quality is insufficient.")

            bullets = justification.get("structured_bullets", [])
            if bullets:
                st.markdown("#### Structured Bullets")
                sections_order = [
                    "patient_condition", "functional_limitation", "objective_findings",
                    "prior_treatment_history", "treatment_provided", "medical_necessity",
                    "missing_documentation", "other",
                ]
                by_section: dict[str, list] = {}
                for b in bullets:
                    by_section.setdefault(b.get("section", "other"), []).append(b)

                for section in sections_order:
                    section_bullets = by_section.get(section, [])
                    if section_bullets:
                        with st.expander(section.replace("_", " ").title(), expanded=True):
                            for b in section_bullets:
                                conf = b.get("confidence_score")
                                conf_str = f" _(confidence: {float(conf):.0%})_" if conf is not None else ""
                                st.markdown(f"- **{b.get('label', '')}** — {b.get('content', '')}{conf_str}")

    st.divider()
    st.caption(f"Outputs saved to `outputs/{encounter_id}/`")
