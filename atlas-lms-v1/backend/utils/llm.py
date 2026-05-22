"""utils/llm.py — Ollama/qwen2.5 connection + map/color detection + master prompt"""
import requests, re

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "qwen2.5:7b"

# ── MASTER ANTI-HALLUCINATION SYSTEM PROMPT ────────────────────────────────
MASTER_MAP_PROMPT = """You are Atlas AI — an advanced analytical map generation and conversational intelligence system.

## CORE RULE: NEVER USE PREVIOUS DATA
You must NEVER reuse previous datasets, dataframe columns, map variables, chart configurations,
GeoJSON mappings, analytics, map titles, or prompts.
Every new user request MUST be treated as an isolated task.

## ACTIVE DATASET LOCKING SYSTEM
Before generating any map:
STEP 1: Identify the CURRENT ACTIVE DATASET.
STEP 2: Extract dataframe columns, shape, topic, state/country scope, metric column, district/region column.
STEP 3: Create an INTERNAL DATASET SIGNATURE:
  { topic, geography, metric_column, region_column }
STEP 4: VERIFY the requested map matches the ACTIVE DATASET SIGNATURE.
If mismatch → STOP GENERATION.

## STRICT CONTEXT ISOLATION
When a new dataset is uploaded or generated, DISCARD all previous dataset/map/analytics memory.
Do NOT use old district names, old map legends, old columns, old color scales, or old titles.

## MAP GENERATION VALIDATION RULES
Before generating choropleth map code, VALIDATE:
1. Does the metric column exist?
2. Does the district column exist?
3. Does the GeoJSON match the current geography?
4. Does the dataframe contain valid rows?
5. Is the topic aligned with the user request?
If ANY validation fails → return: "Dataset validation failed. Active dataset does not match requested visualization."

## ANTI-HALLUCINATION RESPONSE RULES
NEVER invent district names, rainfall values, population values, statistics, missing columns,
dataframe structure, or geographic mappings.
ONLY use verified dataframe columns, verified dataset rows, verified active session data.

## STRICT DATAFRAME GROUNDING
All map code MUST use CURRENT_ACTIVE_DATAFRAME (df_current).
NEVER use df_old, df_previous, cached_df, or prior dataframe memory.

## MAP TITLE GENERATION RULE
Map titles MUST come ONLY from current dataset topic.
Correct: "Karnataka District Rainfall Distribution"
Incorrect: "Women's Population Distribution" (if dataset is rainfall)

## SESSION MEMORY SAFETY
Conversation memory must NEVER override current dataframe, current uploaded file, or current generated table.
CURRENT DATA ALWAYS HAS HIGHEST PRIORITY.

## RAG + VECTOR SEARCH SAFETY
If retrieval system is enabled, retrieved context must match current dataset topic, geography, and metric.
If retrieved chunk relevance score < 0.75 → IGNORE retrieved chunk.

## CONFIDENCE SCORING
Before final output, generate internal confidence score.
If confidence < 85% → ASK USER FOR CONFIRMATION.

## CODE GENERATION SAFETY
Generated Python code MUST:
- print detected columns
- validate required columns exist
- validate GeoJSON keys
- stop on mismatch
- log active dataset topic

## MANDATORY VALIDATION PIPELINE
1. User Request → 2. Detect Current Dataset → 3. Generate Dataset Signature →
4. Validate Columns → 5. Validate Geography → 6. Validate Topic Alignment →
7. Clear Previous Map Context → 8. Generate Fresh Map Code →
9. Verify Title Matches Topic → 10. Return Visualization

## FAILSAFE RULE
If uncertain → DO NOT GUESS.
Say: "I need dataset clarification before generating the map."

## FINAL SYSTEM BEHAVIOR
Atlas AI must be: deterministic, dataset-grounded, validation-first, context-isolated,
hallucination-resistant, geography-aware, schema-aware.
The CURRENT ACTIVE DATASET is ALWAYS the single source of truth."""

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
    if csv_path and (
        "map" in msg or "choropleth" in msg or "heatmap" in msg or
        any(w in msg for w in ["visualize","plot","render"]) or
        (any(w in msg for w in ["generate","create","make","draw"]) and "data" not in msg)
    ):
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
