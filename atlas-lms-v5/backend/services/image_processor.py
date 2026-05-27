"""
services/image_processor.py
Image understanding via Ollama vision models (qwen2.5-vl, llava, moondream).
Sends base64 image to Ollama multimodal endpoint.
"""
import base64, os, requests, re
from utils.storage import storage_path, new_id, now

OLLAMA_URL   = "http://localhost:11434/api/chat"
# Ordered preference: try each model until one responds
VISION_MODELS = ["qwen2.5vl:7b", "llava:7b", "llava", "moondream"]
STORAGE = storage_path()


def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _try_vision_model(image_b64: str, prompt: str) -> str | None:
    """Try each vision model in order until one works."""
    for model in VISION_MODELS:
        try:
            r = requests.post(OLLAMA_URL, json={
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": prompt,
                    "images": [image_b64],
                }],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 1500},
            }, timeout=90)
            if r.status_code == 200:
                return r.json()["message"]["content"]
        except Exception:
            continue
    return None


def analyze_image(image_path: str, user_prompt: str = "") -> dict:
    """
    Analyze an image using Ollama vision model.
    Returns { success, text, model_used, has_table, has_chart, ocr_text }
    """
    if not os.path.exists(image_path):
        return {"success": False, "error": "Image file not found"}

    prompt = user_prompt if user_prompt else (
        "Analyze this image in detail. If it contains:\n"
        "- A table: extract all data in CSV format\n"
        "- A chart/graph: describe the data it shows\n"
        "- Text: transcribe the text (OCR)\n"
        "- A map: describe the geographic regions and values\n"
        "- Other: describe what you see clearly.\n"
        "Be specific and extract all data visible."
    )

    try:
        b64 = _encode_image(image_path)
    except Exception as e:
        return {"success": False, "error": f"Could not read image: {e}"}

    text = _try_vision_model(b64, prompt)
    if text is None:
        return {
            "success": False,
            "error":   (
                "No vision model available. Install one with:\n"
                "  ollama pull qwen2.5vl:7b\n"
                "  ollama pull llava"
            ),
        }

    # Detect if response contains structured data
    has_table = bool(re.search(r'[|,]\s*\d', text) or "district" in text.lower())
    has_chart = any(k in text.lower() for k in ["chart","graph","plot","bar","line","pie"])
    ocr_text  = _extract_ocr(text)

    return {
        "success":   True,
        "text":      text,
        "has_table": has_table,
        "has_chart": has_chart,
        "ocr_text":  ocr_text,
    }


def _extract_ocr(text: str) -> str:
    """Extract any transcribed text from vision response."""
    lines = text.splitlines()
    ocr_lines = []
    in_ocr = False
    for line in lines:
        l = line.strip()
        if any(k in l.lower() for k in ["text:", "transcrib", "ocr", "reads:", "says:"]):
            in_ocr = True
        if in_ocr and l:
            ocr_lines.append(l)
    return "\n".join(ocr_lines[:20]) if ocr_lines else ""


def save_image_analysis(session_id: str, image_path: str, analysis: dict) -> str:
    """Save analysis result to storage for retrieval."""
    ocr_dir = os.path.join(STORAGE, "ocr")
    os.makedirs(ocr_dir, exist_ok=True)
    aid  = new_id()
    path = os.path.join(ocr_dir, f"{aid}.json")
    import json
    json.dump({
        "id":         aid,
        "session_id": session_id,
        "image_path": image_path,
        "analysis":   analysis,
        "timestamp":  now(),
    }, open(path, "w"))
    return aid
