#!/usr/bin/env python3
"""Tkinter GUI for the logs grabber, aimed at non-technical users.

- One checkbox per log source; everything is checked by default, so the
  default behaviour is "collect everything". Uncheck whatever you don't want.
- A box for a description, saved to info.txt inside "Logs - <date>".
- A big progress bar with a live "time remaining" estimate while it copies.
- The result folder opens automatically when it's done.

Target platform: Windows 11, Python 3.10 (tkinter ships with Python).
"""
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import grab_logs


def _fmt_eta(seconds):
    if seconds is None or seconds < 0:
        return ""
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d} min"


class LogsGrabberGUI:
    def __init__(self, root, config):
        self.root = root
        self.config = config
        self.sources = config.get("sources", [])
        self.queue = queue.Queue()
        self.worker = None
        self.start_time = None
        self.source_vars = {}

        root.title("Logs Grabber")
        root.geometry("780x680")
        root.minsize(660, 560)

        main = ttk.Frame(root, padding=14)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="Logs Grabber", font=("Segoe UI", 16, "bold")).pack(
            anchor="w")
        ttk.Label(
            main,
            text="Choose which log types to collect (everything is checked by "
                 "default), add a description, and click the big button. "
                 "The folder opens automatically when finished.",
            foreground="#555", wraplength=720, justify="left",
        ).pack(anchor="w", pady=(0, 10))

        # --- Sources checklist ------------------------------------------
        box = ttk.LabelFrame(main, text="  Log types to collect  ", padding=8)
        box.pack(fill="x", pady=4)

        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(0, 6))
        ttk.Button(btns, text="Select all", command=lambda: self._set_all(True)).pack(
            side="left", padx=2)
        ttk.Button(btns, text="Clear all", command=lambda: self._set_all(False)).pack(
            side="left", padx=2)

        canvas = tk.Canvas(box, height=150, highlightthickness=0)
        scroll = ttk.Scrollbar(box, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        if not self.sources:
            ttk.Label(inner, text="(no sources defined in config.json)").pack(anchor="w")
        for src in self.sources:
            name = src["name"]
            var = tk.BooleanVar(value=True)
            self.source_vars[name] = var
            row = ttk.Frame(inner)
            row.pack(fill="x", anchor="w")
            ttk.Checkbutton(
                row, variable=var,
                text=f"{name}   —   {src.get('path', '')}",
            ).pack(anchor="w")

        # --- Description -------------------------------------------------
        desc_box = ttk.LabelFrame(main, text="  Description (saved to info.txt)  ",
                                  padding=8)
        desc_box.pack(fill="x", pady=6)
        self.desc_text = tk.Text(desc_box, height=3, wrap="word")
        self.desc_text.pack(fill="x")

        # --- Output dir --------------------------------------------------
        out_box = ttk.Frame(main)
        out_box.pack(fill="x", pady=6)
        ttk.Label(out_box, text="Output folder:").pack(side="left")
        default_out = str(grab_logs.resolve_output_dir(config))
        self.out_var = tk.StringVar(value=default_out)
        ttk.Entry(out_box, textvariable=self.out_var).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Button(out_box, text="Browse...", command=self._browse_out).pack(side="left")

        # --- Run button (big and obvious) -------------------------------
        style = ttk.Style()
        try:
            style.configure("Run.TButton", font=("Segoe UI", 13, "bold"), padding=10)
        except tk.TclError:
            pass
        self.run_btn = ttk.Button(main, text="▶  Start collecting logs",
                                  style="Run.TButton", command=self._on_run)
        self.run_btn.pack(fill="x", pady=10)

        # --- Progress ----------------------------------------------------
        prog_box = ttk.Frame(main)
        prog_box.pack(fill="x", pady=(0, 6))
        self.progress = ttk.Progressbar(prog_box, maximum=100, mode="determinate")
        self.progress.pack(fill="x")
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(prog_box, textvariable=self.status_var, font=("Segoe UI", 10),
                  anchor="w", justify="left").pack(fill="x", pady=(4, 0))

        # --- Log output (details) ---------------------------------------
        log_box = ttk.LabelFrame(main, text="  Details  ", padding=4)
        log_box.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_box, height=8, wrap="word", state="disabled",
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

    def _append_log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_progress(self, frac, stage):
        self.queue.put(("progress", frac, stage))

    def _on_log(self, msg):
        self.queue.put(("log", str(msg)))

    def _flush_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                if item[0] == "log":
                    self._append_log(item[1])
                elif item[0] == "progress":
                    self._update_progress(item[1], item[2])
        except queue.Empty:
            pass

    def _drain_queue(self):
        self._flush_queue()
        if self.worker and self.worker.is_alive():
            self.root.after(100, self._drain_queue)
        else:
            self._flush_queue()  # final flush
            self.run_btn.configure(state="normal", text="▶  Start collecting logs")

    def _update_progress(self, frac, stage):
        pct = int(frac * 100)
        self.progress["value"] = pct
        eta = ""
        if self.start_time and 0.02 < frac < 1.0:
            elapsed = time.time() - self.start_time
            remaining = elapsed * (1 - frac) / frac
            eta = f"  —  about {_fmt_eta(remaining)} left"
        if frac >= 1.0:
            self.status_var.set("Done! ✓  Opening folder...")
        else:
            self.status_var.set(f"{stage}   ({pct}%){eta}")

    # --- run ------------------------------------------------------------
    def _on_run(self):
        if self.worker and self.worker.is_alive():
            return
        selected = [n for n, v in self.source_vars.items() if v.get()]
        if not selected:
            messagebox.showwarning("Logs Grabber", "No log type selected.")
            return
        description = self.desc_text.get("1.0", "end").strip()
        output_dir = self.out_var.get().strip() or None

        self.run_btn.configure(state="disabled", text="Working...")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.progress["value"] = 0
        self.status_var.set("Starting...")
        self.start_time = time.time()

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
                log=self._on_log,
                open_when_done=True,
                progress=self._on_progress,
            )
            self._on_log(f"\n✓ Done. {result['copied']} file(s) collected.")
            self.root.after(0, lambda: messagebox.showinfo(
                "Logs Grabber",
                f"Collection finished successfully!\n\n"
                f"Folder: {result['bundle_dir']}\n"
                f"Backup: {result['temp_zip']}"))
        except Exception as e:  # noqa: BLE001 - surface any error to the user
            self._on_log(f"\n[ERROR] {e}")
            self.root.after(0, lambda: (
                self.status_var.set("An error occurred."),
                messagebox.showerror("Logs Grabber", str(e))))


def main():
    config_path = grab_logs.resolve_config_path("config.json")
    try:
        config = grab_logs.load_config(config_path)
        grab_logs.validate_config(config)
    except grab_logs.GrabError as e:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Logs Grabber", f"Problem in config.json:\n{e}")
        return

    root = tk.Tk()
    LogsGrabberGUI(root, config)
    root.mainloop()


if __name__ == "__main__":
    main()
