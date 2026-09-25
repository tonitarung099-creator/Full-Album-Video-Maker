from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QDoubleSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .controller import ProjectController
from .gemini_agent import GeminiAgent
from .key_pool import GeminiKeyPool, MAX_KEYS
from .media import MediaProbeError, probe_duration
from .project import MediaItem, Project
from .renderer import FFmpegRenderer
from .style import APP_STYLE


def fmt(seconds: float) -> str:
    value = max(0, int(round(seconds)))
    h, rem = divmod(value, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def compact_layout(layout, margins=(8, 8, 8, 8), spacing=6) -> None:
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)


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
        self.setWindowTitle("Kelola Gemini Key")
        self.resize(620, 440)
        self.setMinimumSize(540, 380)

        layout = QVBoxLayout(self)
        compact_layout(layout, (10, 10, 10, 10), 7)

        head = QHBoxLayout()
        compact_layout(head, (0, 0, 0, 0), 6)
        title = QLabel("Gemini API / Auth Key")
        title.setObjectName("sectionTitle")
        self.status = QLabel()
        self.status.setObjectName("statusChip")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.status)
        layout.addLayout(head)

        self.list = QListWidget()
        self.list.setTextElideMode(Qt.ElideMiddle)
        layout.addWidget(self.list, 2)

        self.input = QPlainTextEdit()
        self.input.setMaximumHeight(105)
        self.input.setPlaceholderText("Paste key, satu baris satu key. Maksimal 100 key.")
        layout.addWidget(self.input)

        row = QHBoxLayout()
        compact_layout(row, (0, 0, 0, 0), 6)
        add = QPushButton("+ Tambah")
        remove = QPushButton("Hapus")
        add.setToolTip("Tambahkan semua key yang ditempel di kotak di atas.")
        remove.setToolTip("Hapus key yang sedang dipilih.")
        add.clicked.connect(self.add_keys)
        remove.clicked.connect(self.remove_key)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        layout.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        for i, rec in enumerate(self.pool.records):
            state = "SIAP" if rec.available else ("NONAKTIF" if not rec.enabled else "COOLDOWN")
            self.list.addItem(f"{i + 1:02d}. {rec.masked}  •  {state}")
        s = self.pool.summary()
        self.status.setText(
            f"{s['total']}/{MAX_KEYS}  |  siap {s['ready']}  |  cooldown {s['cooldown']}"
        )

    def add_keys(self) -> None:
        values = [x.strip() for x in self.input.toPlainText().splitlines() if x.strip()]
        added, overflow = self.pool.add_keys(values)
        self.input.clear()
        self.refresh()
        tail = f" • melebihi batas: {overflow}" if overflow else ""
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
        self.resize(1320, 780)
        self.setMinimumSize(1060, 680)

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
        compact_layout(outer, (10, 8, 10, 10), 7)

        outer.addLayout(self._header())

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self._media_panel())
        self.splitter.addWidget(self._settings_panel())
        self.splitter.addWidget(self._agent_panel())
        self.splitter.setSizes([390, 370, 430])
        outer.addWidget(self.splitter, 1)

        outer.addLayout(self._status_bar())

        self.render_btn = QPushButton("RENDER FULL ALBUM")
        self.render_btn.setObjectName("primaryButton")
        self.render_btn.setMinimumHeight(36)
        self.render_btn.clicked.connect(self.render)
        outer.addWidget(self.render_btn)

        self.refresh()

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        compact_layout(row, (2, 0, 2, 0), 8)

        titles = QVBoxLayout()
        compact_layout(titles, (0, 0, 0, 0), 1)
        title = QLabel("Full Album Maker")
        title.setObjectName("title")
        subtitle = QLabel("Footage + album audio + slowmo + Gemini Agent")
        subtitle.setObjectName("subtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)

        badge = QLabel("PORTABLE")
        badge.setObjectName("statusChip")

        row.addLayout(titles)
        row.addStretch(1)
        row.addWidget(badge)
        return row

    def _panel(self) -> tuple[QWidget, QVBoxLayout]:
        panel = QWidget()
        panel.setObjectName("panel")
        panel.setMinimumWidth(300)
        lay = QVBoxLayout(panel)
        compact_layout(lay, (9, 8, 9, 8), 7)
        return panel, lay

    def _media_panel(self) -> QWidget:
        panel, lay = self._panel()

        title = QLabel("MEDIA")
        title.setObjectName("sectionTitle")
        lay.addWidget(title)

        videos = QGroupBox("Footage")
        vlay = QVBoxLayout(videos)
        compact_layout(vlay, (7, 8, 7, 7), 5)

        self.video_list = QListWidget()
        self.video_list.setTextElideMode(Qt.ElideMiddle)

        video_row = QHBoxLayout()
        compact_layout(video_row, (0, 0, 0, 0), 5)
        add_video = QPushButton("+ Video")
        remove_video = QPushButton("Hapus")
        add_video.setToolTip("Tambah satu atau banyak footage video.")
        remove_video.setToolTip("Hapus footage yang dipilih.")
        add_video.clicked.connect(self.add_video)
        remove_video.clicked.connect(self.remove_video)
        video_row.addWidget(add_video)
        video_row.addWidget(remove_video)
        video_row.addStretch(1)

        vlay.addWidget(self.video_list, 1)
        vlay.addLayout(video_row)

        audios = QGroupBox("Lagu / Album")
        alay = QVBoxLayout(audios)
        compact_layout(alay, (7, 8, 7, 7), 5)

        self.audio_list = QListWidget()
        self.audio_list.setTextElideMode(Qt.ElideMiddle)

        audio_row = QHBoxLayout()
        compact_layout(audio_row, (0, 0, 0, 0), 5)
        add_audio = QPushButton("+ Lagu")
        remove_audio = QPushButton("Hapus")
        sort = QPushButton("Urut A–Z")
        add_audio.setToolTip("Tambah satu atau banyak lagu.")
        remove_audio.setToolTip("Hapus lagu yang dipilih.")
        sort.setToolTip("Urutkan lagu berdasarkan nama file.")
        add_audio.clicked.connect(self.add_audio)
        remove_audio.clicked.connect(self.remove_audio)
        sort.clicked.connect(self.sort_audio)
        audio_row.addWidget(add_audio)
        audio_row.addWidget(remove_audio)
        audio_row.addWidget(sort)

        alay.addWidget(self.audio_list, 1)
        alay.addLayout(audio_row)

        lay.addWidget(videos, 1)
        lay.addWidget(audios, 1)
        return panel

    def _settings_panel(self) -> QWidget:
        panel, lay = self._panel()

        title = QLabel("VIDEO")
        title.setObjectName("sectionTitle")
        lay.addWidget(title)

        group = QGroupBox("Pengaturan")
        form = QFormLayout(group)
        form.setContentsMargins(8, 10, 8, 8)
        form.setHorizontalSpacing(9)
        form.setVerticalSpacing(6)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.speed_mode = QComboBox()
        self.speed_mode.addItems(["Otomatis", "Manual"])

        self.manual_speed = QDoubleSpinBox()
        self.manual_speed.setRange(0.05, 2.0)
        self.manual_speed.setSingleStep(0.05)
        self.manual_speed.setDecimals(2)
        self.manual_speed.setValue(1.0)
        self.manual_speed.setSuffix(" ×")

        self.min_speed = QDoubleSpinBox()
        self.min_speed.setRange(0.05, 1.0)
        self.min_speed.setSingleStep(0.05)
        self.min_speed.setDecimals(2)
        self.min_speed.setValue(0.5)
        self.min_speed.setSuffix(" ×")

        self.loop_mode = QComboBox()
        self.loop_mode.addItem("Auto + loop", "auto")
        self.loop_mode.addItem("Loop", "loop")
        self.loop_mode.addItem("Ping-pong", "pingpong")
        self.loop_mode.addItem("Tanpa loop", "none")

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

        form.addRow("Slowmo", self.speed_mode)
        form.addRow("Speed", self.manual_speed)
        form.addRow("Min. slowmo", self.min_speed)
        form.addRow("Jika kurang", self.loop_mode)
        form.addRow("Resolusi", self.resolution)
        form.addRow("FPS", self.fps)
        form.addRow("Codec", self.codec)
        lay.addWidget(group)

        log_title = QLabel("LOG RENDER")
        log_title.setObjectName("sectionTitle")
        lay.addWidget(log_title)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Log FFmpeg akan muncul di sini.")
        lay.addWidget(self.log, 1)
        return panel

    def _agent_panel(self) -> QWidget:
        panel, lay = self._panel()

        top = QHBoxLayout()
        compact_layout(top, (0, 0, 0, 0), 6)
        title = QLabel("GEMINI AGENT")
        title.setObjectName("sectionTitle")
        self.key_status = QLabel()
        self.key_status.setObjectName("statusChip")
        keys = QPushButton("Key")
        keys.setToolTip("Kelola hingga 100 Gemini API/Auth key.")
        keys.clicked.connect(self.open_keys)
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(self.key_status)
        top.addWidget(keys)
        lay.addLayout(top)

        model_row = QHBoxLayout()
        compact_layout(model_row, (0, 0, 0, 0), 6)
        model_label = QLabel("Model")
        model_label.setObjectName("subtitle")
        self.model = QLineEdit("gemini-3.6-flash")
        self.model.setToolTip("Nama model Gemini yang dipakai agent.")
        model_row.addWidget(model_label)
        model_row.addWidget(self.model, 1)
        lay.addLayout(model_row)

        self.chat = QPlainTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setPlaceholderText("Percakapan Gemini Agent.")
        lay.addWidget(self.chat, 1)

        self.prompt = QPlainTextEdit()
        self.prompt.setMaximumHeight(76)
        self.prompt.setPlaceholderText("Contoh: slowmo otomatis min 0,5x lalu ping-pong jika kurang.")
        lay.addWidget(self.prompt)

        send = QPushButton("Kirim ke Agent")
        send.setObjectName("primaryButton")
        send.clicked.connect(self.ask_agent)
        lay.addWidget(send)
        return panel

    def _status_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        compact_layout(row, (0, 0, 0, 0), 5)
        self.status_labels: dict[str, QLabel] = {}
        for key in ("video", "album", "speed", "result", "loop"):
            label = QLabel()
            label.setObjectName("statusChip")
            label.setAlignment(Qt.AlignCenter)
            self.status_labels[key] = label
            row.addWidget(label, 1)
        return row

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
            self.video_list.addItem(f"{item.name}   •   {fmt(item.duration)}")

        self.audio_list.clear()
        current = 0.0
        for item in self.project.audios:
            self.audio_list.addItem(f"{fmt(current)}   {item.name}   •   {fmt(item.duration)}")
            current += item.duration

        p = self.project
        self.status_labels["video"].setText(f"Footage  {fmt(p.total_video_duration)}")
        self.status_labels["album"].setText(f"Album  {fmt(p.total_audio_duration)}")
        self.status_labels["speed"].setText(f"Speed  {p.planned_speed():.3f}×")
        self.status_labels["result"].setText(f"Hasil  {fmt(p.adjusted_video_duration())}")
        self.status_labels["loop"].setText(f"Loop  {'YA' if p.needs_loop() else 'TIDAK'}")

        settings = p.settings
        sync_widgets = [
            self.speed_mode,
            self.manual_speed,
            self.min_speed,
            self.loop_mode,
            self.resolution,
            self.fps,
            self.codec,
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
        self.key_status.setText(f"{s['ready']}/{s['total']} key")

    def open_keys(self):
        KeyDialog(self.pool, self).exec()
        self.refresh()

    def ask_agent(self):
        text = self.prompt.toPlainText().strip()
        if not text:
            return

        self.prompt.clear()
        self.chat.appendPlainText(f"ANDA\n{text}\n")
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
        self.chat.appendPlainText(f"GEMINI\n{text}\n")

    def render(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Simpan Full Album", "FULL_ALBUM_FINAL.mp4", "MP4 (*.mp4)"
        )
        if not path:
            return

        self.render_btn.setEnabled(False)
        self.render_btn.setText("RENDERING…")
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
        self.render_btn.setText("RENDER FULL ALBUM")
        if path:
            QMessageBox.information(self, "Render selesai", f"Video selesai:\n{path}")

    def _error(self, text):
        QMessageBox.critical(self, "Full Album Maker", text)


def run() -> int:
    app = QApplication([])
    app.setApplicationName("Full Album Maker")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    win = MainWindow()
    win.show()
    return app.exec()
