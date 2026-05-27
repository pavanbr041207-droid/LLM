"""utils/llm.py — Ollama + LLM data extraction for map generation"""
import requests, re, csv, io

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "qwen2.5:7b"

# Districts that the LLM knows data for (Karnataka)
KNOWN_KARNATAKA_TOPICS = {
    "rainfall", "rain", "monsoon", "precipitation",
    "population", "people", "demographic",
    "literacy", "education", "literate",
    "gdp", "income", "economic",
    "women population", "female population", "sex ratio",
    "infant mortality", "child mortality",
    "unemployment", "employment",
    "forest cover", "green cover",
    "agriculture", "crop", "yield",
    "crime", "crimes",
}

MAP_KEYWORDS = [
    "choropleth","choroplet","choropleat","chloropleth",
    "generate map","create map","make map","draw map","show map",
    "district map","state map","heat map","heatmap",
    "visualize data","map of karnataka","map of india","geographic map",
    "population map","rainfall map","literacy map","gdp map",
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
            "stream": False, "options": {"temperature": 0.3, "num_predict": 3000}
        }, timeout=180)
        r.raise_for_status()
        return r.json()["message"]["content"]
    except requests.exceptions.ConnectionError:
        return "❌ Cannot connect to Ollama. Run `ollama serve` in terminal."
    except Exception as e:
        return f"❌ LLM error: {str(e)}"


def extract_data_from_llm(topic: str, geography: str, metric_col: str) -> dict:
    """
    Query LLM for verified district-level data.
    Returns fresh CSV data or DATA_NOT_AVAILABLE.
    NEVER returns cached or previously generated data.
    """
    system = (
        "You are a precise geographic data assistant. "
        "Your job is to return ONLY a CSV table of real verified data. "
        "Rules:\n"
        "- First row: column headers exactly as: district," + metric_col + "\n"
        "- Each row: one district name, one numeric value (no units, no commas in numbers)\n"
        "- Use ONLY real verified data from your training knowledge\n"
        "- If you are NOT confident about a district's value, OMIT that district row\n"
        "- Do NOT invent, estimate, or extrapolate values\n"
        "- Do NOT add explanations, markdown, or preamble\n"
        "- If you have NO reliable data at all, respond with exactly: NO_DATA_AVAILABLE\n"
        "- Do NOT use placeholder values like 0 or 1"
    )
    prompt = (
        f"Provide a CSV table of {topic} data for {geography} districts.\n"
        f"CSV format: district,{metric_col}\n"
        f"Include all districts you have verified data for.\n"
        f"Return ONLY the CSV. No explanation."
    )
    response = ask_llm(prompt, system_prompt=system).strip()

    # Strip markdown fences
    response = re.sub(r"```[a-zA-Z]*\n?", "", response).strip()
    response = re.sub(r"```", "", response).strip()

    if not response or "NO_DATA_AVAILABLE" in response or len(response) < 20:
        return {
            "status": "no_data",
            "reason": (
                f"⚠️ **Data Not Available**\n\n"
                f"Atlas AI's LLM does not have verified data for **{topic}** "
                f"in **{geography}**.\n\n"
                f"**To generate this map**, please upload a CSV file with:\n"
                f"- Column 1: district/region names\n"
                f"- Column 2: numeric values for {topic}\n\n"
                f"Use the **Maps → Manual Generation** tab to upload and generate."
            ),
        }

    # Parse and validate CSV
    try:
        lines = [l.strip() for l in response.strip().split("\n") if l.strip()]
        # Find header line
        header_idx = 0
        for i, line in enumerate(lines):
            if "district" in line.lower() or metric_col.lower() in line.lower():
                header_idx = i
                break
        csv_text = "\n".join(lines[header_idx:])

        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)
        if not rows:
            return {"status": "no_data", "reason": f"⚠️ LLM returned no valid rows for {topic} in {geography}."}

        cols = list(rows[0].keys())
        if len(cols) < 2:
            return {"status": "no_data", "reason": f"⚠️ LLM data has only {len(cols)} column. Need 2."}

        district_col = cols[0]
        value_col    = cols[1]

        valid_rows = []
        for row in rows:
            try:
                val = row.get(value_col, "").replace(",", "").strip()
                float(val)
                dist = row.get(district_col, "").strip()
                if dist and float(val) > 0:
                    valid_rows.append({district_col: dist, value_col: val})
            except (ValueError, TypeError):
                pass

        if len(valid_rows) < 3:
            return {
                "status": "no_data",
                "reason": (
                    f"⚠️ **Insufficient Data**\n\n"
                    f"LLM returned only {len(valid_rows)} valid rows for {topic}. "
                    f"Need at least 3 districts to generate a meaningful map.\n\n"
                    f"Please upload a CSV with complete district data."
                )
            }

        # Rebuild clean CSV
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=[district_col, value_col])
        writer.writeheader()
        writer.writerows(valid_rows)
        clean_csv = out.getvalue()

        return {
            "status":       "ok",
            "csv_text":     clean_csv,
            "rows":         valid_rows,
            "district_col": district_col,
            "value_col":    value_col,
            "row_count":    len(valid_rows),
        }
    except Exception as e:
        return {"status": "no_data", "reason": f"⚠️ Could not parse LLM data: {e}"}


def infer_topic_geography_metric(user_msg: str) -> tuple:
    """Extract topic, geography, metric column name from user message."""
    msg = user_msg.lower()
    geography = "Karnataka"
    if "karnataka" in msg:    geography = "Karnataka"
    elif "india" in msg:      geography = "India"
    elif "maharashtra" in msg: geography = "Maharashtra"
    elif "tamilnadu" in msg or "tamil nadu" in msg: geography = "Tamil Nadu"

    # Topic + metric column
    if any(k in msg for k in ["women population", "female population", "women's population"]):
        return "women population", geography, "women_population"
    if any(k in msg for k in ["sex ratio", "gender ratio"]):
        return "sex ratio", geography, "sex_ratio_per_1000"
    if any(k in msg for k in ["rain", "monsoon", "precipitation", "rainfall"]):
        return "rainfall", geography, "rainfall_mm"
    if any(k in msg for k in ["literacy", "education", "literate"]):
        return "literacy rate", geography, "literacy_rate_percent"
    if any(k in msg for k in ["gdp", "income", "economic"]):
        return "GDP", geography, "gdp_index"
    if any(k in msg for k in ["infant mortality", "child mortality"]):
        return "infant mortality rate", geography, "infant_mortality_rate"
    if any(k in msg for k in ["unemployment", "unemployed"]):
        return "unemployment rate", geography, "unemployment_rate_percent"
    if any(k in msg for k in ["forest", "green cover"]):
        return "forest cover", geography, "forest_cover_sqkm"
    if any(k in msg for k in ["agriculture", "crop", "yield"]):
        return "agricultural yield", geography, "yield_tonnes_per_hectare"
    if any(k in msg for k in ["crime", "crimes"]):
        return "crime rate", geography, "crime_rate_per_lakh"
    if any(k in msg for k in ["population", "people", "demographic"]):
        return "population", geography, "population"

    # Generic extraction
    import re as re_mod
    m = re_mod.search(
        r"(?:map|choropleth|data)\s+(?:for|of)\s+(?:the\s+)?(.+?)(?:\s+(?:in|of|for|district|karnataka)|$)",
        msg
    )
    if m:
        topic = m.group(1).strip()
        metric = topic.replace(" ", "_")
        return topic, geography, metric

    return "population", geography, "population"


def is_map_request(message, csv_path=None):
    msg = message.lower()
    for kw in MAP_KEYWORDS:
        if kw in msg: return True
    if csv_path and (
        "map" in msg or "choropleth" in msg or "heatmap" in msg or
        any(w in msg for w in ["visualize", "plot", "render"])
    ):
        return True
    return False


def detect_color(message):
    msg = message.lower()
    for kw, cmap in COLOR_KEYWORDS.items():
        if re.search(r'\b' + re.escape(kw) + r'\b', msg):
            return cmap
    return None


# Patterns that mean "same map, different colour" — not a new data request
_COLOR_CHANGE_PATTERNS = [
    r"(?:change|make|convert|redo|switch|update|create|generate).*(?:color|colour|theme|cmap)",
    r"(?:in|with|using)\s+(?:red|blue|green|purple|orange|yellow|viridis|plasma|spectral|inferno|magma)",
    r"same\s+(?:map|data).*(?:different|another|new)\s+(?:color|colour)",
    r"(?:color|colour)\s+(?:it|this|the\s+map|above)\s+(?:in|to|as)",
    r"above\s+map\s+in\s+(?:red|blue|green|purple|orange|yellow|viridis|plasma|spectral)",
    r"create\s+(?:the\s+)?above\s+map\s+in",
    r"(?:re)?plot\s+(?:it|this|above|same).*(?:red|blue|green|purple)",
]


def is_color_change_request(message: str) -> bool:
    """
    Returns True when user wants to regenerate the same map with a different colour.
    Examples: "create above map in red", "change colour to blue", "same map in viridis"
    """
    msg = message.lower()
    return any(re.search(p, msg) for p in _COLOR_CHANGE_PATTERNS)


def clean_title(text):
    return re.sub(r'[^\x00-\x7F]+', '', text).strip()
