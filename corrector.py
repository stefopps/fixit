"""
corrector.py — Local Ollama typo correction.
Model: qwen2.5:1.5b  (~1GB, CPU-only, fast)
"""

import requests

OLLAMA_URL  = "http://localhost:11434"
MODEL       = "qwen2.5:1.5b"
TIMEOUT     = 60   # generous for cold CPU load

SYSTEM_PROMPT = """\
You are a typo corrector. Fix spelling errors, missing letters, and transposed letters.
Rules:
- Return ONLY the corrected text. Nothing else.
- No explanation. No quotes. No preamble.
- Do NOT rephrase, rewrite, or add words.
- Do NOT change meaning, punctuation, or formatting.
- If text is already correct, return it exactly as-is."""


def check_ollama() -> tuple[bool, str]:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=4)
        if r.status_code != 200:
            return False, "Ollama running but returned error."
        models = [m["name"] for m in r.json().get("models", [])]
        base   = [m.split(":")[0] for m in models]
        if "qwen2.5" in base or MODEL in models:
            return True, f"Model '{MODEL}' ready."
        available = ", ".join(models) if models else "none"
        return False, f"'{MODEL}' not found. Run: ollama pull {MODEL}  (have: {available})"
    except requests.ConnectionError:
        return False, "Ollama not running. Install from ollama.com/download"
    except Exception as e:
        return False, f"Check failed: {e}"


def warmup_model() -> bool:
    """Send a tiny request to load the model into RAM."""
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
                "options": {"num_predict": 1, "temperature": 0},
                "keep_alive": "30m",
            },
            timeout=TIMEOUT,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"[corrector] warmup failed: {e}")
        return False


def correct_text(raw: str) -> str:
    if not raw or not raw.strip():
        return raw
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": raw},
                ],
                "stream": False,
                "options": {
                    "temperature": 0.05,
                    "num_predict": min(len(raw) * 2, 512),
                    "top_p": 0.9,
                },
                "keep_alive": "30m",
            },
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            print(f"[corrector] HTTP {r.status_code}: {r.text[:120]}")
            return raw

        fixed = r.json().get("message", {}).get("content", "").strip()
        if not fixed:
            return raw

        # Strip accidental wrapping quotes
        for q in ('"""', "'''", '"', "'"):
            if fixed.startswith(q) and fixed.endswith(q) and len(fixed) > 2*len(q):
                fixed = fixed[len(q):-len(q)].strip()
                break

        # Reject if model added significant content (elaboration guard)
        if len(fixed) > len(raw) * 1.3 + 20:
            print(f"[corrector] Rejected (too long): {fixed[:60]}")
            return raw

        return fixed

    except requests.Timeout:
        print(f"[corrector] Timeout after {TIMEOUT}s")
        return raw
    except requests.ConnectionError:
        print("[corrector] Ollama not reachable")
        return raw
    except Exception as e:
        print(f"[corrector] Error: {e}")
        return raw
