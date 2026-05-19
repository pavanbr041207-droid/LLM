"""routes/file_routes.py — General file upload/download"""
import os, uuid
from flask import Blueprint, request, jsonify, send_file
from utils.storage import storage_path, now

file_bp = Blueprint("file", __name__)
STORAGE = storage_path()
ALLOWED = {".pdf",".csv",".docx",".txt",".png",".jpg",".jpeg",".json",".py",".md",".geojson"}

@file_bp.route("/upload", methods=["POST","OPTIONS"])
def upload():
    if request.method == "OPTIONS": return jsonify({}), 200
    if "file" not in request.files: return jsonify({"error":"No file"}), 400
    f   = request.files["file"]
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED: return jsonify({"error":f"Type {ext} not allowed"}), 400
    fdir = os.path.join(STORAGE,"files")
    os.makedirs(fdir, exist_ok=True)
    fid  = uuid.uuid4().hex[:10]
    fp   = os.path.join(fdir, f"{fid}{ext}")
    f.save(fp)
    return jsonify({"id":fid,"name":f.filename,"stored":f"{fid}{ext}","ext":ext,"uploaded":now()})

@file_bp.route("/list", methods=["GET"])
def list_files():
    fdir = os.path.join(STORAGE,"files")
    os.makedirs(fdir, exist_ok=True)
    return jsonify([{"name":fn,"size":os.path.getsize(os.path.join(fdir,fn)),
                     "path":f"/storage/files/{fn}"}
                    for fn in os.listdir(fdir)])

@file_bp.route("/download/<filename>", methods=["GET"])
def download(filename):
    p = os.path.join(STORAGE,"files",filename)
    if not os.path.exists(p): return jsonify({"error":"Not found"}), 404
    return send_file(p, as_attachment=True)
