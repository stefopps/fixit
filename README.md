# FixIt v2

Type fast and messy anywhere. Press **Ctrl+7** to fix the current line instantly.
Runs fully offline after setup — no internet, no API keys.

---

## Setup (one time)

### 1. Ollama
Download: https://ollama.com/download  
Install it. It runs as a background service automatically.

### 2. Pull the model (once, ~1GB)
```
ollama pull qwen2.5:1.5b
```

### 3. Install Python deps
```
pip install -r requirements.txt
```

### 4. Smoke test (confirm everything works)
```
python smoke_test.py
```
All 6 should pass before you run FixIt.

### 5. Run FixIt as Administrator
Right-click your terminal → Run as Administrator
```
python main.py
```

---

## How to use

1. Click inside any text field (Notepad, Chrome, Slack, VS Code, etc.)
2. Type whatever you want — fast and messy is fine
3. Press **Ctrl+7**
4. FixIt selects the current line, sends it to the local AI, replaces it with corrected text
5. Watch the FixIt panel for Raw → Fixed output

**Important:** Click in your text field first. Don't click the FixIt panel or console before triggering — that moves focus away from where you're typing.

---

## What works

- Notepad ✓
- Chrome / Edge (address bar, text boxes) ✓
- Slack, Discord, Teams ✓
- VS Code / Cursor ✓
- Word, Google Docs ✓
- Email compose ✓

---

## Timing

- First fix after startup: ~4s (model loads into RAM)
- All subsequent fixes: ~2s (model stays hot)
- Ollama must be running (background service — starts with Windows after install)

---

## Troubleshooting

**Nothing captured**
→ You pressed Ctrl+7 while the FixIt window or console had focus
→ Click inside Notepad (or wherever) first, then Ctrl+7

**Ctrl+C / Ctrl+V broken**
→ Make sure you're on v2 — the old version had a global hook that broke these
→ v2 does NOT suppress any keys

**Hotkey not firing**
→ Run as Administrator

**Text goes in wrong place / doubles up**
→ Wait for "Done" before pressing Ctrl+7 again

**Model slow**
→ Normal on CPU — first fix is ~4s, then ~2s steady
→ Close other heavy apps to free RAM
