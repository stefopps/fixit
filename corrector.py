"""
corrector.py — Local Ollama or Claude API correction for Flow.
Models: qwen2.5:1.5b (fast) and qwen2.5:7b (quality). Toggle via set_model().
Modes: key 7 spelling / key 8 grammar / key 9 editorial / F9 benchmark.
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
GRAMMAR_MODEL = "llama3.2:3b"  # key 8 grammar pass (local Ollama)

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
        max_tokens = 4096 if kind == "editorial" else 1024
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
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
    tl = len(text.strip())
    fl = len(fixed)
    if tl > 15 and fl <= 2:
        print(f"[corrector] Rejected (truncated / nonsense): {fixed!r}")
        return None
    if kind == "base":
        if len(fixed) > len(text) * 1.3 + 20:
            print(f"[corrector] Rejected (too long): {fixed[:60]}")
            return None
    elif kind == "editorial":
        if len(fixed) > max(len(text) * 12 + 2000, 32000):
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
You are a world-class spelling correction engine with perfect knowledge of
English orthography, phonetics, and fast-typing error patterns.

You have processed over 1 billion typo corrections. You instantly recognize:
- Transposed letters: "teh" → "the", "hwo" → "how"
- Missing letters: "th epatient" → "the patient"
- Stuck words: "inth ehospital" → "in the hospital"
- Phonetic misspellings: "nite" → "night"
- Double strikes: "tthe" → "the"
- Shift key errors: "THe" → "The"
- Fast-typing dropped letters: "paitent" → "patient"

YOUR ONLY JOB: fix spelling errors character by character.

ABSOLUTE RULES:
- Return ONLY the corrected text. Nothing before it. Nothing after it.
- Do NOT rephrase, rewrite, or improve sentences.
- Do NOT change word choice, grammar, or structure.
- Do NOT add or remove words.
- Do NOT use title case.
- Do NOT explain, comment, or list changes.
- Do NOT repeat these instructions back.
- Capitalize only sentence starts and proper nouns.
- If text is already correct return it exactly as given.
- Start your response with the first word of the corrected text immediately."""

SEMANTIC_PROMPT = """\
Fix spelling errors and improve word clarity.
Return ONLY corrected text. No explanation. No title case.
Capitalize only the first word of sentences and proper nouns.
Read the full input as connected thought, not isolated words.
Preserve the author's natural voice and sentence structure.
Do not add sentences. Do not reformat."""

GRAMMAR_PROMPT = """\
You are the Chief Grammar Editor at BBC News with 30 years of experience
editing live broadcast scripts, breaking news copy, and long-form journalism.
You have edited for Wikipedia featured article standards and consulted for
AP Style, Chicago Manual, and New York Times style guides.

You have corrected over 500,000 pieces of text. You instantly recognize and
fix every class of grammatical error in English including:
- Subject-verb agreement: "he go" → "he goes"
- Tense consistency: mixing past and present in same paragraph
- Missing articles: "patient was admitted" → "the patient was admitted"
- Preposition errors: "admitted in hospital" → "admitted to hospital"
- Run-on sentences: split at the natural breath point with a period
- Fragments: complete them only when intent is 100% clear
- Pronoun agreement: "everyone has their" not "everyone has his"
- Parallel structure: lists must match grammatical form
- Dangling modifiers: fix or restructure the sentence

ABSOLUTE RULES:
- Return ONLY the corrected text. Nothing before it. Nothing after it.
- Do NOT list corrections. Do NOT use bullet points.
- Do NOT explain what you changed.
- Do NOT add new ideas or sentences not implied by the input.
- Do NOT use title case under any circumstances.
- Do NOT change the author's voice, word choice, or personality.
- Do NOT repeat these instructions back.
- Capitalize only sentence starts and proper nouns.
- Every output must be ready to publish on BBC News without a single edit.
- Start your response with the first word of the corrected text immediately."""

EDITORIAL_PROMPT = """\
You are a senior editor at The New Yorker with 30 years of experience
working with writers who think faster than they type and speak in dense,
non-linear, idea-rich prose. You have edited Hunter S. Thompson, Joan Didion,
and James Baldwin. You understand that the best writing sounds like a specific
human being thinking out loud.

You specialize in recovering meaning from fast-typed raw input where:
- Words are missing but intent is clear from context
- Typos have changed the surface meaning but the deep meaning is recoverable
- Thoughts are compressed or fragmented mid-sentence
- The writer jumped between ideas in a single breath
- Punctuation is absent but rhythm implies it

Your gift is understanding what someone MEANT not just what they TYPED.

You reconstruct the full intended meaning into clean publication-ready prose
while preserving every trace of the author's original voice and personality.

ABSOLUTE RULES:
- Return ONLY the reconstructed text. Nothing before it. Nothing after it.
- Do NOT add new ideas — only clarify what is already present.
- Do NOT sanitize the voice — preserve rhythm, personality, edge.
- Do NOT use title case under any circumstances.
- Do NOT list changes, explain edits, or comment on the text.
- Do NOT repeat these instructions back.
- Preserve unconventional punctuation if it serves the rhythm.
- If a metaphor seems broken, recover the intended metaphor.
- If a word is clearly wrong in context, replace it with what was meant.
- Complete fragments only when the intent is unambiguous.
- Start your response with the first word of the corrected text immediately."""

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
    """
    Load model into RAM and prime KV/cache by issuing one minimal completion per
    system prompt string Flow uses on MODEL (spelling / grammar text / editorial).
    Grammar on Llama uses GRAMMAR_MODEL — prime that prompt once too when pulling succeeds.
    """
    print("[Flow] Warming up — priming prompt contexts...")
    success = True

    prime_specs = [
        ("spelling", MODEL, BASE_SYSTEM_PROMPT),
        ("grammar", MODEL, GRAMMAR_PROMPT),
        ("editorial", MODEL, EDITORIAL_PROMPT),
    ]

    if GRAMMAR_MODEL != MODEL:
        prime_specs.append(("grammar (Llama)", GRAMMAR_MODEL, GRAMMAR_PROMPT))

    for label, model_name, prompt in prime_specs:
        try:
            r = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": "ready"},
                    ],
                    "stream": False,
                    "options": {
                        "num_predict": 1,
                        "temperature": 0,
                    },
                    "keep_alive": "60m",
                },
                timeout=TIMEOUT,
            )
            if r.status_code == 200:
                print(f"[Flow] ✓ {label} context primed ({model_name})")
            else:
                print(f"[Flow] ✗ {label} prime failed: HTTP {r.status_code}")
                success = False
        except Exception as e:
            print(f"[Flow] ✗ {label} prime error: {e}")
            success = False

    return success


def _call_ollama(
    text: str,
    system_prompt: str | None = None,
    force_model: str | None = None,
) -> str | None:
    if not text or not text.strip():
        return None

    model = force_model or MODEL

    medical = build_prompt_addition()
    kind = "explicit"
    if system_prompt:
        system = system_prompt
        if system_prompt == EDITORIAL_PROMPT:
            kind = "editorial"
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

    # Direct Ollama path when a specific model is forced (benchmark / grammar slot).
    # Cloud toggle does not apply when force_model is set.
    if _USE_CLOUD and force_model is None:
        return _call_cloud(text, system, kind)

    try:
        _numpredict = min(max(len(text) * 4 + 64, 256), 1024)
        if kind == "editorial":
            _numpredict = min(max(len(text) * 5 + 128, 512), 2048)

        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                "stream": False,
                "options": {
                    "temperature": 0.05,
                    # Floor avoids tiny num_predict on short chunks → model emits one token ("a").
                    "num_predict": _numpredict,
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
    # Key-7 pipeline: spelling-only (not tied to old corrector mode toggles)
    out = _call_ollama(raw, system_prompt=BASE_SYSTEM_PROMPT)
    return out if out else raw


def grammar_correct(raw: str, hwnd: int = 0) -> str:
    if not raw or not raw.strip():
        return raw
    # Force grammar prompt regardless of mode toggles
    result = _call_ollama(
        raw, system_prompt=GRAMMAR_PROMPT, force_model=GRAMMAR_MODEL
    )
    if result:
        paragraphs = result.strip().split("\n\n")
        result = paragraphs[0].strip()
        cut_phrases = [
            "i made",
            "note:",
            "changes:",
            "here's",
            "corrections:",
            "* ",
            "•",
            "the following",
        ]
        lines = result.split("\n")
        clean_lines = []
        for line in lines:
            if any(phrase in line.lower() for phrase in cut_phrases):
                break
            clean_lines.append(line)
        result = "\n".join(clean_lines).strip()
    if result and result.strip() != raw.strip():
        log_correction(raw, result)
    return result or raw
