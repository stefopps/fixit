# Changelog

All notable changes to FixIt in this folder are listed here. Use this when you want a **small, reversible step** or to tell an AI what to roll back.

Format: **date → what changed → why** (one idea per bullet when possible).

---

## [Unreleased]

- (Add entries below as you go; keep each bullet one logical change.)

### Source of truth / backup

- **GitHub** is the canonical backup for the code (not a duplicate folder in the repo). Repo: https://github.com/stefopps/fixit — tag `baseline-2026-05-15` marks the initial pushed baseline.

---

## 2026-05-15

### Current behavior (as of last update)

- **Hotkey:** `Ctrl+7` (via `keyboard.add_hotkey("ctrl+7", …)`).
- **Window:** FixIt panel is **not** always-on-top (`-topmost` removed) to reduce focus stealing during capture.
- **Target window on hotkey:** Uses **`LAST_TARGET_HND`** only — the last foreground window that was not the FixIt panel — so the hook does not rely on `GetForegroundWindow()` at hotkey time.
- **Panel detection:** `_store_hwnd` uses **`FindWindowW(None, "FixIt v2")`** so the tracker skips the FixIt window reliably.
- **Tracker:** Saves target every ~200 ms when foreground ≠ FixIt; optional console prints when the target HWND changes or when hotkey fires.
- **Capture / replace:** Classic **End → Shift+Home → Ctrl+C** line flow; **`do_fix(hwnd, log_fn)`** — no `preview_fn` in this revision.

### Earlier experiments (removed or superseded — restore from git/message history if needed)

- **Bare `7` hotkey:** Tried global digit key; interfered with typing; superseded by `Ctrl+7`.
- **UI previews:** Dedicated “Captured / Corrected” text areas + larger window — removed when reverting to the slimmer Control+7 baseline.
- **Richer capture:** `GetGUIThreadInfo` + focused control + line-then–`Ctrl+A` field fallback — removed in favor of the simpler line-only flow in current `main.py`.

### Operational notes

- Run **as Administrator** for reliable hooks in some apps.
- **Smoke test:** `python smoke_test.py` — on Windows consoles, UTF-8 may be required for Unicode in print output (e.g. `PYTHONUTF8=1`, `chcp 65001`).

---

## How to revert quickly

1. **Git:** `git log --oneline` → `git checkout <commit> -- main.py` (or `git revert` if already pushed).
2. **This file:** Find the bullet for the behavior you want and ask to restore “main.py as described under that date/section.”
3. **Copy/paste:** Keep a known-good `main.py` snippet in a gist or chat and replace the file.

---

## Baseline tag (optional)

If you use git locally, consider:

```text
git tag fixit-baseline-2026-05-15
```

after a version you trust, so `git reset --hard fixit-baseline-2026-05-15` restores it.
