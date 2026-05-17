"""
memory.py — FixIt local learning store.
All data lives in memory.json — edit it in Notepad anytime.
No database needed. Ships with nothing, learns as you use it.
"""

import json
import shutil
import time
from pathlib import Path

MEMORY_FILE = Path(__file__).parent / "memory.json"

_PUNCT = ".,!?;:'\""
_PROTECTED_CACHE: tuple[float, frozenset[str]] | None = None
_VOCAB_CACHE: tuple[float, frozenset[str]] | None = None

# Only replace when shape match is very confident (press-7 manual mode).
_SHAPE_THRESHOLD = 0.4
_SHAPE_MARGIN_MIN = 0.20
_SHAPE_MARGIN_CAP = 0.5

# QWERTY adjacency — each key's physical neighbors
_KB = {
    "q": ["w", "a"],
    "w": ["q", "e", "a", "s"],
    "e": ["w", "r", "s", "d"],
    "r": ["e", "t", "d", "f"],
    "t": ["r", "y", "f", "g"],
    "y": ["t", "u", "g", "h"],
    "u": ["y", "i", "h", "j"],
    "i": ["u", "o", "j", "k"],
    "o": ["i", "p", "k", "l"],
    "p": ["o", "l"],
    "a": ["q", "w", "s", "z"],
    "s": ["a", "w", "e", "d", "z", "x"],
    "d": ["s", "e", "r", "f", "x", "c"],
    "f": ["d", "r", "t", "g", "c", "v"],
    "g": ["f", "t", "y", "h", "v", "b"],
    "h": ["g", "y", "u", "j", "b", "n"],
    "j": ["h", "u", "i", "k", "n", "m"],
    "k": ["j", "i", "o", "l", "m"],
    "l": ["k", "o", "p"],
    "z": ["a", "s", "x"],
    "x": ["z", "s", "d", "c"],
    "c": ["x", "d", "f", "v"],
    "v": ["c", "f", "g", "b"],
    "b": ["v", "g", "h", "n"],
    "n": ["b", "h", "j", "m"],
    "m": ["n", "j", "k"],
}

DEFAULT = {
    "dictionary":       [],   # protected terms — never autocorrect
    "abbreviations":    {},   # e.g. "SpO2": "oxygen saturation"
    "patterns":         {},   # learned typos e.g. {"hwo": {"fixed":"how","count":4}}
    "corrections_log":  [],    # last 500 raw→fixed pairs
    "word_list":        [],   # general English — fuzzy match vocabulary
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
    global _PROTECTED_CACHE, _VOCAB_CACHE
    _PROTECTED_CACHE = None
    _VOCAB_CACHE = None
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _protected_terms() -> frozenset[str]:
    """Protected dictionary (do not autocorrect) — cached by file mtime."""
    global _PROTECTED_CACHE
    mtime = MEMORY_FILE.stat().st_mtime if MEMORY_FILE.exists() else 0.0
    if _PROTECTED_CACHE is None or _PROTECTED_CACHE[0] != mtime:
        data = load()
        _PROTECTED_CACHE = (
            mtime,
            frozenset(t.lower() for t in data.get("dictionary", []) if t),
        )
    return _PROTECTED_CACHE[1]


def _key_distance(a: str, b: str) -> float:
    """0.0 = same key, 1.0 = adjacent, 2.0 = far."""
    a, b = a.lower(), b.lower()
    if a == b:
        return 0.0
    if b in _KB.get(a, []):
        return 1.0
    return 2.0


def _shape_score(typed: str, candidate: str) -> float:
    """
    Score how well a candidate word matches the typed shape.
    Lower = better match. Uses letter-order preservation + key proximity.
    """
    typed = typed.lower()
    candidate = candidate.lower()
    if not typed or not candidate:
        return 999.0

    score = abs(len(typed) - len(candidate)) * 1.5
    c_used = [False] * len(candidate)
    for i, tc in enumerate(typed):
        best = 2.5
        best_j = -1
        for j, cc in enumerate(candidate):
            if c_used[j]:
                continue
            d = _key_distance(tc, cc)
            pos_penalty = abs(
                i / max(len(typed), 1) - j / max(len(candidate), 1)
            )
            total = d + pos_penalty
            if total < best:
                best = total
                best_j = j
        if best_j >= 0:
            c_used[best_j] = True
        score += best

    return score / max(len(typed), len(candidate))


def _is_known_good(
    key: str,
    data: dict,
    vocab: set[str],
    protected: frozenset[str],
    abbrev_keys: set[str],
) -> bool:
    """Skip shape pass — word is already a spelling we trust."""
    if key in protected or key in abbrev_keys:
        return True
    if key in vocab:
        return True
    for v in data.get("patterns", {}).values():
        if v.get("fixed", "").strip(_PUNCT).lower() == key:
            return True
    return False


def _too_garbage_for_shape(key: str) -> bool:
    """Skip scoring when there is no vowel signal at all."""
    if len(key) < 3:
        return True
    vowels = sum(1 for c in key if c in "aeiou")
    return vowels == 0


def _strip_word_punct(word: str) -> tuple[str, str, str]:
    """Return (clean, trailing_punct, leading_punct)."""
    lead = ""
    clean = word
    while clean and clean[0] in _PUNCT:
        lead += clean[0]
        clean = clean[1:]
    trail = ""
    while clean and clean[-1] in _PUNCT:
        trail = clean[-1] + trail
        clean = clean[:-1]
    return clean, trail, lead


def _build_full_vocab(data: dict) -> set[str]:
    """Build fuzzy-match vocabulary from memory.json (uncached)."""
    vocab: set[str] = set()

    for w in data.get("word_list", []):
        if len(w) >= 3:
            vocab.add(w.lower())

    for t in data.get("dictionary", []):
        w = t.strip().lower()
        if len(w) >= 3:
            vocab.add(w)

    for v in data.get("patterns", {}).values():
        w = v.get("fixed", "").strip(_PUNCT).lower()
        if len(w) >= 3:
            vocab.add(w)

    for entry in data.get("corrections_log", []):
        for field in ("fixed", "raw"):
            for word in entry.get(field, "").split():
                w = word.strip(_PUNCT).lower()
                if len(w) >= 3 and w.isalpha():
                    vocab.add(w)

    return vocab


def get_full_vocab() -> set[str]:
    """
    Full vocabulary for fuzzy shape matching.
    word_list (English) + medical dictionary + learned patterns + log.
    """
    global _VOCAB_CACHE
    mtime = MEMORY_FILE.stat().st_mtime if MEMORY_FILE.exists() else 0.0
    if _VOCAB_CACHE is not None and _VOCAB_CACHE[0] == mtime:
        return set(_VOCAB_CACHE[1])

    vocab = _build_full_vocab(load())
    _VOCAB_CACHE = (mtime, frozenset(vocab))
    return vocab


def _candidate_filter(key: str, vocab: set[str]) -> list[str]:
    """
    Fast pre-filter before shape scoring.
    First key same or adjacent; length within ±2.
    (Last-letter filter omitted — it drops valid fixes like hwo→how.)
    """
    if not key or not vocab:
        return []

    first = key[0]
    first_neighbors = set(_KB.get(first, [])) | {first}
    delta = 1 if len(key) <= 4 else 2
    min_len = len(key) - delta
    max_len = len(key) + delta

    return [
        w
        for w in vocab
        if min_len <= len(w) <= max_len and w[0] in first_neighbors
    ]


def _score_candidates(key: str, vocab: set[str]) -> list[tuple[str, float]]:
    """Pre-filter then shape-score candidates (real-time safe)."""
    candidates = _candidate_filter(key, vocab)
    return sorted(
        ((c, _shape_score(key, c)) for c in candidates if c != key),
        key=lambda x: x[1],
    )


def _personal_vocab(data: dict) -> set[str]:
    """Words you actually use — from corrections and promoted patterns."""
    vocab: set[str] = set()
    for entry in data.get("corrections_log", []):
        for field in ("fixed", "raw"):
            for w in entry.get(field, "").split():
                clean = w.strip(_PUNCT).lower()
                if len(clean) >= 3 and clean.isalpha():
                    vocab.add(clean)
    for v in data.get("patterns", {}).values():
        fixed = v.get("fixed", "").strip(_PUNCT).lower()
        if len(fixed) >= 3 and fixed.isalpha():
            vocab.add(fixed)
    return vocab


def shape_correct(text: str, top_n: int = 1) -> str:
    """
    Shape-based correction for words not in patterns.
    Scores against personal vocabulary (corrections_log + pattern targets).
    Only fires when pattern lookup failed and the token looks like a typo.
    """
    if not text or not text.strip():
        return text

    data = load()
    vocab = get_full_vocab()
    if not vocab:
        return text

    patterns = data.get("patterns", {})
    protected = _protected_terms()
    abbrev_keys = {k.lower() for k in data.get("abbreviations", {})}
    result = []
    changed = False

    for word in text.split():
        clean, punct_trail, punct_lead = _strip_word_punct(word)
        key = clean.lower()

        if not key or len(key) < 5:
            result.append(word)
            continue

        if key in patterns:
            result.append(word)
            continue

        if _is_known_good(key, data, vocab, protected, abbrev_keys):
            result.append(word)
            continue

        if _too_garbage_for_shape(key):
            result.append(word)
            continue

        scored = _score_candidates(key, vocab)

        if not scored:
            result.append(word)
            continue

        best_word, best_score = scored[0]
        confident = best_score < _SHAPE_THRESHOLD
        if not confident and len(scored) > 1:
            runner_up = scored[1][1]
            margin = runner_up - best_score
            confident = (
                best_score < _SHAPE_MARGIN_CAP
                and margin >= _SHAPE_MARGIN_MIN
            )
        if not confident:
            result.append(word)
            continue

        if clean and clean[0].isupper():
            best_word = best_word.capitalize()
        confidence_pct = max(0, int((1 - best_score / _SHAPE_MARGIN_CAP) * 100))
        print(f"[shape] '{key}' -> '{best_word}' ({confidence_pct}% confidence)")
        result.append(punct_lead + best_word + punct_trail)
        changed = True

    out = " ".join(result)
    if changed:
        print(f"[memory] Shape-corrected: '{text[:60]}' -> '{out[:60]}'")
    return out


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


def backup_memory() -> None:
    """Snapshot memory.json; keep only the 3 most recent backups."""
    if not MEMORY_FILE.exists():
        return
    dst = MEMORY_FILE.parent / f"memory_backup_{int(time.time())}.json"
    shutil.copy2(MEMORY_FILE, dst)
    backups = sorted(MEMORY_FILE.parent.glob("memory_backup_*.json"))
    for old in backups[:-3]:
        old.unlink()
    print(f"[memory] Backup saved: {dst.name}")


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
    if len(data["corrections_log"]) % 100 == 0:
        backup_memory()


def _pattern_pass(text: str) -> str:
    """Pass 1: exact learned typo patterns (count >= 2)."""
    patterns = load()["patterns"]
    words = text.split()
    result = []
    changed = False
    for word in words:
        clean, punct_trail, punct_lead = _strip_word_punct(word)
        key = clean.lower()
        entry = patterns.get(key)
        if entry and entry["count"] >= 2:
            fixed_word = entry["fixed"]
            if clean and clean[0].isupper():
                fixed_word = fixed_word.capitalize()
            result.append(punct_lead + fixed_word + punct_trail)
            changed = True
        else:
            result.append(word)
    out = " ".join(result)
    if changed:
        print(f"[memory] Pre-corrected: '{text[:60]}' -> '{out[:60]}'")
    return out


def pre_correct(text: str) -> str:
    """
    Fast local correction before any model call.
    Pass 1: learned patterns. Pass 2: keyboard-shape scoring on typos.
    """
    return shape_correct(_pattern_pass(text))


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
    log = data.get("agreement_log") or []
    return {
        "dictionary":      len(data["dictionary"]),
        "word_list":       len(data.get("word_list", [])),
        "abbreviations":   len(data["abbreviations"]),
        "patterns":        len(data["patterns"]),
        "corrections_log": len(data["corrections_log"]),
        "training_pairs":  len(data.get("training", {})),
        "agreement_rate": (
            sum(log) / len(log) if log else 0.0
        ),
    }
