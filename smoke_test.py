"""
smoke_test.py — Run this before using FixIt to confirm everything works.
No GUI, no hotkeys. Pure logic test.
"""

import sys
import time

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
print("=" * 50)
print("  FixIt v2 — Smoke Test")
print("=" * 50)

from corrector import check_ollama, warmup_model, correct_text

results = []

# 1. Ollama reachable
def t1():
    ok, msg = check_ollama()
    if not ok: raise Exception(msg)
    return msg
results.append(test("1. Ollama check", t1))

# 2. Model warmup
def t2():
    t = time.time()
    ok = warmup_model()
    if not ok: raise Exception("warmup returned False")
    return f"{time.time()-t:.1f}s"
results.append(test("2. Model warmup", t2))

# 3. Basic typo fix
def t3():
    t = time.time()
    raw = "helo wrld"
    fixed = correct_text(raw)
    elapsed = time.time() - t
    if not fixed or fixed == raw:
        raise Exception(f"No correction: '{fixed}'")
    return f"'{raw}' → '{fixed}'  ({elapsed:.1f}s)"
results.append(test("3. Basic fix", t3))

# 4. Fast-typing style (your actual input)
def t4():
    raw = "i wsa tryign to tpye thsi bu tmy fingres are fsat"
    fixed = correct_text(raw)
    if not fixed or fixed == raw:
        raise Exception(f"No correction: '{fixed}'")
    return f"'{fixed[:50]}'"
results.append(test("4. Fast-typing fix", t4))

# 5. No elaboration guard
def t5():
    from corrector import SYSTEM_PROMPT
    if "do NOT rephrase" not in SYSTEM_PROMPT.upper() and "not rephrase" not in SYSTEM_PROMPT.lower():
        raise Exception("Elaboration guard missing from prompt")
    return "prompt has anti-elaboration rules"
results.append(test("5. Anti-elaboration guard", t5))

# 6. Clipboard not broken
def t6():
    import pyperclip
    pyperclip.copy("test_value_xyz")
    val = pyperclip.paste()
    if val != "test_value_xyz":
        raise Exception("Clipboard read/write broken")
    return "clipboard OK"
results.append(test("6. Clipboard r/w", t6))

print()
passed = sum(results)
total  = len(results)
print(f"  Result: {passed}/{total} passed")
if passed == total:
    print("  ✓ All good — FixIt should work.")
else:
    print("  ✗ Fix the failures above before running FixIt.")
print("=" * 50)
print()
