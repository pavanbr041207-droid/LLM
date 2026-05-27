"""
services/retrieval_engine.py
Semantic retrieval across messages, CSVs, maps, notes, project docs.
"""
import os
from utils.storage import storage_path, read_json
from services.embedding_service import search_embeddings

STORAGE = storage_path()


def retrieve_relevant_context(query: str, session_id: str = None,
                               project_id: str = None, top_k: int = 4) -> str:
    hits = search_embeddings(query, top_k=top_k * 2)
    if not hits:
        return ""

    filtered = []
    for h in hits:
        meta  = h.get("metadata", {})
        boost = 1.0
        if session_id and meta.get("session_id") == session_id:
            boost = 1.5
        if project_id and meta.get("project_id") == project_id:
            boost = 1.8
        h["boosted_score"] = h["score"] * boost
        filtered.append(h)

    filtered.sort(key=lambda x: x["boosted_score"], reverse=True)
    top = filtered[:top_k]
    if not top:
        return ""

    parts = ["--- Relevant Context from Memory ---"]
    for h in top:
        meta = h.get("metadata", {})
        typ  = meta.get("type","item")
        text = h.get("text","")[:300]
        ts   = meta.get("timestamp","")[:10]
        if typ == "message":
            parts.append(f"[{ts}] {meta.get('role','').upper()}: {text}")
        elif typ == "csv":
            parts.append(f"[CSV: {meta.get('filename','')}] {text}")
        elif typ == "map":
            parts.append(f"[Map: {meta.get('title','')}] {text}")
        else:
            parts.append(f"[{typ}] {text}")
    return "\n".join(parts)


def retrieve_csv_context(csv_path: str, query: str = "") -> str:
    if not csv_path or not os.path.exists(csv_path):
        return ""
    try:
        import pandas as pd
        df    = pd.read_csv(csv_path)
        rows  = df.head(8).to_string(index=False)
        cols  = ", ".join(df.columns.tolist())
        shape = f"{len(df)} rows x {len(df.columns)} columns"
        return f"CSV ({shape}):\nColumns: {cols}\n\nSample:\n{rows}"
    except Exception as e:
        return f"[CSV error: {e}]"


def retrieve_project_docs(project_id: str, query: str, top_k: int = 3) -> str:
    if not project_id:
        return ""
    doc_idx = os.path.join(STORAGE, "documents", f"{project_id}_docs.json")
    docs    = read_json(doc_idx, [])
    if not docs:
        return ""
    query_words = set(query.lower().split())
    scored = []
    for doc in docs:
        for chunk in doc.get("chunks", []):
            score = len(query_words & set(chunk.lower().split()))
            if score > 0:
                scored.append((score, chunk, doc["name"]))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]
    if not top:
        return ""
    parts = ["--- Project Document Context ---"]
    for _, chunk, name in top:
        parts.append(f"[From: {name}]\n{chunk[:400]}")
    return "\n\n".join(parts)
