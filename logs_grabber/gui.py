#!/usr/bin/env python3
"""Tkinter GUI for the logs grabber.

Lets the user uncheck any log source they don't want collected (everything
is checked by default), enter a Hebrew description that is saved to info.txt
inside the "Logs - <date>" folder, then run the grab with live progress.

Target platform: Windows 11, Python 3.10 (tkinter ships with Python).
"""
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import grab_logs


class LogsGrabberGUI:
    def __init__(self, root, config, config_path):
        self.root = root
        self.config = config
        self.config_path = config_path
        self.sources = config.get("sources", [])
        self.queue = queue.Queue()
        self.worker = None
        self.source_vars = {}

        root.title("Logs Grabber")
        root.geometry("760x640")
        root.minsize(640, 520)

        main = ttk.Frame(root, padding=12)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="איסוף לוגים", font=("Segoe UI", 14, "bold")).pack(
            anchor="e")
        ttk.Label(
            main,
            text="בחר אילו סוגי לוגים לאסוף (כברירת מחדל הכל מסומן), "
                 "הוסף תיאור, ולחץ 'הרץ'.",
            foreground="#555",
        ).pack(anchor="e", pady=(0, 8))

        # --- Sources checklist ------------------------------------------
        box = ttk.LabelFrame(main, text="סוגי לוגים", padding=8)
        box.pack(fill="both", expand=False, pady=4)

        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(0, 6))
        ttk.Button(btns, text="סמן הכל", command=lambda: self._set_all(True)).pack(
            side="right", padx=2)
        ttk.Button(btns, text="נקה הכל", command=lambda: self._set_all(False)).pack(
            side="right", padx=2)

        # Scrollable area for many sources
        canvas = tk.Canvas(box, height=170, highlightthickness=0)
        scroll = ttk.Scrollbar(box, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        if not self.sources:
            ttk.Label(inner, text="(אין מקורות מוגדרים ב-config.json)").pack(anchor="e")
        for src in self.sources:
            name = src["name"]
            var = tk.BooleanVar(value=True)
            self.source_vars[name] = var
            row = ttk.Frame(inner)
            row.pack(fill="x", anchor="e")
            ttk.Checkbutton(
                row, variable=var,
                text=f"{name}   —   {src.get('path', '')}",
            ).pack(anchor="e")

        # --- Description -------------------------------------------------
        desc_box = ttk.LabelFrame(main, text="תיאור / שם בעברית (יישמר ל-info.txt)",
                                  padding=8)
        desc_box.pack(fill="x", pady=6)
        self.desc_text = tk.Text(desc_box, height=4, wrap="word")
        self.desc_text.pack(fill="x")

        # --- Output dir --------------------------------------------------
        out_box = ttk.Frame(main)
        out_box.pack(fill="x", pady=6)
        ttk.Label(out_box, text="תיקיית יעד:").pack(side="right")
        default_out = str(grab_logs.resolve_output_dir(config))
        self.out_var = tk.StringVar(value=default_out)
        ttk.Entry(out_box, textvariable=self.out_var).pack(
            side="right", fill="x", expand=True, padx=6)
        ttk.Button(out_box, text="עיון...", command=self._browse_out).pack(side="right")

        # --- Run button --------------------------------------------------
        self.run_btn = ttk.Button(main, text="הרץ איסוף", command=self._on_run)
        self.run_btn.pack(pady=8)

        # --- Log output --------------------------------------------------
        log_box = ttk.LabelFrame(main, text="פלט", padding=4)
        log_box.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_box, height=10, wrap="word", state="disabled",
                                background="#1e1e1e", foreground="#dcdcdc")
        log_scroll = ttk.Scrollbar(log_box, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

    # --- helpers --------------------------------------------------------
    def _set_all(self, value):
        for var in self.source_vars.values():
            var.set(value)

    def _browse_out(self):
        chosen = filedialog.askdirectory(initialdir=self.out_var.get() or os.getcwd())
        if chosen:
            self.out_var.set(chosen)

    def _log(self, msg):
        """Thread-safe: producers push to the queue, the UI thread drains it."""
        self.queue.put(str(msg))

    def _drain_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        if self.worker and self.worker.is_alive():
            self.root.after(100, self._drain_queue)
        else:
            self._drain_queue_final()

    def _drain_queue_final(self):
        # flush anything left, then re-enable the button
        try:
            while True:
                msg = self.queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.run_btn.configure(state="normal", text="הרץ איסוף")

    # --- run ------------------------------------------------------------
    def _on_run(self):
        if self.worker and self.worker.is_alive():
            return
        selected = [n for n, v in self.source_vars.items() if v.get()]
        if not selected:
            messagebox.showwarning("Logs Grabber", "לא נבחר אף סוג לוג לאיסוף.")
            return
        description = self.desc_text.get("1.0", "end").strip()
        output_dir = self.out_var.get().strip() or None

        self.run_btn.configure(state="disabled", text="עובד...")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

        self.worker = threading.Thread(
            target=self._work, args=(selected, description, output_dir), daemon=True)
        self.worker.start()
        self.root.after(100, self._drain_queue)

    def _work(self, selected, description, output_dir):
        try:
            result = grab_logs.run_grab(
                self.config,
                selected_names=selected,
                description=description,
                output_dir=output_dir,
                log=self._log,
                open_when_done=True,
            )
            self._log(f"\n✓ הסתיים. {result['copied']} קבצים נאספו.")
            self.root.after(0, lambda: messagebox.showinfo(
                "Logs Grabber",
                f"האיסוף הסתיים.\n\nתיקייה: {result['bundle_dir']}\n"
                f"גיבוי: {result['temp_zip']}"))
        except grab_logs.GrabError as e:
            self._log(f"\n[ERROR] {e}")
            self.root.after(0, lambda: messagebox.showerror("Logs Grabber", str(e)))
        except Exception as e:  # noqa: BLE001 - surface unexpected errors to the user
            self._log(f"\n[ERROR] {e}")
            self.root.after(0, lambda: messagebox.showerror("Logs Grabber", str(e)))


def main():
    config_path = grab_logs.resolve_config_path("config.json")
    try:
        config = grab_logs.load_config(config_path)
        grab_logs.validate_config(config)
    except grab_logs.GrabError as e:
        # Show a dialog even if config is broken, so double-click users see why.
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Logs Grabber", f"בעיה ב-config.json:\n{e}")
        return

    root = tk.Tk()
    LogsGrabberGUI(root, config, config_path)
    root.mainloop()


if __name__ == "__main__":
    main()
