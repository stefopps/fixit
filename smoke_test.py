"""
smoke_test.py — Run this before using Flow. All 7 must pass.
python smoke_test.py
"""

import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def test(name, fn):
    print(f"  {name}... ", end="", flush=True)
    try:
        result = fn()
        print(f"PASS  {result}")
        return True
    except Exception as e:
        print(f"FAIL  {e}")
        return False

print()
print("=" * 55)
print("  Flow — Smoke Test")
print("=" * 55)
print()

from corrector import check_ollama, warmup_model, correct_text
from memory import stats

results = []

def t1():
    ok, msg = check_ollama()
    if not ok: raise Exception(msg)
    return msg
results.append(test("1. Ollama reachable", t1))

def t2():
    t = time.time()
    ok = warmup_model()
    if not ok: raise Exception("warmup returned False")
    return f"{time.time()-t:.1f}s"
results.append(test("2. Model warmup", t2))

def t3():
    t = time.time()
    raw = "helo wrld"
    fixed = correct_text(raw, hwnd=999)
    if not fixed or fixed.lower().strip() == raw.lower().strip():
        raise Exception(f"No correction: got '{fixed}'")
    return f"'{raw}' -> '{fixed}'  ({time.time()-t:.1f}s)"
results.append(test("3. Basic typo fix", t3))

def t4():
    raw = "she go to the hosptial yestrday for a brokn arm"
    fixed = correct_text(raw, hwnd=998)
    if not fixed or fixed == raw:
        raise Exception(f"No change: '{fixed}'")
    fl = fixed.lower()
    for bad in ("hosptial", "yestrday", "brokn"):
        if bad in fl:
            raise Exception(f"Spelling should be fixed (use key 8 for grammar): '{fixed}'")
    return f"'{fixed[:55]}'"
results.append(test("4. Spelling fix (grammar via key 8)", t4))

def t5():
    from corrector import update_buffer
    update_buffer(777, "Hello world", "")
    raw2 = "Hello world thsi is nw"
    fixed = correct_text(raw2, hwnd=777)
    fl = fixed.lower()
    if "hello" not in fl:
        raise Exception(f"Opening mangled or dropped: '{fixed}'")
    if "this" not in fl:
        raise Exception(f"Incremental tail not corrected: '{fixed}'")
    if "thsi" in fl or " nw" in fl:
        raise Exception(f"Typos remain: '{fixed}'")
    return f"Buffer-ish preserved: '{fixed[:50]}'"
results.append(test("5. Incremental buffer", t5))

def t6():
    import pyperclip
    pyperclip.copy("test_sentinel_xyz")
    val = pyperclip.paste()
    if val != "test_sentinel_xyz":
        raise Exception("Clipboard broken")
    return "OK"
results.append(test("6. Clipboard read/write", t6))

def t7():
    s = stats()
    return (f"dict:{s['dictionary']} "
            f"abbrevs:{s['abbreviations']} "
            f"patterns:{s['patterns']}")
results.append(test("7. Memory store", t7))

print()
passed = sum(results)
total  = len(results)
print(f"  Result: {passed}/{total} passed")
if passed == total:
    print("  OK All good — run: python main.py (as Administrator)")
else:
    print("  FAIL Fix failures above before running Flow.")
print("=" * 55)
print()
