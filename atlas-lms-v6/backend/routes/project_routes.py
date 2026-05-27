"""
routes/project_routes.py
Full Projects: create/edit/delete, chat grouping+movement, system prompt, documents, RAG
"""
import os
from flask import Blueprint, request, jsonify, send_file
from utils.storage import storage_path, read_json, write_json, now, new_id
from utils.llm import ask_llm

project_bp = Blueprint("project", __name__)
STORAGE    = storage_path()

# ── Path helpers ──
def proj_index():     return os.path.join(STORAGE, "projects", "index.json")
def doc_index(pid):   return os.path.join(STORAGE, "documents", f"{pid}_docs.json")
def chat_idx_file():  return os.path.join(STORAGE, "chats", "_index.json")
def chat_data(cid):   return os.path.join(STORAGE, "chats", f"{cid}.json")

# ── Project helpers ──
def load_projects():            return read_json(proj_index(), [])
def save_projects(d):           write_json(proj_index(), d)
def get_project(pid):           return next((p for p in load_projects() if p["id"]==pid), None)

# ── Chat index helpers ──
def load_chat_idx():            return read_json(chat_idx_file(), [])
def save_chat_idx(d):           write_json(chat_idx_file(), d)

def update_chat_project(chat_id, project_id):
    """Update project_id in both the chat file and the index."""
    cf   = chat_data(chat_id)
    chat = read_json(cf, {})
    chat["project_id"] = project_id
    chat["updated"]    = now()
    write_json(cf, chat)
    idx = load_chat_idx()
    for c in idx:
        if c["id"] == chat_id:
            c["project_id"] = project_id
            c["updated"]    = now()
    save_chat_idx(idx)

# ══════════════════════════════════════════════════════════
# PROJECT CRUD
# ══════════════════════════════════════════════════════════

@project_bp.route("/list", methods=["GET"])
def list_projects():
    projects = load_projects()
    idx      = load_chat_idx()
    # Attach chat count to each project
    for p in projects:
        p["chat_count"] = sum(1 for c in idx if c.get("project_id") == p["id"])
    return jsonify(projects)

@project_bp.route("/create", methods=["POST","OPTIONS"])
def create_project():
    if request.method == "OPTIONS": return jsonify({}), 200
    data    = request.json or {}
    project = {
        "id":            new_id(),
        "title":         data.get("title", "New Project"),
        "description":   data.get("description", ""),
        "system_prompt": data.get("system_prompt",
                         "You are a helpful AI assistant for this project. "
                         "Use the project documents and context to give accurate answers."),
        "memory":        "",
        "icon":          data.get("icon", "📁"),
        "created":       now(),
        "updated":       now(),
    }
    projects = load_projects()
    projects.insert(0, project)
    save_projects(projects)
    return jsonify(project), 201

@project_bp.route("/get/<project_id>", methods=["GET"])
def get_project_route(project_id):
    p = get_project(project_id)
    if not p: return jsonify({"error": "Not found"}), 404
    return jsonify(p)

@project_bp.route("/update/<project_id>", methods=["PUT","OPTIONS"])
def update_project(project_id):
    if request.method == "OPTIONS": return jsonify({}), 200
    data     = request.json or {}
    projects = load_projects()
    for p in projects:
        if p["id"] == project_id:
            for k in ["title","description","system_prompt","memory","icon"]:
                if k in data: p[k] = data[k]
            p["updated"] = now()
            save_projects(projects)
            return jsonify(p)
    return jsonify({"error": "Not found"}), 404

@project_bp.route("/delete/<project_id>", methods=["DELETE","OPTIONS"])
def delete_project(project_id):
    if request.method == "OPTIONS": return jsonify({}), 200
    # Move all project chats back to Recent
    idx = load_chat_idx()
    for c in idx:
        if c.get("project_id") == project_id:
            update_chat_project(c["id"], None)
    # Delete all project documents
    docs = read_json(doc_index(project_id), [])
    for doc in docs:
        fp = os.path.join(STORAGE, "documents", doc.get("stored",""))
        if os.path.exists(fp): os.remove(fp)
    di = doc_index(project_id)
    if os.path.exists(di): os.remove(di)
    # Remove project
    projects = [p for p in load_projects() if p["id"] != project_id]
    save_projects(projects)
    return jsonify({"ok": True})

@project_bp.route("/update-prompt/<project_id>", methods=["PUT","OPTIONS"])
def update_prompt(project_id):
    if request.method == "OPTIONS": return jsonify({}), 200
    data     = request.json or {}
    projects = load_projects()
    for p in projects:
        if p["id"] == project_id:
            p["system_prompt"] = data.get("system_prompt", p.get("system_prompt",""))
            p["updated"]       = now()
            save_projects(projects)
            return jsonify({"ok": True})
    return jsonify({"error": "Not found"}), 404

# ══════════════════════════════════════════════════════════
# CHAT MOVEMENT  (Recent ↔ Project)
# ══════════════════════════════════════════════════════════

@project_bp.route("/move-chat", methods=["POST","OPTIONS"])
def move_chat():
    """Move a chat into a project, or back to Recent (project_id=None)."""
    if request.method == "OPTIONS": return jsonify({}), 200
    data       = request.json or {}
    chat_id    = data.get("chat_id")
    project_id = data.get("project_id")   # None → Recent
    if not chat_id:
        return jsonify({"error": "chat_id required"}), 400
    if not os.path.exists(chat_data(chat_id)):
        return jsonify({"error": "Chat not found"}), 404
    if project_id and not get_project(project_id):
        return jsonify({"error": "Project not found"}), 404
    update_chat_project(chat_id, project_id)
    return jsonify({"ok": True, "chat_id": chat_id, "project_id": project_id})

@project_bp.route("/remove-chat", methods=["POST","OPTIONS"])
def remove_chat():
    """Remove a chat from its project → moves to Recent."""
    if request.method == "OPTIONS": return jsonify({}), 200
    data    = request.json or {}
    chat_id = data.get("chat_id")
    if not chat_id: return jsonify({"error": "chat_id required"}), 400
    update_chat_project(chat_id, None)
    return jsonify({"ok": True, "chat_id": chat_id, "project_id": None})

@project_bp.route("/chats/<project_id>", methods=["GET"])
def get_project_chats(project_id):
    """List all chats belonging to this project."""
    idx   = load_chat_idx()
    chats = [c for c in idx if c.get("project_id") == project_id]
    return jsonify(chats)

# ══════════════════════════════════════════════════════════
# DOCUMENT MANAGEMENT
# ══════════════════════════════════════════════════════════

@project_bp.route("/docs/upload/<project_id>", methods=["POST","OPTIONS"])
def upload_doc(project_id):
    if request.method == "OPTIONS": return jsonify({}), 200
    if not get_project(project_id):
        return jsonify({"error": "Project not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f   = request.files["file"]
    ext = os.path.splitext(f.filename)[1].lower()
    allowed = {".pdf",".txt",".md",".docx",".csv"}
    if ext not in allowed:
        return jsonify({"error": f"Type {ext} not allowed. Use: {', '.join(allowed)}"}), 400

    doc_id   = new_id()
    stored   = f"{project_id}_{doc_id}{ext}"
    doc_path = os.path.join(STORAGE, "documents", stored)
    os.makedirs(os.path.join(STORAGE, "documents"), exist_ok=True)
    f.save(doc_path)
    content  = _extract_text(doc_path, ext)
    chunks   = _chunk_text(content)

    entry = {
        "id":       doc_id,
        "name":     f.filename,
        "stored":   stored,
        "ext":      ext,
        "size":     os.path.getsize(doc_path),
        "uploaded": now(),
        "content":  content[:3000],
        "chunks":   chunks,
    }
    docs = read_json(doc_index(project_id), [])
    docs.append(entry)
    write_json(doc_index(project_id), docs)

    return jsonify({
        "id": doc_id, "name": f.filename,
        "size": entry["size"], "uploaded": entry["uploaded"]
    }), 201

@project_bp.route("/docs/list/<project_id>", methods=["GET"])
def list_docs(project_id):
    docs = read_json(doc_index(project_id), [])
    # Strip chunks from response (too large)
    return jsonify([{k:v for k,v in d.items() if k not in ("chunks","content")} for d in docs])

@project_bp.route("/docs/delete/<project_id>/<doc_id>", methods=["DELETE","OPTIONS"])
def delete_doc(project_id, doc_id):
    if request.method == "OPTIONS": return jsonify({}), 200
    docs = read_json(doc_index(project_id), [])
    doc  = next((d for d in docs if d["id"]==doc_id), None)
    if not doc: return jsonify({"error": "Document not found"}), 404
    fp = os.path.join(STORAGE, "documents", doc["stored"])
    if os.path.exists(fp): os.remove(fp)
    docs = [d for d in docs if d["id"] != doc_id]
    write_json(doc_index(project_id), docs)
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════
# RAG — keyword-based retrieval (no embeddings needed for local LLM)
# ══════════════════════════════════════════════════════════

def retrieve_chunks(project_id, query, top_k=3):
    docs = read_json(doc_index(project_id), [])
    if not docs: return ""
    query_words = set(query.lower().split())
    scored = []
    for doc in docs:
        for chunk in doc.get("chunks", []):
            score = len(query_words & set(chunk.lower().split()))
            if score > 0:
                scored.append((score, chunk, doc["name"]))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]
    if not top: return ""
    result = "\n\n--- Relevant Document Context ---"
    for _, chunk, name in top:
        result += f"\n\n[From: {name}]\n{chunk}"
    return result

def _chunk_text(text, size=400):
    words  = text.split()
    chunks = []
    step   = size - 40
    for i in range(0, len(words), step):
        c = " ".join(words[i:i+size])
        if c.strip(): chunks.append(c)
    return chunks

def _extract_text(path, ext):
    try:
        if ext in (".txt",".md",".csv"):
            with open(path,"r",encoding="utf-8",errors="ignore") as f: return f.read()
        elif ext == ".pdf":
            try:
                import fitz
                doc  = fitz.open(path)
                return "".join(p.get_text() for p in doc)
            except ImportError:
                return "[PDF extraction needs: pip install PyMuPDF]"
        elif ext == ".docx":
            try:
                import docx
                doc = docx.Document(path)
                return "\n".join(p.text for p in doc.paragraphs)
            except ImportError:
                return "[DOCX extraction needs: pip install python-docx]"
    except Exception as e:
        return f"[Extraction error: {e}]"
    return ""

# ══════════════════════════════════════════════════════════
# CONTEXT BUILDER  (called by chat_routes)
# ══════════════════════════════════════════════════════════

def build_project_context(project_id, user_query, chat_history):
    """Returns (system_prompt, extra_context) for injecting into LLM call."""
    proj = get_project(project_id)
    if not proj: return None, None

    system_prompt = proj.get("system_prompt","")
    memory        = proj.get("memory","")
    retrieved     = retrieve_chunks(project_id, user_query)

    parts = []
    if memory:    parts.append(f"--- Project Memory ---\n{memory}")
    if retrieved: parts.append(retrieved)
    if chat_history:
        hist  = "\n".join(f"{m['role'].upper()}: {m['content']}"
                          for m in chat_history[-10:])
        parts.append(f"--- Chat History ---\n{hist}")

    return system_prompt, "\n\n".join(parts)
