"""
build_dictionary.py — One-time setup.
Downloads medical word lists from GitHub and loads them into memory.json.
Run once: python build_dictionary.py
"""

import csv
import io
import json
import re
import sys
import urllib.request
from pathlib import Path
from memory import add_terms, add_abbreviations, stats

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

SOURCES = {
    "hunspell_medical": (
        "https://raw.githubusercontent.com/glutanimate/"
        "hunspell-en-med-glut/master/en_med_glut.dic"
    ),
    "medical_abbreviations": (
        "https://raw.githubusercontent.com/KumaTea/"
        "medical-abbreviations/master/ALL.csv"
    ),
}

def fetch(url: str, label: str) -> str | None:
    print(f"  Downloading {label}...", end=" ", flush=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FixIt/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read().decode("utf-8", errors="ignore")
        print(f"OK ({len(data):,} bytes)")
        return data
    except Exception as e:
        print(f"FAILED: {e}")
        return None


def parse_hunspell(text: str) -> list[str]:
    terms = []
    for line in text.splitlines():
        word = line.strip().split("/")[0].strip()
        if word and len(word) >= 3 and re.match(r"^[A-Za-z\-']+$", word):
            terms.append(word)
    return terms


def parse_abbreviations_csv(text: str) -> dict:
    abbrevs = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        k = (row.get("Abbreviation") or row.get("abbreviation") or "").strip()
        v = (row.get("Meaning") or row.get("meaning") or "").strip()
        if k and v:
            abbrevs[k] = v
    return abbrevs


def parse_abbreviations(text: str) -> dict:
    abbrevs = {}
    if text.lstrip().startswith(("Abbreviation,", "abbreviation,")):
        return parse_abbreviations_csv(text)
    try:
        raw = json.loads(text)
        if isinstance(raw, dict):
            abbrevs = {str(k): str(v) for k, v in raw.items() if k and v}
        elif isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                k = (item.get("abbreviation") or item.get("abbr")
                     or item.get("short") or "")
                v = (item.get("expansion") or item.get("meaning")
                     or item.get("full") or "")
                if k and v:
                    abbrevs[str(k)] = str(v)
    except Exception as e:
        print(f"  Parse error: {e}")
    return abbrevs


print()
print("=" * 55)
print("  FixIt — Building Medical Dictionary")
print("=" * 55)

# ── Source 1: hunspell medical word list ──────────────────
print("\n[1] Medical word list (hunspell-en-med-glut)")
text = fetch(SOURCES["hunspell_medical"], "hunspell medical dict")
if text:
    terms = parse_hunspell(text)
    added = add_terms(terms)
    print(f"  Parsed {len(terms):,} words → added {added:,} new terms")
else:
    print("  Skipped (download failed)")

# ── Source 2: medical abbreviations ───────────────────────
print("\n[2] Medical abbreviations")
text = fetch(SOURCES["medical_abbreviations"], "abbreviations")
if text:
    abbrevs = parse_abbreviations(text)
    added = add_abbreviations(abbrevs)
    print(f"  Parsed {len(abbrevs):,} abbreviations → added {added:,} new")
else:
    print("  Skipped (download failed)")

# ── Also add common EM/clinical abbreviations by default ──
print("\n[3] Built-in EM/clinical abbreviations")
BUILTIN = {
    "SpO2": "oxygen saturation", "O2": "oxygen", "HR": "heart rate",
    "BP": "blood pressure", "RR": "respiratory rate", "Temp": "temperature",
    "GCS": "Glasgow Coma Scale", "LOC": "loss of consciousness",
    "SOB": "shortness of breath", "CP": "chest pain", "HA": "headache",
    "N/V": "nausea and vomiting", "Abd": "abdomen", "c/o": "complains of",
    "h/o": "history of", "PMH": "past medical history", "HPI": "history of present illness",
    "ROS": "review of systems", "PE": "physical exam", "A&O": "alert and oriented",
    "HEENT": "head eyes ears nose throat", "CXR": "chest x-ray",
    "EKG": "electrocardiogram", "ECG": "electrocardiogram",
    "IV": "intravenous", "IM": "intramuscular", "SQ": "subcutaneous",
    "prn": "as needed", "qid": "four times daily", "tid": "three times daily",
    "bid": "twice daily", "qd": "once daily", "stat": "immediately",
    "Dx": "diagnosis", "Tx": "treatment", "Rx": "prescription",
    "Hx": "history", "Sx": "symptoms", "Fx": "fracture",
    "ETT": "endotracheal tube", "BVM": "bag valve mask",
    "ALS": "advanced life support", "BLS": "basic life support",
    "EMS": "emergency medical services", "ED": "emergency department",
    "ICU": "intensive care unit", "OR": "operating room",
    "NPO": "nothing by mouth", "DNR": "do not resuscitate",
}
added = add_abbreviations(BUILTIN)
print(f"  Added {added} built-in EM abbreviations")

# ── Summary ────────────────────────────────────────────────
s = stats()
print()
print("=" * 55)
print(f"  ✓ Dictionary:    {s['dictionary']:,} terms")
print(f"  ✓ Abbreviations: {s['abbreviations']:,} entries")
print(f"  ✓ Saved to memory.json")
print("=" * 55)
print()
print("  You can add your own terms anytime:")
print("  Open memory.json in Notepad → edit 'dictionary' array")
print()
