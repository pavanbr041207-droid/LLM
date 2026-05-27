"""app.py — Atlas LMS Main Backend — Fixed CORS + all blueprints"""
import os
from flask import Flask, jsonify, send_from_directory, request, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}},
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE  = os.path.join(BASE_DIR, "..", "storage")
for folder in ["chats","maps","projects","files","uploads","history","notes","documents","execution_state"]:
    os.makedirs(os.path.join(STORAGE, folder), exist_ok=True)

from routes.chat_routes    import chat_bp
from routes.map_routes     import map_bp
from routes.project_routes import project_bp
from routes.study_routes   import study_bp
from routes.file_routes    import file_bp

app.register_blueprint(chat_bp,    url_prefix="/api/chat")
app.register_blueprint(map_bp,     url_prefix="/api/map")
app.register_blueprint(project_bp, url_prefix="/api/project")
app.register_blueprint(study_bp,   url_prefix="/api/study")
app.register_blueprint(file_bp,    url_prefix="/api/file")

@app.after_request
def after_request(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    return response

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "app": "Atlas LMS", "version": "2.1"})

@app.route("/storage/<path:filename>")
def serve_storage(filename):
    return send_from_directory(STORAGE, filename)

if __name__ == "__main__":
    print("=" * 55)
    print("  Atlas LMS Backend — http://localhost:5001")
    print("  Health check: http://localhost:5001/api/health")
    print("=" * 55)
    app.run(debug=True, use_reloader=False, port=5001, host="0.0.0.0")
