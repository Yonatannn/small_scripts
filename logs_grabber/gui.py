#!/usr/bin/env python3
import sys
import time

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

import grab_logs


def _fmt_eta(seconds):
    if seconds is None or seconds < 0:
        return ""
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d} min"


class Worker(QThread):
    progress = pyqtSignal(float, str)
    log = pyqtSignal(str)
    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, config, selected, description):
        super().__init__()
        self.config = config
        self.selected = selected
        self.description = description

    def run(self):
        try:
            result = grab_logs.run_grab(
                self.config,
                selected_names=self.selected,
                description=self.description,
                log=lambda m: self.log.emit(str(m)),
                open_when_done=True,
                progress=lambda f, s: self.progress.emit(f, s),
            )
            self.done.emit(result)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class MainWindow(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.sources = config.get("sources", [])
        self.worker = None
        self.start_time = None
        self.checks = {}

        self.setWindowTitle("Logs Grabber")
        self.resize(720, 640)

        layout = QVBoxLayout(self)

        title = QLabel("Logs Grabber")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Choose which log types to collect (everything is checked by "
            "default), add a description, and click the button. The folder "
            "opens automatically when finished.")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #555;")
        layout.addWidget(subtitle)

        # Sources
        src_group = QGroupBox("Log types to collect")
        src_outer = QVBoxLayout(src_group)
        btn_row = QHBoxLayout()
        select_all = QPushButton("Select all")
        clear_all = QPushButton("Clear all")
        select_all.clicked.connect(lambda: self._set_all(True))
        clear_all.clicked.connect(lambda: self._set_all(False))
        btn_row.addWidget(select_all)
        btn_row.addWidget(clear_all)
        btn_row.addStretch()
        src_outer.addLayout(btn_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(150)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        if not self.sources:
            inner_layout.addWidget(QLabel("(no sources defined in config.json)"))
        for src in self.sources:
            name = src["name"]
            cb = QCheckBox(f"{name}   —   {src.get('path', '')}")
            cb.setChecked(True)
            self.checks[name] = cb
            inner_layout.addWidget(cb)
        inner_layout.addStretch()
        scroll.setWidget(inner)
        src_outer.addWidget(scroll)
        layout.addWidget(src_group)

        # Description
        desc_group = QGroupBox("Description (saved to info.txt)")
        desc_layout = QVBoxLayout(desc_group)
        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setFixedHeight(60)
        desc_layout.addWidget(self.desc_edit)
        layout.addWidget(desc_group)

        # Run button
        self.run_btn = QPushButton("▶  Start collecting logs")
        self.run_btn.setStyleSheet("font-size: 15px; font-weight: bold; padding: 10px;")
        self.run_btn.clicked.connect(self._on_run)
        layout.addWidget(self.run_btn)

        # Progress
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        layout.addWidget(self.bar)
        self.status = QLabel("Ready.")
        layout.addWidget(self.status)

        # Details
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)
        layout.addWidget(QLabel("Details"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background: #1e1e1e; color: #dcdcdc;")
        self.log_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.log_view)

    def _set_all(self, value):
        for cb in self.checks.values():
            cb.setChecked(value)

    def _on_run(self):
        if self.worker and self.worker.isRunning():
            return
        selected = [n for n, cb in self.checks.items() if cb.isChecked()]
        if not selected:
            QMessageBox.warning(self, "Logs Grabber", "No log type selected.")
            return

        self.run_btn.setEnabled(False)
        self.run_btn.setText("Working...")
        self.log_view.clear()
        self.bar.setValue(0)
        self.status.setText("Starting...")
        self.start_time = time.time()

        self.worker = Worker(self.config, selected,
                             self.desc_edit.toPlainText().strip())
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self._on_log)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_log(self, msg):
        self.log_view.appendPlainText(msg)

    def _on_progress(self, frac, stage):
        pct = int(frac * 100)
        self.bar.setValue(pct)
        if frac >= 1.0:
            self.status.setText("Done! ✓  Opening folder...")
            return
        eta = ""
        if self.start_time and frac > 0.02:
            elapsed = time.time() - self.start_time
            eta = f"  —  about {_fmt_eta(elapsed * (1 - frac) / frac)} left"
        self.status.setText(f"{stage}   ({pct}%){eta}")

    def _on_done(self, result):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("▶  Start collecting logs")
        QMessageBox.information(
            self, "Logs Grabber",
            f"Collection finished successfully!\n\n"
            f"Folder: {result['bundle_dir']}\n"
            f"Backup: {result['temp_zip']}")

    def _on_failed(self, message):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("▶  Start collecting logs")
        self.status.setText("An error occurred.")
        QMessageBox.critical(self, "Logs Grabber", message)


def main():
    app = QApplication(sys.argv)
    try:
        config = grab_logs.load_config(grab_logs.resolve_config_path())
        grab_logs.validate_config(config)
    except grab_logs.GrabError as e:
        QMessageBox.critical(None, "Logs Grabber", f"Problem in config.json:\n{e}")
        return
    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
