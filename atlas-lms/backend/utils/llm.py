"""utils/llm.py — Ollama/qwen2.5 connection + map/color detection"""
import requests, re

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "qwen2.5:7b"

MAP_KEYWORDS = [
    "choropleth","choroplet","choropleat","chloropleth",
    "generate map","create map","make map","draw map","show map",
    "district map","state map","heat map","heatmap",
    "literacy rate","population map","gdp map",
    "visualize data","map of karnataka","map of india","geographic map",
]

COLOR_KEYWORDS = {
    "blue":"Blues","blues":"Blues","navy":"Blues",
    "green":"Greens","greens":"Greens","lime":"Greens",
    "red":"Reds","reds":"Reds","crimson":"Reds",
    "purple":"Purples","purples":"Purples","violet":"Purples",
    "orange":"Oranges","oranges":"Oranges","amber":"Oranges",
    "grey":"Greys","gray":"Greys","black":"Greys",
    "pink":"RdPu","rose":"RdPu",
    "brown":"YlOrBr","tan":"YlOrBr",
    "teal":"GnBu","cyan":"GnBu","aqua":"GnBu",
    "viridis":"viridis","plasma":"plasma","rainbow":"rainbow",
    "spectral":"Spectral","warm":"YlOrRd","hot":"hot","jet":"jet",
    "inferno":"inferno","magma":"magma","cividis":"cividis","turbo":"turbo",
    "colorful":"Spectral","multi":"Spectral","yellow":"YlOrRd",
}

DISTRICT_NAME_MAP = {
    "chamarajanagar":"chamarajanagar","chamarajnagar":"chamarajanagar",
    "chamrajnagar":"chamarajanagar","davangere":"davanagere",
    "bengaluru urban":"bangalore urban","bengaluru rural":"bangalore rural",
    "mysuru":"mysore","belagavi":"belgaum","kalaburagi":"gulbarga",
    "shivamogga":"shimoga","tumakuru":"tumkur","vijayapura":"bijapur",
    "ballari":"bellary","mangaluru":"dakshina kannada",
    "mangalore":"dakshina kannada","chikkamagaluru":"chikmagalur",
    "chikkamagalur":"chikmagalur","north kanara":"uttara kannada",
}

def ask_llm(prompt, system_prompt=None):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL_NAME, "messages": messages,
            "stream": False, "options": {"temperature": 0.3, "num_predict": 2048}
        }, timeout=120)
        r.raise_for_status()
        return r.json()["message"]["content"]
    except requests.exceptions.ConnectionError:
        return "❌ Cannot connect to Ollama. Run `ollama serve` in terminal."
    except Exception as e:
        return f"❌ LLM error: {str(e)}"

def is_map_request(message, csv_path=None):
    msg = message.lower()
    for kw in MAP_KEYWORDS:
        if kw in msg: return True
    if csv_path and any(w in msg for w in ["map","generate","create","show","visualize","plot","district","literacy","population"]):
        return True
    return False

def detect_color(message):
    msg = message.lower()
    for kw, cmap in COLOR_KEYWORDS.items():
        if re.search(r'\b' + re.escape(kw) + r'\b', msg):
            return cmap
    return None

def clean_title(text):
    return re.sub(r'[^\x00-\x7F]+', '', text).strip()
