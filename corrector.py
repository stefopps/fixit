"""
corrector.py — Local Ollama or Claude API correction for Flow.
Models: qwen2.5:1.5b (fast) and qwen2.5:7b (quality). Toggle via set_model().
Modes: spelling / semantic / grammar toggles via set_modes().
Cloud: Claude Haiku when set_cloud(True).
"""

import os

import requests
from dotenv import load_dotenv

from memory import build_prompt_addition, log_correction

load_dotenv()

OLLAMA_URL = "http://localhost:11434"
MODEL_LOW = "qwen2.5:1.5b"
MODEL_HIGH = "qwen2.5:7b"
MODEL = MODEL_LOW  # default; toggle via set_model()

# ── Cloud mode ─────────────────────────────────────────────────────────────────
_USE_CLOUD = False
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def set_cloud(enabled: bool):
    global _USE_CLOUD
    _USE_CLOUD = enabled
    print(f"[Flow] Cloud: {'ON — Claude API' if enabled else 'OFF — local Ollama'}")


def _call_cloud(text: str, system: str, kind: str) -> str | None:
    """Send correction to Claude API instead of local Ollama."""
    if (
        not ANTHROPIC_KEY
        or not ANTHROPIC_KEY.strip()
        or ANTHROPIC_KEY.strip() == "your_key_here"
    ):
        print("[Flow] No API key — add ANTHROPIC_API_KEY to .env")
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": text}],
        )
        block = msg.content[0]
        raw_out = getattr(block, "text", str(block))
        return _finalize_correction(text, raw_out, kind)
    except Exception as e:
        print(f"[Flow] Cloud error: {e}")
        return None


def _finalize_correction(text: str, fixed: str | None, kind: str) -> str | None:
    if not fixed:
        return None
    fixed = fixed.strip()
    if not fixed:
        return None
    for q in ('"""', "'''", '"', "'"):
        if fixed.startswith(q) and fixed.endswith(q) and len(fixed) > 2 * len(q):
            fixed = fixed[len(q) : -len(q)].strip()
            break
    if kind == "base":
        if len(fixed) > len(text) * 1.3 + 20:
            print(f"[corrector] Rejected (too long): {fixed[:60]}")
            return None
    else:
        if len(fixed) > len(text) * 1.5 + 60:
            print(f"[corrector] Rejected (too long): {fixed[:60]}")
            return None
    return fixed


_MODE_SPELLING = True
_MODE_SEMANTIC = False
_MODE_GRAMMAR = False


def set_model(high: bool):
    global MODEL
    MODEL = MODEL_HIGH if high else MODEL_LOW
    print(f"[corrector] Model → {MODEL}")


def set_modes(spelling: bool, semantic: bool, grammar: bool):
    global _MODE_SPELLING, _MODE_SEMANTIC, _MODE_GRAMMAR
    _MODE_SPELLING = spelling
    _MODE_SEMANTIC = semantic
    _MODE_GRAMMAR = grammar
    print(
        f"[corrector] Modes → spelling:{spelling} semantic:{semantic} grammar:{grammar}"
    )


TIMEOUT = 60

_clean_buffer: dict[int, str] = {}


def update_buffer(hwnd: int, clean_prefix: str, fixed_chunk: str) -> str:
    parts = [clean_prefix.strip(), fixed_chunk.strip()]
    full = " ".join(p for p in parts if p)
    _clean_buffer[hwnd] = full
    return full


def clear_buffer(hwnd: int):
    _clean_buffer.pop(hwnd, None)


BASE_SYSTEM_PROMPT = """\
You are a pure spelling corrector. Your only job is fixing typos character by character.

STRICT RULES:
- Correct ONLY spelling errors: missing letters, swapped letters, stuck-together words.
- Do NOT change word choice, sentence structure, or meaning.
- Do NOT rephrase anything.
- Do NOT fix grammar.
- Return the text with identical word order, just spelled correctly.
- Return ONLY the corrected text. Nothing else.

EXAMPLES:
"hwo do u do thsi" → "how do u do this"
"th epatient ha sa brokn arm" → "the patient has a broken arm"
"i wsa tryign to typ eth is" → "i was trying to type this"
"sdasdasd adsasdasdf" → "sdasdasd adsasdasdf"
"""

SEMANTIC_PROMPT = """\
Fix spelling errors and improve word clarity.
Return ONLY corrected text. No explanation. No title case.
Capitalize only the first word of sentences and proper nouns.
Read the full input as connected thought, not isolated words.
Preserve the author's natural voice and sentence structure.
Do not add sentences. Do not reformat."""

GRAMMAR_PROMPT = """\
You are a grammar editor. Read the full input as one complete thought.

Fix:
- Subject-verb agreement
- Wrong or missing tense
- Missing articles (a, an, the)
- Preposition errors
- Run-on sentences — split with a period where natural
- Fragmented sentences — complete them if the meaning is clear
- Capitalization of sentence starts and proper nouns only

Do NOT:
- Change the author's voice or word choice
- Add new ideas or sentences
- Use title case
- Return anything except the corrected text"""

DEEP_PROMPT = """\
Fix spelling, grammar, and improve clarity and flow.
Return ONLY corrected text. No explanation.
This is deep edit mode — fix everything but preserve the author's voice."""

SYSTEM_PROMPT = BASE_SYSTEM_PROMPT


def check_ollama() -> tuple[bool, str]:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=4)
        if r.status_code != 200:
            return False, "Ollama running but returned error."
        models = [m["name"] for m in r.json().get("models", [])]
        base = [m.split(":")[0] for m in models]
        if "qwen2.5" in base or MODEL in models:
            return True, f"Model '{MODEL}' ready."
        available = ", ".join(models) if models else "none"
        return False, f"'{MODEL}' not found. Run: ollama pull {MODEL}  (have: {available})"
    except requests.ConnectionError:
        return False, "Ollama not running. Install from ollama.com/download"
    except Exception as e:
        return False, f"Check failed: {e}"


def warmup_model() -> bool:
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


def _call_ollama(text: str, system_prompt: str | None = None) -> str | None:
    if not text or not text.strip():
        return None

    medical = build_prompt_addition()
    kind = "explicit"
    if system_prompt:
        system = system_prompt
    elif _MODE_GRAMMAR and _MODE_SEMANTIC:
        kind = "deep"
        system = DEEP_PROMPT
    elif _MODE_GRAMMAR:
        kind = "grammar"
        system = GRAMMAR_PROMPT
    elif _MODE_SEMANTIC:
        kind = "semantic"
        system = SEMANTIC_PROMPT
    else:
        kind = "base"
        system = BASE_SYSTEM_PROMPT

    if medical:
        system = system + "\n\n" + medical

    if _USE_CLOUD:
        return _call_cloud(text, system, kind)

    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                "stream": False,
                "options": {
                    "temperature": 0.05,
                    "num_predict": min(len(text) * 2, 512),
                    "top_p": 0.9,
                },
                "keep_alive": "30m",
            },
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            print(f"[corrector] HTTP {r.status_code}: {r.text[:120]}")
            return None

        fixed = r.json().get("message", {}).get("content", "").strip()
        return _finalize_correction(text, fixed, kind)

    except requests.Timeout:
        print(f"[corrector] Timeout after {TIMEOUT}s")
        return None
    except requests.ConnectionError:
        print("[corrector] Ollama not reachable")
        return None
    except Exception as e:
        print(f"[corrector] Error: {e}")
        return None


_call_ollama_with_prompt = _call_ollama


def correct_text(raw: str, hwnd: int = 0) -> str:
    _ = hwnd
    out = _call_ollama(raw, system_prompt=None)
    return out if out else raw


def grammar_correct(raw: str, hwnd: int = 0) -> str:
    if not raw or not raw.strip():
        return raw
    # Force grammar prompt regardless of mode toggles
    result = _call_ollama(raw, system_prompt=GRAMMAR_PROMPT)
    if result and result.strip() != raw.strip():
        log_correction(raw, result)
    return result or raw
