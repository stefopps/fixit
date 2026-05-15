# FixIt — AI Typo + Grammar Corrector

Local, offline, system-wide. Press Ctrl+7 to fix any text field instantly.

---

## First-time setup

### 1. Ollama
https://ollama.com/download — installs as a background service.

### 2. Pull model (once, ~1GB)
```
ollama pull qwen2.5:1.5b
```

### 3. Install Python deps
```
pip install -r requirements.txt
```

### 4. Build medical dictionary (once)
```
python build_dictionary.py
```
Downloads ~500 medical terms + abbreviations from GitHub into memory.json.

### 5. Smoke test
```
python smoke_test.py
```
All 7 must pass.

### 6. Run
Double-click `START_FIXIT.bat` — auto-elevates to Administrator.
Or manually:
```
# Right-click terminal → Run as Administrator
cd C:\Users\steve\fixit
python main.py
```

---

## How to use

1. Click inside any text field (Notepad, Chrome, Slack, VS Code, email...)
2. Type fast and messy
3. Press **Ctrl+7**
4. FixIt captures the line, fixes typos AND grammar, types it back
5. Press **Ctrl+7** again after typing more — it only fixes the NEW part

**Clear buffer button** — press when starting a new paragraph so FixIt
starts fresh instead of trying to extend the previous line.

**Ctrl+Z** — undoes the correction in any app (standard undo).

---

## How it learns

Every correction is logged to memory.json.
After you make the same typo 2+ times, FixIt corrects it instantly
without hitting Ollama — sub-10ms.

To add your own medical terms:
- Open memory.json in Notepad
- Add words to the "dictionary" array
- Save — takes effect immediately, no restart needed

---

## What's in memory.json

```json
{
  "dictionary": ["endotracheal", "cricothyrotomy", ...],
  "abbreviations": {"SpO2": "oxygen saturation", ...},
  "patterns": {"hwo": {"fixed": "how", "count": 4}},
  "corrections_log": [...]
}
```

---

## Troubleshooting

**Nothing captured** → You pressed Ctrl+7 while FixIt panel had focus.
Click in your text field first, then Ctrl+7.

**Ctrl+C / Ctrl+V broken** → Restart FixIt. You may have an old version running.

**Hotkey not working** → Must run as Administrator (use START_FIXIT.bat).

**Text inserted in wrong place** → Wait for "Done" before pressing Ctrl+7 again.

**Model slow first time** → Normal. ~4s first fix, ~2s after model is warm.
