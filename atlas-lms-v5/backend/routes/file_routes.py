"""routes/file_routes.py — Multimodal file upload + processing
Extends original: same endpoints preserved, new /process endpoint added.
"""
import os, uuid
from flask import Blueprint, request, jsonify, send_file
from utils.storage import storage_path, now

file_bp = Blueprint("file", __name__)
STORAGE = storage_path()

ALLOWED = {
    ".pdf", ".csv", ".docx", ".doc", ".txt", ".png", ".jpg", ".jpeg",
    ".json", ".py", ".md", ".geojson", ".xlsx", ".xls", ".webp",
    ".gif", ".pptx", ".bmp",
}


@file_bp.route("/upload", methods=["POST", "OPTIONS"])
def upload():
    """Original upload endpoint — preserved exactly."""
    if request.method == "OPTIONS": return jsonify({}), 200
    if "file" not in request.files: return jsonify({"error": "No file"}), 400
    f   = request.files["file"]
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED: return jsonify({"error": f"Type {ext} not allowed"}), 400
    fdir = os.path.join(STORAGE, "files")
    os.makedirs(fdir, exist_ok=True)
    fid  = uuid.uuid4().hex[:10]
    fp   = os.path.join(fdir, f"{fid}{ext}")
    f.save(fp)
    return jsonify({
        "id":       fid,
        "name":     f.filename,
        "stored":   f"{fid}{ext}",
        "ext":      ext,
        "uploaded": now(),
    })


@file_bp.route("/upload-and-process", methods=["POST", "OPTIONS"])
def upload_and_process():
    """
    Upload file AND process it (extract text, detect datasets, store in vector memory).
    Returns extended metadata including dataset detection results.
    """
    if request.method == "OPTIONS": return jsonify({}), 200
    if "file" not in request.files: return jsonify({"error": "No file"}), 400

    f          = request.files["file"]
    session_id = request.form.get("session_id")
    project_id = request.form.get("project_id")
    user_prompt= request.form.get("prompt", "")
    ext        = os.path.splitext(f.filename)[1].lower()

    if ext not in ALLOWED:
        return jsonify({"error": f"Type {ext} not allowed"}), 400

    fdir = os.path.join(STORAGE, "files")
    os.makedirs(fdir, exist_ok=True)
    fid  = uuid.uuid4().hex[:10]
    fp   = os.path.join(fdir, f"{fid}{ext}")
    f.save(fp)

    # Route to correct processor
    try:
        from services.file_router import route_file
        result = route_file(fp, fid, f.filename, session_id, project_id, user_prompt)
    except Exception as e:
        result = {"success": False, "error": str(e)}

    result.update({
        "id":       fid,
        "name":     f.filename,
        "stored":   f"{fid}{ext}",
        "ext":      ext,
        "uploaded": now(),
    })
    return jsonify(result)


@file_bp.route("/list", methods=["GET"])
def list_files():
    """Original list endpoint — preserved."""
    fdir = os.path.join(STORAGE, "files")
    os.makedirs(fdir, exist_ok=True)
    return jsonify([{
        "name":  fn,
        "size":  os.path.getsize(os.path.join(fdir, fn)),
        "path":  f"/storage/files/{fn}",
    } for fn in os.listdir(fdir)])


@file_bp.route("/download/<filename>", methods=["GET"])
def download(filename):
    """Original download endpoint — preserved."""
    p = os.path.join(STORAGE, "files", filename)
    if not os.path.exists(p): return jsonify({"error": "Not found"}), 404
    return send_file(p, as_attachment=True)


@file_bp.route("/analyze-image", methods=["POST", "OPTIONS"])
def analyze_image_endpoint():
    """Direct image analysis endpoint for existing images."""
    if request.method == "OPTIONS": return jsonify({}), 200
    data      = request.json or {}
    file_path = data.get("file_path", "")
    prompt    = data.get("prompt", "")
    session_id= data.get("session_id", "default")

    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 400

    try:
        from services.image_processor import analyze_image
        result = analyze_image(file_path, prompt)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
