"""
memory.py — FixIt local learning store.
All data lives in memory.json — edit it in Notepad anytime.
No database needed. Ships with nothing, learns as you use it.
"""

import json
from pathlib import Path

MEMORY_FILE = Path(__file__).parent / "memory.json"

DEFAULT = {
    "dictionary":       [],   # protected terms — never autocorrect
    "abbreviations":    {},   # e.g. "SpO2": "oxygen saturation"
    "patterns":         {},   # learned typos e.g. {"hwo": {"fixed":"how","count":4}}
    "corrections_log":  []    # last 500 raw→fixed pairs
}


def load() -> dict:
    if MEMORY_FILE.exists():
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in DEFAULT.items():
                if k not in data:
                    data[k] = v
            return data
        except Exception:
            pass
    return {k: (v.copy() if isinstance(v, (list, dict)) else v)
            for k, v in DEFAULT.items()}


def save(data: dict):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Public API ─────────────────────────────────────────────────────────────────

def add_terms(terms: list[str]) -> int:
    data = load()
    existing = set(t.lower() for t in data["dictionary"])
    new = [t.strip() for t in terms
           if t.strip() and t.strip().lower() not in existing]
    data["dictionary"].extend(new)
    save(data)
    return len(new)


def add_abbreviations(abbrevs: dict) -> int:
    data = load()
    existing = set(data["abbreviations"].keys())
    new = {k: v for k, v in abbrevs.items() if k not in existing}
    data["abbreviations"].update(new)
    save(data)
    return len(new)


def log_correction(raw: str, fixed: str):
    """Log correction and promote frequent word-level patterns."""
    data = load()
    data["corrections_log"].append({"raw": raw, "fixed": fixed})

    raw_words   = raw.strip().split()
    fixed_words = fixed.strip().split()

    if len(raw_words) == len(fixed_words):
        for r, f in zip(raw_words, fixed_words):
            r_key = r.lower().strip(".,!?;:'\"")
            f_clean = f.strip(".,!?;:'\"")
            if r_key != f_clean.lower() and len(r_key) > 1:
                if r_key not in data["patterns"]:
                    data["patterns"][r_key] = {"fixed": f_clean, "count": 1}
                else:
                    data["patterns"][r_key]["count"] += 1

    data["corrections_log"] = data["corrections_log"][-500:]
    save(data)


def pre_correct(text: str) -> str:
    """
    Fast local correction before hitting Ollama.
    Only applies patterns seen 2+ times — avoids false positives.
    """
    patterns = load()["patterns"]
    words = text.split()
    result = []
    changed = False
    for word in words:
        punct_trail = ""
        clean = word
        # peel trailing punctuation
        while clean and clean[-1] in ".,!?;:'\"":
            punct_trail = clean[-1] + punct_trail
            clean = clean[:-1]
        key = clean.lower()
        entry = patterns.get(key)
        if entry and entry["count"] >= 2:
            fixed_word = entry["fixed"]
            if clean and clean[0].isupper():
                fixed_word = fixed_word.capitalize()
            result.append(fixed_word + punct_trail)
            changed = True
        else:
            result.append(word)
    out = " ".join(result)
    if changed:
        print(f"[memory] Pre-corrected: '{text[:60]}' → '{out[:60]}'")
    return out


def build_prompt_addition() -> str:
    """
    Returns extra lines for the Ollama system prompt:
    protected terms + known abbreviations.
    Capped to keep prompt short and fast.
    """
    data = load()
    lines = []

    dictionary = data.get("dictionary", [])
    if dictionary:
        terms = ", ".join(dictionary[:50])
        lines.append(
            f"PROTECTED TERMS — do not alter these words: {terms}"
        )

    abbreviations = data.get("abbreviations", {})
    if abbreviations:
        abbrevs = ", ".join(list(abbreviations.keys())[:150])
        lines.append(
            f"KNOWN ABBREVIATIONS — do not expand or alter: {abbrevs}"
        )

    return "\n".join(lines)


def stats() -> dict:
    data = load()
    return {
        "dictionary":      len(data["dictionary"]),
        "abbreviations":   len(data["abbreviations"]),
        "patterns":        len(data["patterns"]),
        "corrections_log": len(data["corrections_log"]),
    }
