"""
services/vector_memory.py
Lightweight RAG using Ollama nomic-embed-text embeddings.
Stores embeddings as numpy arrays in JSON. No ChromaDB/FAISS dependency.
Falls back to keyword search if Ollama embedding model unavailable.
"""
import os, json, re
import numpy as np
import requests
from utils.storage import storage_path, new_id, now

STORAGE    = storage_path()
EMBED_URL  = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"
CHUNK_SIZE  = 400    # words per chunk
CHUNK_OVERLAP = 50
TOP_K_DEFAULT = 4


# ── Embedding ────────────────────────────────────────────────────────────────

def _get_embedding(text: str) -> list | None:
    """Get embedding from Ollama nomic-embed-text. Returns None on failure."""
    try:
        r = requests.post(EMBED_URL, json={"model": EMBED_MODEL, "prompt": text[:2000]}, timeout=15)
        if r.status_code == 200:
            return r.json().get("embedding")
    except Exception:
        pass
    return None


def _cosine(a: list, b: list) -> float:
    a, b = np.array(a), np.array(b)
    n    = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / n) if n > 0 else 0.0


# ── Chunking ─────────────────────────────────────────────────────────────────

def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    words  = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + size])
        chunks.append(chunk)
        i += size - overlap
    return [c for c in chunks if len(c.strip()) > 30]


# ── Storage ───────────────────────────────────────────────────────────────────

def _vec_dir(namespace: str) -> str:
    d = os.path.join(STORAGE, "vectors", namespace)
    os.makedirs(d, exist_ok=True)
    return d


def _index_path(namespace: str) -> str:
    return os.path.join(_vec_dir(namespace), "index.json")


def _load_index(namespace: str) -> list:
    p = _index_path(namespace)
    if not os.path.exists(p): return []
    try:
        with open(p) as f: return json.load(f)
    except Exception: return []


def _save_index(namespace: str, index: list):
    with open(_index_path(namespace), "w") as f:
        json.dump(index, f)


# ── Public API ───────────────────────────────────────────────────────────────

def store_text(text: str, namespace: str, metadata: dict = None) -> int:
    """
    Chunk text, embed each chunk, store in namespace index.
    Returns number of chunks stored.
    Namespace = session_id or project_id for isolation.
    """
    if not text or not text.strip(): return 0
    chunks = chunk_text(text)
    index  = _load_index(namespace)
    stored = 0
    for chunk in chunks:
        emb = _get_embedding(chunk)
        entry = {
            "id":        new_id(),
            "text":      chunk,
            "metadata":  metadata or {},
            "timestamp": now(),
            "embedding": emb,   # None if Ollama unavailable
        }
        index.append(entry)
        stored += 1
    # Keep last 500 chunks per namespace
    _save_index(namespace, index[-500:])
    return stored


def retrieve(query: str, namespace: str, top_k: int = TOP_K_DEFAULT) -> list[dict]:
    """
    Semantic retrieval. Falls back to keyword search if no embeddings available.
    Returns list of {text, score, metadata}.
    """
    index = _load_index(namespace)
    if not index: return []

    # Try embedding-based search
    q_emb = _get_embedding(query)
    if q_emb and index[0].get("embedding"):
        scored = []
        for entry in index:
            if entry.get("embedding"):
                score = _cosine(q_emb, entry["embedding"])
                scored.append({"text": entry["text"], "score": score,
                               "metadata": entry.get("metadata", {})})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    # Keyword fallback
    q_words = set(re.sub(r'[^\w\s]','',query.lower()).split())
    scored  = []
    for entry in index:
        words = set(re.sub(r'[^\w\s]','',entry["text"].lower()).split())
        score = len(q_words & words) / max(len(q_words), 1)
        if score > 0:
            scored.append({"text": entry["text"], "score": score,
                           "metadata": entry.get("metadata", {})})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def retrieve_as_context(query: str, namespace: str, top_k: int = TOP_K_DEFAULT) -> str:
    """Return retrieved chunks as a formatted context string for prompt injection."""
    results = retrieve(query, namespace, top_k)
    if not results: return ""
    lines = ["=== RETRIEVED CONTEXT ==="]
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r['text'][:400]}")
    lines.append("=== END CONTEXT ===")
    return "\n".join(lines)


def store_conversation_turn(session_id: str, role: str, content: str):
    """Store a single conversation turn for semantic retrieval."""
    store_text(content, namespace=session_id,
               metadata={"role": role, "type": "conversation"})


def store_document(file_id: str, text: str, project_id: str,
                   filename: str, file_type: str):
    """Store document chunks in project namespace."""
    store_text(text, namespace=project_id or file_id,
               metadata={"file_id": file_id, "filename": filename,
                         "file_type": file_type, "type": "document"})


def clear_namespace(namespace: str):
    p = _index_path(namespace)
    if os.path.exists(p): os.remove(p)
