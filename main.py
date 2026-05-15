"""
Flow — Pipeline AI corrector.
Keystroke buffer → auto-chunks every ~20 chars (at last space before limit) → model (background).
Press 7: typo pipeline commit. Press 8: grammar pass on buffer (handled in hook, not add_hotkey).
Run as Administrator.
"""

import time
import sys
import threading
import ctypes
import tkinter as tk
from collections import deque

import keyboard
import win32gui
import win32api
import pyperclip

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from corrector import (
    correct_text,
    check_ollama,
    warmup_model,
    clear_buffer,
    grammar_correct,
    set_model,
    set_modes,
    set_cloud,
)
import corrector
from memory import stats as memory_stats

# ── Config ─────────────────────────────────────────────────────────────────────
CHUNK_SIZE = 20  # dispatch when buffer reaches this length; cuts at prior space (_maybe_chunk)
TRIGGER_KEY = "7"
GRAMMAR_KEY = "8"

# ── Global state ───────────────────────────────────────────────────────────────
BUSY = False
MODEL_LOADED = False
LAST_TARGET_HND = None
PANEL_HWND = None

# ── Keystroke buffer ───────────────────────────────────────────────────────────
_key_buffer: list[str] = []
_buffer_lock = threading.Lock()
_live_cb = None
_grammar_cb = None

# ── Pipeline queue ─────────────────────────────────────────────────────────────
_pipeline: deque = deque()
_pipe_lock = threading.Lock()
_hwnd_ref = [None]

# WPM tracking (space = word boundary)
_wpm_keystrokes: list[float] = []  # timestamps of each word-ending space
_wpm_lock = threading.Lock()
_WPM_WINDOW = 60.0  # rolling 60-second window


def get_foreground():
    return win32gui.GetForegroundWindow()


def _append_char(ch: str) -> str:
    if len(ch) != 1:
        return ch
    if ch.isalpha() and (
        keyboard.is_pressed("shift") or keyboard.is_pressed("right shift")
    ):
        return ch.upper()
    return ch


def _grammar_fix_dispatch():
    """Read directly from active field via clipboard. Corrects what's visible."""
    global BUSY, MODEL_LOADED

    hwnd = (_hwnd_ref[0] or None) or (LAST_TARGET_HND or None)
    if not hwnd:
        if _grammar_cb:
            _grammar_cb("✗ Grammar: no target window — click in a field first.")
        return

    if BUSY:
        if _grammar_cb:
            _grammar_cb("Still working — wait.")
        return

    BUSY = True
    saved = ""
    try:
        force_focus(hwnd)
        time.sleep(0.05)

        try:
            saved = pyperclip.paste()
        except Exception:
            saved = ""

        pyperclip.copy("~~FLOW_GRAMMAR~~")
        time.sleep(0.04)
        keyboard.send("ctrl+a")
        time.sleep(0.05)
        keyboard.send("ctrl+c")
        time.sleep(0.18)

        try:
            raw = pyperclip.paste()
        except Exception:
            raw = ""

        if not raw or raw == "~~FLOW_GRAMMAR~~" or not raw.strip():
            try:
                pyperclip.copy(saved)
            except Exception:
                pass
            return

        if _grammar_cb:
            _grammar_cb(f"Grammar: {raw[:50]}")

        if not MODEL_LOADED:
            if corrector._USE_CLOUD:
                MODEL_LOADED = True
            else:
                if _grammar_cb:
                    _grammar_cb("→ Loading model...")
                ok = warmup_model()
                MODEL_LOADED = ok
                if not ok:
                    if _grammar_cb:
                        _grammar_cb("✗ Ollama not ready.")
                    try:
                        pyperclip.copy(saved)
                    except Exception:
                        pass
                    return

        fixed = grammar_correct(raw, hwnd=hwnd)

        if not fixed or fixed.strip() == raw.strip():
            try:
                pyperclip.copy(saved)
            except Exception:
                pass
            return

        pyperclip.copy(fixed)
        time.sleep(0.04)
        keyboard.send("ctrl+a")
        time.sleep(0.04)
        keyboard.send("ctrl+v")
        time.sleep(0.06)

        def _restore():
            time.sleep(0.8)
            try:
                pyperclip.copy(saved)
            except Exception:
                pass

        threading.Thread(target=_restore, daemon=True).start()

        clear_key_buffer()
        with _pipe_lock:
            _pipeline.clear()

        if _grammar_cb:
            _grammar_cb("✓ Grammar done.")
    except Exception as e:
        if _grammar_cb:
            _grammar_cb(f"✗ Grammar error: {e}")
        import traceback

        traceback.print_exc()
        try:
            pyperclip.copy(saved)
        except Exception:
            pass
    finally:
        BUSY = False


def _on_key_event(event):
    global _key_buffer, _live_cb
    if event.event_type != "down":
        return

    try:
        if PANEL_HWND and get_foreground() == PANEL_HWND:
            return
    except Exception:
        pass

    name = event.name
    if name == TRIGGER_KEY:
        return
    if name == GRAMMAR_KEY:
        threading.Thread(target=_grammar_fix_dispatch, daemon=True).start()
        return

    with _buffer_lock:
        if name == "backspace":
            if _key_buffer:
                _key_buffer.pop()
        elif name in ("enter", "return"):
            _key_buffer.clear()
            with _pipe_lock:
                _pipeline.clear()
        elif name == "space":
            _key_buffer.append(" ")
            _maybe_chunk()
            now = time.time()
            with _wpm_lock:
                _wpm_keystrokes.append(now)
                cutoff = now - _WPM_WINDOW
                while _wpm_keystrokes and _wpm_keystrokes[0] < cutoff:
                    _wpm_keystrokes.pop(0)
        elif name == "tab":
            _key_buffer.append(" ")
        elif len(name) == 1:
            _key_buffer.append(_append_char(name))
            if len(_key_buffer) % CHUNK_SIZE == 0:
                _maybe_chunk()

    if _live_cb:
        try:
            text = "".join(_key_buffer)
            _live_cb(text[-70:])
        except Exception:
            pass


def _maybe_chunk():
    """Emit a chunk ending at or before CHUNK_SIZE, never before the last internal space."""
    global _key_buffer
    text = "".join(_key_buffer)
    if len(text) < CHUNK_SIZE:
        return

    chunk_end = len(text)
    last_space = text.rfind(" ", 0, CHUNK_SIZE + 1)
    if last_space > 0:
        chunk_end = last_space + 1

    chunk_raw = text[:chunk_end]
    _key_buffer = list(text[chunk_end:])

    _dispatch_chunk(chunk_raw)


def get_buffer_text() -> str:
    with _buffer_lock:
        return "".join(_key_buffer).strip()


def clear_key_buffer():
    with _buffer_lock:
        _key_buffer.clear()


def get_wpm() -> int:
    now = time.time()
    cutoff = now - _WPM_WINDOW
    with _wpm_lock:
        recent = [t for t in _wpm_keystrokes if t > cutoff]
    if len(recent) < 2:
        return 0
    elapsed = recent[-1] - recent[0]
    if elapsed < 1:
        return 0
    return int((len(recent) / elapsed) * 60)


def _dispatch_chunk(raw: str):
    if not raw.strip():
        return

    entry = {"raw": raw, "fixed": None, "done": threading.Event()}
    with _pipe_lock:
        _pipeline.append(entry)

    def _work():
        hwnd = _hwnd_ref[0] or 0
        print(f"[pipeline] Processing chunk: '{raw[:50]}'")
        result = correct_text(raw, hwnd=hwnd)
        entry["fixed"] = result
        entry["done"].set()
        print(f"[pipeline] Done: '{result[:50] if result else ''}'")

    threading.Thread(target=_work, daemon=True).start()


def _flush_pipeline(hwnd: int, log_fn) -> tuple[str, str]:
    tail_raw = get_buffer_text()
    if tail_raw:
        _dispatch_chunk(tail_raw)
        clear_key_buffer()

    with _pipe_lock:
        entries = list(_pipeline)
        _pipeline.clear()

    if not entries:
        return "", ""

    for entry in entries:
        entry["done"].wait(timeout=8.0)

    raw_parts = [e["raw"] for e in entries]
    fixed_parts = [(e["fixed"] or e["raw"]) for e in entries]

    full_raw = "".join(raw_parts)
    full_fixed = " ".join(p.strip() for p in fixed_parts)

    return full_raw.strip(), full_fixed.strip()


def force_focus(hwnd: int):
    try:
        fg_tid = win32api.GetWindowThreadProcessId(get_foreground())[0]
        our_tid = win32api.GetCurrentThreadId()
        attached = False
        if fg_tid != our_tid:
            ctypes.windll.user32.AttachThreadInput(fg_tid, our_tid, True)
            attached = True
        win32gui.SetForegroundWindow(hwnd)
        if attached:
            ctypes.windll.user32.AttachThreadInput(fg_tid, our_tid, False)
    except Exception:
        pass
    time.sleep(0.08)


def replace_text(hwnd: int, raw: str, fixed: str):
    """Delete current line from caret back (Shift+Home), paste fixed. Clipboard restored."""
    _ = raw  # API parity; assumes caret at end of the corrected chunk on this line.
    force_focus(hwnd)
    time.sleep(0.05)

    try:
        saved = pyperclip.paste()
    except Exception:
        saved = ""

    pyperclip.copy(fixed)
    time.sleep(0.04)

    keyboard.send("shift+home")
    time.sleep(0.03)
    keyboard.send("delete")
    time.sleep(0.04)

    keyboard.send("ctrl+v")
    time.sleep(0.06)

    def _restore():
        time.sleep(0.8)
        try:
            pyperclip.copy(saved)
        except Exception:
            pass

    threading.Thread(target=_restore, daemon=True).start()


def do_fix(hwnd: int, log_fn):
    global BUSY, MODEL_LOADED

    if BUSY:
        log_fn("Still working — wait.")
        return
    BUSY = True

    try:
        if not MODEL_LOADED:
            if corrector._USE_CLOUD:
                MODEL_LOADED = True
            else:
                log_fn("→ Loading model (~4s once)...")
                ok = warmup_model()
                MODEL_LOADED = ok
                if not ok:
                    log_fn("✗ Ollama not ready. Run: ollama pull qwen2.5:7b (or qwen2.5:1.5b)")
                    return
                log_fn("✓ Model loaded.")

        log_fn("→ Collecting chunks...")
        full_raw, full_fixed = _flush_pipeline(hwnd, log_fn)

        if not full_raw:
            log_fn("✗ Nothing in buffer — type something first.")
            return

        log_fn(f"Raw:   {full_raw[:80]}")

        if not full_fixed or full_fixed.strip() == full_raw.strip():
            log_fn("✓ Already correct.")
            return

        log_fn(f"Fixed: {full_fixed[:80]}")
        replace_text(hwnd, full_raw, full_fixed)
        log_fn("✓ Done.")

    except Exception as e:
        log_fn(f"✗ Error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        BUSY = False


class FlowPanel:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Flow")
        self.root.geometry("400x500")
        self.root.resizable(False, False)
        self.root.configure(bg="#0a0a0a")

        self.root.after(150, self._store_panel_hwnd)

        tk.Label(
            self.root,
            text="Flow",
            bg="#0a0a0a",
            fg="#22c55e",
            font=("Consolas", 15, "bold"),
        ).pack(pady=(12, 0))

        top_row = tk.Frame(self.root, bg="#0a0a0a")
        top_row.pack(fill="x", padx=12, pady=(2, 0))
        tk.Label(
            top_row,
            text="7 = typo pipeline  |  8 = grammar (buffer)",
            bg="#0a0a0a",
            fg="#2a2a2a",
            font=("Consolas", 8),
        ).pack(side="left")

        self._pinned = False
        self.pin_btn = tk.Button(
            top_row,
            text="pin",
            command=self._toggle_pin,
            bg="#1a1a1a",
            fg="#555555",
            font=("Consolas", 8),
            relief="flat",
            cursor="hand2",
            padx=6,
            pady=1,
        )
        self.pin_btn.pack(side="right")

        tk.Label(
            self.root,
            text="Listening:",
            bg="#0a0a0a",
            fg="#444444",
            font=("Consolas", 7),
        ).pack(pady=(10, 0), padx=12, anchor="w")

        self.live_var = tk.StringVar(value="")
        self.live_label = tk.Label(
            self.root,
            textvariable=self.live_var,
            bg="#111111",
            fg="#22c55e",
            font=("Consolas", 9),
            anchor="w",
            wraplength=372,
            justify="left",
            padx=6,
            pady=5,
        )
        self.live_label.pack(padx=12, fill="x")

        tk.Label(
            self.root,
            text="Pipeline:",
            bg="#0a0a0a",
            fg="#444444",
            font=("Consolas", 7),
        ).pack(pady=(6, 0), padx=12, anchor="w")

        self.pipe_var = tk.StringVar(value="idle")
        self.pipe_var_label = tk.Label(
            self.root,
            textvariable=self.pipe_var,
            bg="#111111",
            fg="#f59e0b",
            font=("Consolas", 8),
            anchor="w",
            wraplength=372,
            justify="left",
            padx=6,
            pady=3,
        )
        self.pipe_var_label.pack(padx=12, fill="x")

        tk.Label(
            self.root,
            text="WPM:",
            bg="#0a0a0a",
            fg="#444444",
            font=("Consolas", 7),
        ).pack(pady=(4, 0), padx=12, anchor="w")

        wpm_row = tk.Frame(self.root, bg="#0a0a0a")
        wpm_row.pack(padx=12, fill="x")

        self.wpm_var = tk.StringVar(value="0 wpm")
        self.wpm_main_label = tk.Label(
            wpm_row,
            textvariable=self.wpm_var,
            bg="#111111",
            fg="#f97316",
            font=("Consolas", 22, "bold"),
            anchor="w",
            padx=8,
            pady=4,
        )
        self.wpm_main_label.pack(side="left", fill="x", expand=True)

        self.wpm_peak_var = tk.StringVar(value="peak: 0")
        tk.Label(
            wpm_row,
            textvariable=self.wpm_peak_var,
            bg="#111111",
            fg="#333333",
            font=("Consolas", 8),
            anchor="e",
            padx=8,
        ).pack(side="right")

        self._wpm_peak = 0
        self._update_wpm()

        self.log_box = tk.Text(
            self.root,
            height=4,
            width=48,
            bg="#111111",
            fg="#22c55e",
            font=("Consolas", 8),
            relief="flat",
            bd=0,
            state="disabled",
        )
        self.log_box.pack(padx=12, pady=6)

        self._set_accent("#22c55e")

        tk.Button(
            self.root,
            text="▶  COMMIT FIX  (press 7)",
            command=self._on_fix_now,
            bg="#22c55e",
            fg="#000000",
            font=("Consolas", 10, "bold"),
            relief="flat",
            cursor="hand2",
            pady=8,
        ).pack(padx=12, pady=(0, 4), fill="x")

        tk.Button(
            self.root,
            text="↺  Clear (new sentence)",
            command=self._on_clear,
            bg="#1a1a1a",
            fg="#555555",
            font=("Consolas", 8),
            relief="flat",
            cursor="hand2",
            pady=3,
        ).pack(padx=12, pady=(0, 4), fill="x")

        self._high_model = False
        self.model_btn = tk.Button(
            self.root,
            text="⚡ Low quality (fast)",
            command=self._toggle_model,
            bg="#1a1a1a",
            fg="#555555",
            font=("Consolas", 8),
            relief="flat",
            cursor="hand2",
            pady=3,
        )
        self.model_btn.pack(padx=12, pady=(0, 4), fill="x")

        # ── Mode toggles ──────────────────────────────────────────────────────
        modes_frame = tk.Frame(self.root, bg="#0a0a0a")
        modes_frame.pack(padx=12, pady=(0, 6), fill="x")

        self._mode_spelling = True
        self._mode_semantic = False
        self._mode_grammar = False

        self.btn_spelling = tk.Button(
            modes_frame,
            text="✓ Spelling",
            command=lambda: self._toggle_mode("spelling"),
            bg="#0f2a1a",
            fg="#22c55e",
            font=("Consolas", 8),
            relief="flat",
            cursor="hand2",
            pady=3,
            padx=8,
        )
        self.btn_spelling.pack(side="left", expand=True, fill="x", padx=(0, 2))

        self.btn_semantic = tk.Button(
            modes_frame,
            text="○ Semantic",
            command=lambda: self._toggle_mode("semantic"),
            bg="#1a1a1a",
            fg="#555555",
            font=("Consolas", 8),
            relief="flat",
            cursor="hand2",
            pady=3,
            padx=8,
        )
        self.btn_semantic.pack(side="left", expand=True, fill="x", padx=2)

        self.btn_grammar = tk.Button(
            modes_frame,
            text="○ Grammar",
            command=lambda: self._toggle_mode("grammar"),
            bg="#1a1a1a",
            fg="#555555",
            font=("Consolas", 8),
            relief="flat",
            cursor="hand2",
            pady=3,
            padx=8,
        )
        self.btn_grammar.pack(side="left", expand=True, fill="x", padx=(2, 0))

        self._cloud_mode = False
        self.cloud_btn = tk.Button(
            self.root,
            text="○  Cloud (Claude API)",
            command=self._toggle_cloud,
            bg="#1a1a1a",
            fg="#555555",
            font=("Consolas", 8),
            relief="flat",
            cursor="hand2",
            pady=3,
        )
        self.cloud_btn.pack(padx=12, pady=(0, 6), fill="x")

        self.info_var = tk.StringVar(value="Checking Ollama...")
        tk.Label(
            self.root,
            textvariable=self.info_var,
            bg="#0a0a0a",
            fg="#333333",
            font=("Consolas", 7),
        ).pack(padx=12, anchor="w")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._track_focus()
        self._watch_pipeline()

        global _live_cb, _grammar_cb
        _live_cb = lambda t: self.root.after(0, lambda: self.live_var.set(t))
        _grammar_cb = self.log

        keyboard.hook(_on_key_event)

        try:
            keyboard.add_hotkey(TRIGGER_KEY, self._hotkey_fired, suppress=True)
            self.log(
                f"Listening. {TRIGGER_KEY} = typo commit (pipeline), "
                f"{GRAMMAR_KEY} = grammar on buffer."
            )
        except Exception as e:
            self.log(f"Hotkey failed: {e} — run as Admin.")

        self.root.after(
            600,
            lambda: threading.Thread(target=self._startup_checks, daemon=True).start(),
        )
        self.root.after(
            800,
            lambda: threading.Thread(target=self._warmup, daemon=True).start(),
        )

        self._sync_modes()

    def _on_close(self):
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        self.root.destroy()

    def _toggle_mode(self, mode: str):
        if mode == "spelling":
            self._mode_spelling = not self._mode_spelling
            active = self._mode_spelling
            btn = self.btn_spelling
        elif mode == "semantic":
            self._mode_semantic = not self._mode_semantic
            active = self._mode_semantic
            btn = self.btn_semantic
        else:
            self._mode_grammar = not self._mode_grammar
            active = self._mode_grammar
            btn = self.btn_grammar

        if active:
            btn.config(
                bg="#0f2a1a",
                fg="#22c55e",
                text=f"✓ {mode.capitalize()}",
            )
        else:
            btn.config(
                bg="#1a1a1a",
                fg="#555555",
                text=f"○ {mode.capitalize()}",
            )

        self.log(f"{'ON' if active else 'OFF'} — {mode}")
        self._sync_modes()

    def _sync_modes(self):
        set_modes(
            spelling=self._mode_spelling,
            semantic=self._mode_semantic,
            grammar=self._mode_grammar,
        )

    def _toggle_pin(self):
        self._pinned = not self._pinned
        self.root.attributes("-topmost", self._pinned)
        if self._pinned:
            self.pin_btn.config(text="unpin", fg="#22c55e", bg="#0f2a1a")
        else:
            self.pin_btn.config(text="pin", fg="#555555", bg="#1a1a1a")

    def _toggle_model(self):
        global MODEL_LOADED
        self._high_model = not self._high_model
        set_model(self._high_model)
        MODEL_LOADED = False
        if self._high_model:
            self.model_btn.config(
                text="🧠 High quality (7b)",
                fg="#22c55e",
                bg="#0f2a1a",
            )
        else:
            self.model_btn.config(
                text="⚡ Low quality (fast)",
                fg="#555555",
                bg="#1a1a1a",
            )
        if not self._cloud_mode:
            if self._high_model:
                self._set_accent("#f97316")
            else:
                self._set_accent("#22c55e")
        self.log(f"Model → {'7b HIGH' if self._high_model else '1.5b fast'}")

        if corrector._USE_CLOUD:
            MODEL_LOADED = True
        else:

            def _warm():
                global MODEL_LOADED
                ok = warmup_model()
                MODEL_LOADED = ok

            threading.Thread(target=_warm, daemon=True).start()

        ok, _msg = check_ollama()
        s = memory_stats()
        foot = (
            f"Ollama: {'OK ✓' if ok else 'MISSING ✗'} | "
            f"{corrector.MODEL} | Dict:{s['dictionary']} | Patterns:{s['patterns']}"
        )
        self.root.after(0, lambda: self.info_var.set(foot))

    def _toggle_cloud(self):
        global MODEL_LOADED
        self._cloud_mode = not self._cloud_mode
        set_cloud(self._cloud_mode)
        if self._cloud_mode:
            MODEL_LOADED = True
            self.cloud_btn.config(
                text="✓  Cloud (Claude API)",
                fg="#818cf8",
                bg="#1e1b4b",
            )
            self._set_accent("#818cf8")
            self.log("Cloud ON — routing to Claude API.")
        else:
            MODEL_LOADED = False
            self.cloud_btn.config(
                text="○  Cloud (Claude API)",
                fg="#555555",
                bg="#1a1a1a",
            )
            color = "#f97316" if corrector.MODEL == corrector.MODEL_HIGH else "#22c55e"
            self._set_accent(color)
            self.log("Cloud OFF — back to local Ollama.")

    def _set_accent(self, color: str):
        """Recolor typing/listening accents (green = 1.5b, orange = 7b, indigo = cloud)."""
        self.log_box.config(fg=color)
        self.live_label.config(fg=color)
        self.pipe_var_label.config(fg=color)

    def _warmup(self):
        global MODEL_LOADED
        if MODEL_LOADED:
            return
        if corrector._USE_CLOUD:
            MODEL_LOADED = True
            self.log("✓ Cloud mode — skipping local warmup.")
            self.root.after(0, lambda: self._set_accent("#818cf8"))
            return
        self.log("→ Warming up model...")
        ok = warmup_model()
        MODEL_LOADED = ok
        self.log(
            "✓ Model warm — zero wait on first fix." if ok else "✗ Ollama warmup failed."
        )
        # Set accent color based on whichever model is active at launch
        from corrector import MODEL, MODEL_HIGH

        color = "#f97316" if MODEL == MODEL_HIGH else "#22c55e"
        self.root.after(
            0,
            lambda c=color: self._set_accent(c) if not corrector._USE_CLOUD else None,
        )

    def _store_panel_hwnd(self):
        global PANEL_HWND
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, "Flow")
            if hwnd:
                PANEL_HWND = hwnd
        except Exception:
            pass

    def _track_focus(self):
        global LAST_TARGET_HND
        try:
            hwnd = get_foreground()
            if hwnd and hwnd != PANEL_HWND and hwnd != 0:
                if LAST_TARGET_HND != hwnd:
                    title = win32gui.GetWindowText(hwnd)
                    print(f"[Flow] Target → {hwnd}: '{title}'")
                LAST_TARGET_HND = hwnd
                _hwnd_ref[0] = hwnd
        except Exception:
            pass
        self.root.after(200, self._track_focus)

    def _update_wpm(self):
        try:
            wpm = get_wpm()
            self.wpm_var.set(f"{wpm} wpm")
            if wpm > self._wpm_peak:
                self._wpm_peak = wpm
                self.wpm_peak_var.set(f"peak: {wpm}")
            if wpm >= 120:
                color = "#22c55e"  # green — stenographer speed
            elif wpm >= 80:
                color = "#f97316"  # orange — fast
            elif wpm >= 40:
                color = "#facc15"  # yellow — average
            else:
                color = "#555555"  # grey — slow
            self.wpm_main_label.config(fg=color)
        except tk.TclError:
            return
        self.root.after(500, self._update_wpm)

    def _watch_pipeline(self):
        with _pipe_lock:
            n = len(_pipeline)
            done = sum(1 for e in _pipeline if e["done"].is_set())
        if n == 0:
            self.pipe_var.set("idle")
        else:
            self.pipe_var.set(f"{done}/{n} chunks processed")
        self.root.after(300, self._watch_pipeline)

    def _startup_checks(self):
        ok, msg = check_ollama()
        s = memory_stats()
        info = (
            f"Ollama: {'OK ✓' if ok else 'MISSING ✗'} | "
            f"{corrector.MODEL} | Dict:{s['dictionary']} | Patterns:{s['patterns']}"
        )
        self.root.after(0, lambda: self.info_var.set(info))
        self.root.after(0, lambda m=corrector.MODEL: self.log(f"Active model: {m}"))
        if not ok:
            self.log("Ollama missing — see README.")
        color = (
            "#f97316" if corrector.MODEL == corrector.MODEL_HIGH else "#22c55e"
        )
        self.root.after(0, lambda c=color: self._set_accent(c))
        if (
            corrector.ANTHROPIC_KEY
            and corrector.ANTHROPIC_KEY.strip()
            and corrector.ANTHROPIC_KEY.strip() != "your_key_here"
        ):
            self.log("Claude API key found — Cloud mode available.")
        else:
            self.log("No API key — add ANTHROPIC_API_KEY to .env for Cloud mode.")

    def log(self, msg: str):
        print(f"[Flow] {msg}")

        def _ui():
            self.log_box.config(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.config(state="disabled")

        try:
            self.root.after(0, _ui)
        except Exception:
            pass

    def _hotkey_fired(self):
        target = LAST_TARGET_HND
        if not target:
            self.log("No target window tracked.")
            return
        threading.Thread(target=do_fix, args=(target, self.log), daemon=True).start()

    def _on_fix_now(self):
        target = LAST_TARGET_HND
        if not target:
            self.log("Click in a text field first.")
            return
        threading.Thread(target=do_fix, args=(target, self.log), daemon=True).start()

    def _on_clear(self):
        clear_key_buffer()
        with _pipe_lock:
            _pipeline.clear()
        if LAST_TARGET_HND:
            clear_buffer(LAST_TARGET_HND)
        self.log("Cleared.")
        self.live_var.set("")
        self.pipe_var.set("idle")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if not bool(ctypes.windll.shell32.IsUserAnAdmin()):
        print("[Flow] ⚠  Run as Administrator for system-wide access.")
        print()
    FlowPanel().run()
