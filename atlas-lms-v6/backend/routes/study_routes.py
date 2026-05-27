"""routes/study_routes.py — MCQ, assignments, notes, topic explainer"""
import os
from flask import Blueprint, request, jsonify
from utils.storage import storage_path, read_json, write_json, now, new_id
from utils.llm import ask_llm

study_bp   = Blueprint("study", __name__)
STORAGE    = storage_path()
NOTES_FILE = os.path.join(STORAGE, "notes", "notes.json")

@study_bp.route("/notes/list", methods=["GET"])
def list_notes():
    return jsonify(read_json(NOTES_FILE, []))

@study_bp.route("/notes/save", methods=["POST","OPTIONS"])
def save_note():
    if request.method == "OPTIONS": return jsonify({}), 200
    data  = request.json or {}
    notes = read_json(NOTES_FILE, [])
    note  = {"id":new_id(),"title":data.get("title","Untitled"),
             "content":data.get("content",""),"created":now(),"updated":now()}
    notes.insert(0, note)
    write_json(NOTES_FILE, notes[:200])
    return jsonify(note)

@study_bp.route("/notes/delete/<note_id>", methods=["DELETE","OPTIONS"])
def delete_note(note_id):
    if request.method == "OPTIONS": return jsonify({}), 200
    write_json(NOTES_FILE, [n for n in read_json(NOTES_FILE,[]) if n["id"]!=note_id])
    return jsonify({"ok":True})

@study_bp.route("/generate-mcq", methods=["POST","OPTIONS"])
def generate_mcq():
    if request.method == "OPTIONS": return jsonify({}), 200
    data  = request.json or {}
    topic = data.get("topic","").strip()
    count = int(data.get("count", 5))
    if not topic: return jsonify({"error":"topic required"}), 400
    prompt = (f"Generate {count} multiple choice questions about: {topic}\n\n"
              "Format each as:\nQ: [question]\nA) [option]\nB) [option]\nC) [option]\nD) [option]\nAnswer: [letter]\n\n"
              "Make them clear and educational.")
    return jsonify({"mcqs": ask_llm(prompt)})

@study_bp.route("/generate-assignment", methods=["POST","OPTIONS"])
def generate_assignment():
    if request.method == "OPTIONS": return jsonify({}), 200
    data  = request.json or {}
    topic = data.get("topic","").strip()
    atype = data.get("type","report")
    if not topic: return jsonify({"error":"topic required"}), 400
    prompt = f"Generate a {atype} for a student on: {topic}\n\nMake it educational and well-structured."
    return jsonify({"assignment": ask_llm(prompt)})

@study_bp.route("/explain", methods=["POST","OPTIONS"])
def explain():
    if request.method == "OPTIONS": return jsonify({}), 200
    data  = request.json or {}
    topic = data.get("topic","").strip()
    level = data.get("level","simple")
    if not topic: return jsonify({"error":"topic required"}), 400
    prompt = f"Explain the following in a {level} way for a student:\n\n{topic}"
    return jsonify({"explanation": ask_llm(prompt)})
