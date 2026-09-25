from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QDoubleSpinBox, QSplitter, QVBoxLayout, QWidget
)

from .controller import ProjectController
from .gemini_agent import GeminiAgent
from .key_pool import GeminiKeyPool, MAX_KEYS
from .media import MediaProbeError, probe_duration
from .project import MediaItem, Project
from .renderer import FFmpegRenderer

def fmt(seconds: float) -> str:
    value = max(0, int(round(seconds)))
    h, rem = divmod(value, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"

class Bridge(QObject):
    agent_message = Signal(str)
    render_log = Signal(str)
    error = Signal(str)
    refresh = Signal()
    render_done = Signal(str)

class KeyDialog(QDialog):
    def __init__(self, pool: GeminiKeyPool, parent=None) -> None:
        super().__init__(parent)
        self.pool = pool
        self.setWindowTitle("Kelola Gemini API/Auth Key")
        self.resize(650, 480)
        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.list = QListWidget()
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Paste banyak key di sini — satu key per baris. Maksimal 100.")
        add = QPushButton("Tambahkan Key")
        remove = QPushButton("Hapus Key Terpilih")
        add.clicked.connect(self.add_keys)
        remove.clicked.connect(self.remove_key)
        layout.addWidget(self.status)
        layout.addWidget(self.list, 2)
        layout.addWidget(self.input, 1)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        layout.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        for i, rec in enumerate(self.pool.records):
            state = "SIAP" if rec.available else ("NONAKTIF" if not rec.enabled else "COOLDOWN")
            self.list.addItem(f"{i+1:02d}. {rec.masked}  —  {state}")
        s = self.pool.summary()
        self.status.setText(
            f"Total {s['total']}/{MAX_KEYS} • Siap {s['ready']} • "
            f"Cooldown {s['cooldown']} • Nonaktif {s['disabled']}"
        )

    def add_keys(self) -> None:
        values = [x.strip() for x in self.input.toPlainText().splitlines() if x.strip()]
        added, overflow = self.pool.add_keys(values)
        self.input.clear()
        self.refresh()
        tail = f" • Melebihi batas: {overflow}" if overflow else ""
        QMessageBox.information(self, "Gemini Key", f"Ditambahkan: {added}{tail}")

    def remove_key(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.pool.remove(row)
            self.refresh()

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Full Album Maker")
        self.resize(1380, 820)
        self.project = Project()
        self.controller = ProjectController(self.project)
        self.pool = GeminiKeyPool()
        self.agent = None
        self.bridge = Bridge()
        self.bridge.agent_message.connect(self._agent_message)
        self.bridge.render_log.connect(self._render_log)
        self.bridge.error.connect(self._error)
        self.bridge.refresh.connect(self.refresh)
        self.bridge.render_done.connect(self._render_done)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._media_panel())
        splitter.addWidget(self._settings_panel())
        splitter.addWidget(self._agent_panel())
        splitter.setSizes([430, 420, 450])
        outer.addWidget(splitter)

        self.summary = QLabel()
        self.summary.setStyleSheet("font-size: 14px; padding: 8px;")
        outer.addWidget(self.summary)
        self.render_btn = QPushButton("RENDER FULL ALBUM")
        self.render_btn.setMinimumHeight(46)
        self.render_btn.clicked.connect(self.render)
        outer.addWidget(self.render_btn)
        self.refresh()

    def _media_panel(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)

        videos = QGroupBox("Footage Video")
        vlay = QVBoxLayout(videos)
        self.video_list = QListWidget()
        add_video = QPushButton("+ Tambah Video")
        add_video.clicked.connect(self.add_video)
        remove_video = QPushButton("Hapus Video Terpilih")
        remove_video.clicked.connect(self.remove_video)
        vlay.addWidget(self.video_list)
        row = QHBoxLayout()
        row.addWidget(add_video)
        row.addWidget(remove_video)
        vlay.addLayout(row)

        audios = QGroupBox("Lagu / Album")
        alay = QVBoxLayout(audios)
        self.audio_list = QListWidget()
        add_audio = QPushButton("+ Tambah Audio")
        add_audio.clicked.connect(self.add_audio)
        remove_audio = QPushButton("Hapus Lagu Terpilih")
        remove_audio.clicked.connect(self.remove_audio)
        sort = QPushButton("Urutkan Berdasarkan Nama")
        sort.clicked.connect(self.sort_audio)
        alay.addWidget(self.audio_list)
        row2 = QHBoxLayout()
        row2.addWidget(add_audio)
        row2.addWidget(remove_audio)
        alay.addLayout(row2)
        alay.addWidget(sort)

        lay.addWidget(videos)
        lay.addWidget(audios)
        return box

    def _settings_panel(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        group = QGroupBox("Pengaturan Video")
        form = QFormLayout(group)

        self.speed_mode = QComboBox()
        self.speed_mode.addItems(["Otomatis", "Manual"])
        self.manual_speed = QDoubleSpinBox()
        self.manual_speed.setRange(0.05, 2.0)
        self.manual_speed.setSingleStep(0.05)
        self.manual_speed.setValue(1.0)
        self.min_speed = QDoubleSpinBox()
        self.min_speed.setRange(0.05, 1.0)
        self.min_speed.setSingleStep(0.05)
        self.min_speed.setValue(0.5)

        self.loop_mode = QComboBox()
        self.loop_mode.addItem("Slowmo + Loop Otomatis", "auto")
        self.loop_mode.addItem("Loop", "loop")
        self.loop_mode.addItem("Ping-Pong", "pingpong")
        self.loop_mode.addItem("Tanpa Loop", "none")

        self.resolution = QComboBox()
        for label, data in [
            ("1920×1080", (1920, 1080)),
            ("2560×1440", (2560, 1440)),
            ("3840×2160", (3840, 2160)),
        ]:
            self.resolution.addItem(label, data)

        self.fps = QComboBox()
        for value in (24, 25, 30, 50, 60):
            self.fps.addItem(str(value), value)
        self.fps.setCurrentText("30")

        self.codec = QComboBox()
        self.codec.addItem("H.264", "h264")
        self.codec.addItem("H.265 / HEVC", "h265")

        self.speed_mode.currentIndexChanged.connect(self.apply_settings)
        self.manual_speed.valueChanged.connect(self.apply_settings)
        self.min_speed.valueChanged.connect(self.apply_settings)
        self.loop_mode.currentIndexChanged.connect(self.apply_settings)
        self.resolution.currentIndexChanged.connect(self.apply_settings)
        self.fps.currentIndexChanged.connect(self.apply_settings)
        self.codec.currentIndexChanged.connect(self.apply_settings)

        form.addRow("Slow Motion", self.speed_mode)
        form.addRow("Speed Manual", self.manual_speed)
        form.addRow("Batas Slowmo", self.min_speed)
        form.addRow("Jika Video Kurang", self.loop_mode)
        form.addRow("Resolusi", self.resolution)
        form.addRow("FPS", self.fps)
        form.addRow("Codec", self.codec)
        lay.addWidget(group)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Log render FFmpeg…")
        lay.addWidget(self.log, 1)
        return box

    def _agent_panel(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        top = QHBoxLayout()
        self.key_status = QLabel()
        keys = QPushButton("Kelola API Key")
        keys.clicked.connect(self.open_keys)
        top.addWidget(self.key_status, 1)
        top.addWidget(keys)
        lay.addLayout(top)

        self.model = QLineEdit("gemini-3.6-flash")
        lay.addWidget(QLabel("Model Gemini"))
        lay.addWidget(self.model)

        self.chat = QPlainTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setPlaceholderText("Gemini Agent akan tampil di sini.")
        lay.addWidget(self.chat, 1)

        self.prompt = QPlainTextEdit()
        self.prompt.setMaximumHeight(100)
        self.prompt.setPlaceholderText(
            "Contoh: buat slowmo otomatis minimal 0,5x lalu ping-pong kalau kurang"
        )
        send = QPushButton("Kirim ke Gemini Agent")
        send.clicked.connect(self.ask_agent)
        lay.addWidget(self.prompt)
        lay.addWidget(send)
        return box

    def apply_settings(self, *_):
        s = self.project.settings
        s.auto_speed = self.speed_mode.currentText() == "Otomatis"
        s.manual_speed = float(self.manual_speed.value())
        s.min_speed = float(self.min_speed.value())
        s.loop_mode = self.loop_mode.currentData()
        s.width, s.height = self.resolution.currentData()
        s.fps = int(self.fps.currentData())
        s.codec = self.codec.currentData()
        self.refresh()

    def add_video(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Pilih Footage", "", "Video (*.mp4 *.mov *.mkv *.webm *.avi)"
        )
        self._add_media(paths, self.project.videos)

    def add_audio(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Pilih Lagu", "", "Audio (*.mp3 *.wav *.flac *.m4a *.aac *.ogg)"
        )
        self._add_media(paths, self.project.audios)

    def _add_media(self, paths, target):
        for path in paths:
            try:
                target.append(MediaItem(path=path, duration=probe_duration(path)))
            except MediaProbeError as exc:
                self._error(str(exc))
        self.refresh()

    def remove_video(self):
        row = self.video_list.currentRow()
        if row >= 0:
            del self.project.videos[row]
            self.refresh()

    def remove_audio(self):
        row = self.audio_list.currentRow()
        if row >= 0:
            del self.project.audios[row]
            self.refresh()

    def sort_audio(self):
        self.project.sort_audio_by_name()
        self.refresh()

    def refresh(self):
        self.video_list.clear()
        for item in self.project.videos:
            self.video_list.addItem(f"{item.name}  •  {fmt(item.duration)}")

        self.audio_list.clear()
        current = 0.0
        for item in self.project.audios:
            self.audio_list.addItem(f"{fmt(current)}  {item.name}  •  {fmt(item.duration)}")
            current += item.duration

        p = self.project
        self.summary.setText(
            f"Footage: {fmt(p.total_video_duration)}   |   Album: {fmt(p.total_audio_duration)}   |   "
            f"Speed rencana: {p.planned_speed():.3f}×   |   Hasil footage: {fmt(p.adjusted_video_duration())}   |   "
            f"Perlu loop: {'YA' if p.needs_loop() else 'TIDAK'}"
        )
        settings = p.settings
        sync_widgets = [
            self.speed_mode, self.manual_speed, self.min_speed,
            self.loop_mode, self.resolution, self.fps, self.codec,
        ]
        for widget in sync_widgets:
            widget.blockSignals(True)
        try:
            self.speed_mode.setCurrentText("Otomatis" if settings.auto_speed else "Manual")
            self.manual_speed.setValue(settings.manual_speed)
            self.min_speed.setValue(settings.min_speed)
            loop_index = self.loop_mode.findData(settings.loop_mode)
            if loop_index >= 0:
                self.loop_mode.setCurrentIndex(loop_index)
            resolution_index = self.resolution.findData((settings.width, settings.height))
            if resolution_index >= 0:
                self.resolution.setCurrentIndex(resolution_index)
            fps_index = self.fps.findData(settings.fps)
            if fps_index >= 0:
                self.fps.setCurrentIndex(fps_index)
            codec_index = self.codec.findData(settings.codec)
            if codec_index >= 0:
                self.codec.setCurrentIndex(codec_index)
        finally:
            for widget in sync_widgets:
                widget.blockSignals(False)

        s = self.pool.summary()
        self.key_status.setText(f"Gemini: {s['ready']} siap / {s['total']} key")

    def open_keys(self):
        KeyDialog(self.pool, self).exec()
        self.refresh()

    def ask_agent(self):
        text = self.prompt.toPlainText().strip()
        if not text:
            return
        self.prompt.clear()
        self.chat.appendPlainText(f"ANDA: {text}\n")
        model = self.model.text().strip() or "gemini-3.6-flash"

        def work():
            try:
                if self.agent is None or self.agent.model != model:
                    self.agent = GeminiAgent(self.pool, self.controller, model=model)
                answer = self.agent.ask(text)
                self.bridge.agent_message.emit(answer)
                self.bridge.refresh.emit()
            except Exception as exc:
                self.bridge.error.emit(str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _agent_message(self, text):
        self.chat.appendPlainText(f"GEMINI: {text}\n")

    def render(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Simpan Full Album", "FULL_ALBUM_FINAL.mp4", "MP4 (*.mp4)"
        )
        if not path:
            return
        self.render_btn.setEnabled(False)
        self.log.clear()

        def work():
            try:
                renderer = FFmpegRenderer(self.project)
                result = renderer.render(path, log=self.bridge.render_log.emit)
                self.bridge.render_done.emit(result)
            except Exception as exc:
                self.bridge.error.emit(str(exc))
                self.bridge.render_done.emit("")

        threading.Thread(target=work, daemon=True).start()

    def _render_log(self, text):
        self.log.appendPlainText(text)

    def _render_done(self, path):
        self.render_btn.setEnabled(True)
        if path:
            QMessageBox.information(self, "Render selesai", f"Video selesai:\n{path}")

    def _error(self, text):
        QMessageBox.critical(self, "Full Album Maker", text)

def run() -> int:
    app = QApplication([])
    app.setApplicationName("Full Album Maker")
    win = MainWindow()
    win.show()
    return app.exec()
