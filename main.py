"""
FixIt v2 — System-wide AI typo corrector. Clean rebuild.
Hotkey: Ctrl+7 (won't conflict with anything)
Flow:   grab window → select line → copy → fix → delete line → type back
No global hooks. No clipboard hijacking. No background thread races.
Run as Administrator for system-wide access.
"""

import time
import sys
import threading
import ctypes
import tkinter as tk

import pyperclip
import keyboard
import win32gui
import win32api
import win32con
from PIL import Image, ImageDraw
import pystray

from corrector import correct_text, check_ollama, warmup_model

# ── Global state ───────────────────────────────────────────────────────────────
BUSY            = False
MODEL_LOADED    = False
LAST_TARGET_HND = None   # last non-FixIt window with focus

# ── Win32 focus helpers ────────────────────────────────────────────────────────

def get_foreground_hwnd():
    return win32gui.GetForegroundWindow()

def force_focus(hwnd):
    """Bring hwnd to foreground reliably."""
    try:
        # Attach thread input so SetForegroundWindow is allowed
        fg_tid  = win32api.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[0]
        our_tid = win32api.GetCurrentThreadId()
        if fg_tid != our_tid:
            ctypes.windll.user32.AttachThreadInput(fg_tid, our_tid, True)
        win32gui.SetForegroundWindow(hwnd)
        if fg_tid != our_tid:
            ctypes.windll.user32.AttachThreadInput(fg_tid, our_tid, False)
    except Exception:
        pass
    time.sleep(0.10)

# ── Capture current line ───────────────────────────────────────────────────────

def capture_line(hwnd) -> str | None:
    """
    Focus hwnd, move to end of line, select to home, copy.
    Restores clipboard immediately.  Returns stripped text or None.
    """
    force_focus(hwnd)

    # Save clipboard
    try:    saved_clip = pyperclip.paste()
    except: saved_clip = ""

    pyperclip.copy("\x00")           # sentinel — clear clipboard
    time.sleep(0.05)

    keyboard.send("end")             # go to end of line
    time.sleep(0.06)
    keyboard.send("shift+home")      # select back to start
    time.sleep(0.06)
    keyboard.send("ctrl+c")          # copy selection
    time.sleep(0.18)                 # give clipboard time to update

    try:    captured = pyperclip.paste()
    except: captured = ""

    # Restore original clipboard right away
    try:    pyperclip.copy(saved_clip)
    except: pass

    if not captured or captured == "\x00" or not captured.strip():
        return None
    return captured.strip()

# ── Replace current line ───────────────────────────────────────────────────────

def replace_line(hwnd, fixed: str):
    """
    Focus hwnd, re-select the line, delete it, type corrected text in chunks.
    Never uses Ctrl+V — pure keystroke injection.
    """
    force_focus(hwnd)

    keyboard.send("end")
    time.sleep(0.05)
    keyboard.send("shift+home")
    time.sleep(0.05)
    keyboard.send("delete")          # delete selection
    time.sleep(0.05)

    # Type back in small chunks with tiny delay — feels natural, works everywhere
    chunk = 10
    for i in range(0, len(fixed), chunk):
        keyboard.write(fixed[i:i+chunk], delay=0.005)
    keyboard.send("end")             # cursor to end

# ── Core fix pipeline ──────────────────────────────────────────────────────────

def do_fix(hwnd: int, log_fn):
    global BUSY, MODEL_LOADED

    if BUSY:
        log_fn("Still working — please wait.")
        return
    BUSY = True

    try:
        log_fn("→ Capturing line...")
        text = capture_line(hwnd)

        if not text:
            log_fn("✗ Nothing captured. Click INSIDE a text field, then trigger.")
            return

        log_fn(f"Raw:   {text[:90]}")

        if not MODEL_LOADED:
            log_fn("→ Loading model (~4s, first time only)...")
            ok = warmup_model()
            MODEL_LOADED = ok
            if not ok:
                log_fn("✗ Ollama not ready. Check setup.")
                return
            log_fn("✓ Model loaded.")

        fixed = correct_text(text)

        if not fixed or not fixed.strip():
            log_fn("✗ AI returned empty — try again.")
            return

        if fixed.strip() == text.strip():
            log_fn("✓ No changes needed.")
            return

        log_fn(f"Fixed: {fixed[:90]}")
        replace_line(hwnd, fixed)
        log_fn("✓ Done.")

    except Exception as e:
        log_fn(f"✗ Error: {e}")
        import traceback; traceback.print_exc()
    finally:
        BUSY = False

# ── GUI panel ──────────────────────────────────────────────────────────────────

class FixItPanel:
    PANEL_HWND = None   # set after window created

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("FixIt v2")
        self.root.geometry("340x240")
        self.root.resizable(False, False)
        # NO topmost — it steals focus and breaks capture
        self.root.configure(bg="#0d0d0d")

        # Store panel hwnd immediately via winfo_id after mainloop starts
        self.root.after(100, self._store_hwnd)

        # ── Layout ──────────────────────────────────────
        tk.Label(
            self.root, text="FixIt  v2",
            bg="#0d0d0d", fg="#22c55e",
            font=("Consolas", 13, "bold")
        ).pack(pady=(12, 2))

        self.status_var = tk.StringVar(value="Click in your text field → Ctrl+7")
        tk.Label(
            self.root, textvariable=self.status_var,
            bg="#0d0d0d", fg="#888888",
            font=("Consolas", 8), wraplength=320, justify="left"
        ).pack(padx=12, anchor="w")

        # Log
        self.log_box = tk.Text(
            self.root, height=4, width=42,
            bg="#161616", fg="#22c55e",
            font=("Consolas", 8),
            relief="flat", bd=0, state="disabled"
        )
        self.log_box.pack(padx=12, pady=6)

        # Fix Now button
        tk.Button(
            self.root,
            text="▶  FIX NOW   (Ctrl+7)",
            command=self._on_fix_now,
            bg="#22c55e", fg="#000000",
            font=("Consolas", 10, "bold"),
            relief="flat", cursor="hand2",
            pady=7
        ).pack(padx=12, pady=(2, 10), fill="x")

        # Ollama status
        self.ollama_var = tk.StringVar(value="Ollama: checking...")
        tk.Label(
            self.root, textvariable=self.ollama_var,
            bg="#0d0d0d", fg="#444444",
            font=("Consolas", 7)
        ).pack(padx=12, anchor="w")

        # ── Focus tracker ────────────────────────────────
        self._track_focus()

        # ── Hotkey ───────────────────────────────────────
        try:
            keyboard.add_hotkey("ctrl+7", self._hotkey_fired, suppress=False)
            self.log("Hotkey Ctrl+7 registered. Ready.")
        except Exception as e:
            self.log(f"Hotkey failed: {e}  →  Run as Administrator.")

        # ── Ollama check ─────────────────────────────────
        self.root.after(600, lambda: threading.Thread(
            target=self._check_ollama, daemon=True).start())

    def _store_hwnd(self):
        try:
            # FindWindow by exact title — most reliable way
            hwnd = ctypes.windll.user32.FindWindowW(None, "FixIt v2")
            if hwnd:
                FixItPanel.PANEL_HWND = hwnd
                print(f"[FixIt] Panel HWND: {hwnd}")
        except Exception as e:
            print(f"[FixIt] _store_hwnd failed: {e}")

    def _track_focus(self):
        """Every 200ms save the foreground window if it's not ours."""
        try:
            hwnd = get_foreground_hwnd()
            if hwnd and hwnd != FixItPanel.PANEL_HWND and hwnd != 0:
                global LAST_TARGET_HND
                if LAST_TARGET_HND != hwnd:
                    title = win32gui.GetWindowText(hwnd)
                    print(f"[FixIt] Target → HWND {hwnd}: '{title}'")
                LAST_TARGET_HND = hwnd
        except Exception:
            pass
        self.root.after(200, self._track_focus)

    def _check_ollama(self):
        ok, msg = check_ollama()
        short = ("OK ✓" if ok else "NOT FOUND ✗") + "  " + msg[:40]
        self.root.after(0, lambda: self.ollama_var.set(f"Ollama: {short}"))
        if not ok:
            self.log("Install Ollama → ollama.com/download")
            self.log("Then run:  ollama pull qwen2.5:1.5b")

    def log(self, msg: str):
        print(f"[FixIt] {msg}")
        def _do():
            self.log_box.config(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.config(state="disabled")
            self.status_var.set(msg[:55])
        try:
            self.root.after(0, _do)
        except Exception:
            pass

    def _hotkey_fired(self):
        """
        Always use LAST_TARGET_HND — the last window YOU were in.
        Never use get_foreground_hwnd() here because by the time this
        fires, Windows may have already shifted focus to our panel or
        the keyboard hook process.
        """
        target = LAST_TARGET_HND
        if not target:
            self.log("No target. Click inside a text field first.")
            return
        print(f"[FixIt] Hotkey fired → targeting HWND {target}")
        threading.Thread(target=do_fix, args=(target, self.log), daemon=True).start()

    def _on_fix_now(self):
        target = LAST_TARGET_HND
        if not target:
            self.log("Click in a text field first, then FIX NOW.")
            return
        threading.Thread(target=do_fix, args=(target, self.log), daemon=True).start()

    def run(self):
        self.root.mainloop()

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    if not is_admin:
        print("[FixIt] ⚠  Not Administrator — hotkey may not work in all apps.")
        print("[FixIt]    Right-click terminal → Run as Administrator.")
        print()

    FixItPanel().run()
