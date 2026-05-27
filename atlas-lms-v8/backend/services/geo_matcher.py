"""
services/geo_matcher.py
Fuzzy district name matching — stdlib only (difflib), no extra deps.
Normalizes aliases: "Bangalore Urban" → "Bengaluru Urban" etc.
"""
import re
from difflib import SequenceMatcher

# Canonical Karnataka district names (GeoJSON expects these)
KARNATAKA_CANONICAL = [
    "Bagalkot","Ballari","Belagavi","Bengaluru Rural","Bengaluru Urban",
    "Bidar","Chamarajanagar","Chikkaballapur","Chikkamagaluru",
    "Chitradurga","Dakshina Kannada","Davanagere","Dharwad","Gadag",
    "Hassan","Haveri","Kalaburagi","Kodagu","Kolar","Koppal",
    "Mandya","Mysuru","Raichur","Ramanagara","Shivamogga","Tumakuru",
    "Udupi","Uttara Kannada","Vijayanagara","Vijayapura","Yadgir",
]

# Hard-coded alias table for known variants
ALIASES = {
    # Bengaluru variants
    "bangalore urban":    "Bengaluru Urban",
    "bangalore":          "Bengaluru Urban",
    "bengaluru":          "Bengaluru Urban",
    "bangalore rural":    "Bengaluru Rural",
    "bengaluru rural":    "Bengaluru Rural",
    # Mysuru variants
    "mysore":             "Mysuru",
    "mysuru":             "Mysuru",
    # Belagavi variants
    "belgaum":            "Belagavi",
    "belagavi":           "Belagavi",
    # Kalaburagi variants
    "gulbarga":           "Kalaburagi",
    "kalaburagi":         "Kalaburagi",
    # Shivamogga variants
    "shimoga":            "Shivamogga",
    "shivamogga":         "Shivamogga",
    # Tumakuru variants
    "tumkur":             "Tumakuru",
    "tumakuru":           "Tumakuru",
    # Vijayapura variants
    "bijapur":            "Vijayapura",
    "vijayapura":         "Vijayapura",
    # Ballari variants
    "bellary":            "Ballari",
    "ballari":            "Ballari",
    # Dakshina Kannada variants
    "mangalore":          "Dakshina Kannada",
    "mangaluru":          "Dakshina Kannada",
    "dakshina kannada":   "Dakshina Kannada",
    # Uttara Kannada variants
    "north kanara":       "Uttara Kannada",
    "uttara kannada":     "Uttara Kannada",
    # Chikkamagaluru variants
    "chikmagalur":        "Chikkamagaluru",
    "chikkamagalur":      "Chikkamagaluru",
    "chikkamagaluru":     "Chikkamagaluru",
    # Davanagere variants
    "davangere":          "Davanagere",
    "davanagere":         "Davanagere",
    # Chamarajanagar variants
    "chamrajnagar":       "Chamarajanagar",
    "chamarajnagar":      "Chamarajanagar",
    "chamarajanagar":     "Chamarajanagar",
    # Vijayanagara variants
    "vijayanagar":        "Vijayanagara",
    "vijayanagara":       "Vijayanagara",
}

_canonical_lc = [c.lower() for c in KARNATAKA_CANONICAL]


def _normalize(name: str) -> str:
    return re.sub(r'[^\w\s]', '', name.strip().lower())


def match_district(name: str, threshold: float = 0.6) -> str | None:
    """
    Map any district name variant to its canonical form.
    Returns canonical name or None if no match above threshold.
    """
    norm = _normalize(name)
    if not norm: return None

    # Exact alias lookup first
    if norm in ALIASES:
        return ALIASES[norm]

    # Exact canonical match
    if norm in _canonical_lc:
        return KARNATAKA_CANONICAL[_canonical_lc.index(norm)]

    # Fuzzy match against canonicals
    best_score = 0.0
    best_match = None
    for i, canon_lc in enumerate(_canonical_lc):
        score = SequenceMatcher(None, norm, canon_lc).ratio()
        if score > best_score:
            best_score = score
            best_match = KARNATAKA_CANONICAL[i]

    if best_score >= threshold:
        return best_match
    return None


def normalize_dataframe_districts(df, district_col: str):
    """
    Apply district matching to a dataframe column in-place.
    Unmatched rows are kept with original name.
    """
    import pandas as pd
    def _match(name):
        m = match_district(str(name))
        return m if m else name
    df[district_col] = df[district_col].apply(_match)
    return df
