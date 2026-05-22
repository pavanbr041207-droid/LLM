"""
services/embedding_service.py
Lightweight embedding service using Ollama or TF-IDF fallback.
No heavy dependencies required — works out of the box.
"""
import os, json, math, re, hashlib
from collections import Counter
from utils.storage import storage_path, read_json, write_json

STORAGE     = storage_path()
EMBED_DIR   = os.path.join(STORAGE, "embeddings")
CACHE_DIR   = os.path.join(STORAGE, "context_cache")
os.makedirs(EMBED_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# ── Try Ollama embeddings, fallback to TF-IDF ──
def get_embedding(text: str) -> list:
    """Get embedding vector for text. Uses cache."""
    text = text.strip()
    if not text: return []

    cache_key = hashlib.md5(text.encode()).hexdigest()
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")

    if os.path.exists(cache_file):
        try:
            with open(cache_file) as f:
                return json.load(f)
        except Exception:
            pass

    # Try Ollama embeddings first
    emb = _ollama_embed(text)
    if not emb:
        # Fallback: TF-IDF style sparse vector
        emb = _tfidf_embed(text)

    # Cache it
    try:
        with open(cache_file, "w") as f:
            json.dump(emb, f)
    except Exception:
        pass

    return emb


def _ollama_embed(text: str) -> list:
    """Try to get embeddings from Ollama nomic-embed-text."""
    try:
        import requests
        r = requests.post("http://localhost:11434/api/embeddings",
                          json={"model": "nomic-embed-text", "prompt": text},
                          timeout=10)
        if r.status_code == 200:
            return r.json().get("embedding", [])
    except Exception:
        pass
    return []


def _tfidf_embed(text: str, dim: int = 256) -> list:
    """
    TF-IDF style embedding — lightweight, no external deps.
    Produces a deterministic fixed-size vector from text.
    """
    words  = re.findall(r'\w+', text.lower())
    counts = Counter(words)
    total  = max(sum(counts.values()), 1)

    vector = [0.0] * dim
    for word, count in counts.items():
        # Hash word to a bucket
        bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % dim
        tf     = count / total
        idf    = math.log(1 + len(word))   # simplified IDF
        vector[bucket] += tf * idf

    # Normalize
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def cosine_similarity(a: list, b: list) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot  = sum(x * y for x, y in zip(a, b))
    na   = math.sqrt(sum(x * x for x in a))
    nb   = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def embed_and_store(doc_id: str, text: str, metadata: dict) -> bool:
    """Store an embedding with metadata in the local vector store."""
    emb = get_embedding(text)
    if not emb:
        return False
    entry = {"id": doc_id, "text": text[:500], "embedding": emb, "metadata": metadata}
    path  = os.path.join(EMBED_DIR, f"{doc_id}.json")
    with open(path, "w") as f:
        json.dump(entry, f)
    return True


def search_embeddings(query: str, top_k: int = 5, filter_type: str = None) -> list:
    """Search all stored embeddings by cosine similarity."""
    query_emb = get_embedding(query)
    if not query_emb:
        return []

    results = []
    for fname in os.listdir(EMBED_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(EMBED_DIR, fname)) as f:
                entry = json.load(f)
            meta  = entry.get("metadata", {})
            if filter_type and meta.get("type") != filter_type:
                continue
            score = cosine_similarity(query_emb, entry.get("embedding", []))
            results.append({"score": score, "text": entry.get("text",""),
                             "metadata": meta, "id": entry.get("id","")})
        except Exception:
            continue

    results.sort(key=lambda x: x["score"], reverse=True)
    return [r for r in results[:top_k] if r["score"] > 0.1]
