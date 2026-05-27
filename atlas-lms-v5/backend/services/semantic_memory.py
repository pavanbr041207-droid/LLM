"""
services/semantic_memory.py
Stores embeddings for messages, CSVs, maps, files.
Enables cross-chat reference resolution.
"""
import os, json
from datetime import datetime
from utils.storage import storage_path, new_id
from services.embedding_service import embed_and_store, search_embeddings

STORAGE = storage_path()

# ── Memory entry types ──
TYPE_MESSAGE  = "message"
TYPE_CSV      = "csv"
TYPE_MAP      = "map"
TYPE_FILE     = "file"
TYPE_NOTE     = "note"

def store_message(session_id: str, role: str, content: str, attachments: dict = None):
    """Embed and store a chat message."""
    if not content or not content.strip(): return
    doc_id = new_id()
    meta   = {
        "type":       TYPE_MESSAGE,
        "session_id": session_id,
        "role":       role,
        "timestamp":  datetime.now().isoformat(),
        "attachments": attachments or {}
    }
    embed_and_store(doc_id, content, meta)

def store_csv(csv_path: str, session_id: str, preview: str = ""):
    """Embed and store CSV file reference."""
    if not csv_path: return
    fname  = os.path.basename(csv_path)
    doc_id = new_id()
    text   = f"CSV file: {fname}. Preview: {preview}"
    meta   = {
        "type":       TYPE_CSV,
        "session_id": session_id,
        "path":       csv_path,
        "filename":   fname,
        "timestamp":  datetime.now().isoformat(),
    }
    embed_and_store(doc_id, text, meta)

def store_map(map_id: str, title: str, session_id: str, csv_path: str = "",
              colormap: str = "", value_col: str = ""):
    """Embed and store map generation event."""
    doc_id = new_id()
    text   = f"Choropleth map: {title}. Value: {value_col}. Color: {colormap}."
    meta   = {
        "type":       TYPE_MAP,
        "session_id": session_id,
        "map_id":     map_id,
        "title":      title,
        "csv_path":   csv_path,
        "colormap":   colormap,
        "value_col":  value_col,
        "map_file":   f"{map_id}.png",
        "timestamp":  datetime.now().isoformat(),
    }
    embed_and_store(doc_id, text, meta)

def store_file(file_path: str, filename: str, session_id: str):
    """Embed and store uploaded file reference."""
    doc_id = new_id()
    text   = f"Uploaded file: {filename}"
    meta   = {
        "type":       TYPE_FILE,
        "session_id": session_id,
        "path":       file_path,
        "filename":   filename,
        "timestamp":  datetime.now().isoformat(),
    }
    embed_and_store(doc_id, text, meta)

# ── Reference resolution ──
def resolve_reference(user_msg: str, session_id: str, current_csv: str = None):
    """
    Detect references like 'above csv', 'previous map', 'last file'
    and return resolved resource paths/ids.
    """
    msg_lower = user_msg.lower()
    result    = {"csv_path": current_csv, "map_id": None, "context": ""}

    # ── CSV references ──
    csv_refs = ["above csv", "previous csv", "last csv", "that csv",
                "use csv", "same csv", "earlier csv", "last uploaded"]
    if any(r in msg_lower for r in csv_refs):
        hits = search_embeddings(user_msg, top_k=3, filter_type=TYPE_CSV)
        # Also filter by session for relevance
        session_hits = [h for h in hits if h["metadata"].get("session_id") == session_id]
        best = session_hits[0] if session_hits else (hits[0] if hits else None)
        if best:
            p = best["metadata"].get("path","")
            if os.path.exists(p):
                result["csv_path"]  = p
                result["context"]  += f"\n[Retrieved CSV: {best['metadata'].get('filename','')}]"

    # ── Map references ──
    map_refs = ["previous map", "last map", "that map", "above map",
                "earlier map", "same map", "the map", "previous graph"]
    if any(r in msg_lower for r in map_refs):
        hits = search_embeddings(user_msg, top_k=3, filter_type=TYPE_MAP)
        session_hits = [h for h in hits if h["metadata"].get("session_id") == session_id]
        best = session_hits[0] if session_hits else (hits[0] if hits else None)
        if best:
            result["map_id"]   = best["metadata"].get("map_id","")
            result["map_meta"] = best["metadata"]
            result["context"] += f"\n[Retrieved Map: {best['metadata'].get('title','')}]"

    # ── Semantic search for any reference ──
    if not result["csv_path"] and not result["map_id"]:
        # General semantic search across all stored items
        hits = search_embeddings(user_msg, top_k=5)
        if hits:
            ctx_parts = []
            for h in hits:
                if h["metadata"].get("type") == TYPE_CSV:
                    p = h["metadata"].get("path","")
                    if os.path.exists(p) and not result["csv_path"]:
                        result["csv_path"] = p
                elif h["metadata"].get("type") == TYPE_MAP:
                    if not result.get("map_id"):
                        result["map_id"]   = h["metadata"].get("map_id","")
                        result["map_meta"] = h["metadata"]
                ctx_parts.append(h.get("text",""))
            if ctx_parts:
                result["semantic_context"] = "\n".join(ctx_parts[:3])

    return result
