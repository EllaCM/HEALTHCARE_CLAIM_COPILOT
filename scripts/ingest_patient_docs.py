"""Offline ingestion: chunk encounter note by section, embed with Voyage AI, store in Chroma."""

import os
import pathlib
import re
from typing import Any

try:
    import chromadb
    import voyageai
    _RAG_AVAILABLE = True
except ImportError:
    _RAG_AVAILABLE = False

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent
_VECTOR_INDEX_DIR = _PROJECT_ROOT / "data" / "vector_index"

_voyage_client = None  # voyageai.Client when _RAG_AVAILABLE

# Section header keywords (uppercase match)
_SECTION_KEYWORDS: dict[str, list[str]] = {
    "chief_complaint": ["CHIEF COMPLAINT"],
    "hpi": ["HISTORY OF PRESENT ILLNESS", "HPI"],
    "functional_limitations": ["FUNCTIONAL LIMITATIONS", "FUNCTIONAL LIMITATION"],
    "objective": ["OBJECTIVE FINDINGS", "OBJECTIVE"],
    "assessment": ["ASSESSMENT", "DIAGNOSIS"],
    "treatment_provided": ["TREATMENT PROVIDED", "TREATMENT"],
    "response": ["RESPONSE TO TREATMENT", "RESPONSE"],
    "plan": ["PLAN"],
}

# Ordered for matching priority (longer/more-specific first)
_ORDERED_KEYWORDS: list[tuple[str, str]] = sorted(
    [(section, kw) for section, keywords in _SECTION_KEYWORDS.items() for kw in keywords],
    key=lambda x: -len(x[1]),
)


def _get_voyage_client():
    global _voyage_client
    if _voyage_client is None:
        key = os.environ.get("VOYAGE_API_KEY")
        if not key:
            raise EnvironmentError("VOYAGE_API_KEY is not set. See .env.example.")
        _voyage_client = voyageai.Client(api_key=key)
    return _voyage_client


def _parse_sections(note_text: str) -> list[dict[str, str]]:
    """Split note into chunks by section header. Returns [{section, text}].

    Falls back to a single 'full_note' chunk if no headers are detected.
    """
    lines = note_text.splitlines()
    chunks: list[dict[str, str]] = []
    current_section = "full_note"
    current_lines: list[str] = []

    for line in lines:
        upper = line.strip().upper()
        matched_section: str | None = None
        for section, keyword in _ORDERED_KEYWORDS:
            # Match header lines: the keyword appears at start or is the entire line
            if upper.startswith(keyword):
                matched_section = section
                break
        if matched_section:
            if current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    chunks.append({"section": current_section, "text": text})
            current_section = matched_section
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            chunks.append({"section": current_section, "text": text})

    if not chunks:
        chunks = [{"section": "full_note", "text": note_text.strip()}]

    return chunks


def _collection_name(patient_id: str, encounter_id: str) -> str:
    # Chroma requires: 3-63 chars, alphanumeric + underscores/hyphens, no consecutive dots
    safe_patient = re.sub(r"[^a-zA-Z0-9_-]", "_", patient_id)
    safe_encounter = re.sub(r"[^a-zA-Z0-9_-]", "_", encounter_id)
    return f"{safe_patient}__{safe_encounter}"


def _get_chroma_client(patient_id: str, encounter_id: str):
    persist_dir = _VECTOR_INDEX_DIR / patient_id / encounter_id
    persist_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist_dir))


def ingest_encounter(patient_id: str, encounter_id: str, note_text: str) -> str:
    """Parse note → section chunks → Voyage AI embeddings → Chroma upsert.

    Idempotent: skips embedding if this encounter is already indexed.
    Returns the Chroma collection name.
    """
    if not _RAG_AVAILABLE:
        return "unavailable"
    client = _get_chroma_client(patient_id, encounter_id)
    name = _collection_name(patient_id, encounter_id)
    collection = client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})

    # Idempotency check
    existing = collection.get(where={"encounter_id": encounter_id}, limit=1)
    if existing["ids"]:
        return name

    chunks = _parse_sections(note_text)
    texts = [c["text"] for c in chunks]

    voyage = _get_voyage_client()
    result = voyage.embed(texts, model="voyage-3-large", input_type="document")
    embeddings = result.embeddings

    doc_ids = [f"{encounter_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas: list[dict[str, Any]] = [
        {
            "section": chunks[i]["section"],
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "chunk_index": i,
        }
        for i in range(len(chunks))
    ]

    collection.upsert(ids=doc_ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
    return name


def retrieve_chunks(
    patient_id: str,
    encounter_id: str,
    query: str,
    n_results: int = 5,
) -> list[dict[str, Any]]:
    """Embed query and retrieve top-n chunks from Chroma.

    Returns [{section, text, chunk_index, distance}].
    """
    if not _RAG_AVAILABLE:
        return []
    client = _get_chroma_client(patient_id, encounter_id)
    name = _collection_name(patient_id, encounter_id)

    try:
        collection = client.get_collection(name=name)
    except Exception:
        return []

    voyage = _get_voyage_client()
    query_embedding = voyage.embed([query], model="voyage-3-large", input_type="query").embeddings[0]

    count = collection.count()
    if count == 0:
        return []

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(n_results, count),
        include=["documents", "metadatas", "distances"],
    )

    chunks: list[dict[str, Any]] = []
    for i, doc_id in enumerate(results["ids"][0]):
        meta = results["metadatas"][0][i]
        chunks.append(
            {
                "section": meta.get("section", "unknown"),
                "text": results["documents"][0][i],
                "chunk_index": meta.get("chunk_index", i),
                "distance": results["distances"][0][i],
            }
        )
    return chunks
