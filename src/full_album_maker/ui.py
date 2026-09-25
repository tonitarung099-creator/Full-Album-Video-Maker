from __future__ import annotations

import threading
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
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
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .controller import ProjectController
from .gemini_agent import GeminiAgent
from .key_pool import GeminiKeyPool, MAX_KEYS
from .media import MediaProbeError, probe_duration
from .paths import asset_path, output_dir
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


def muted_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


class Bridge(QObject):
    agent_message = Signal(str)
    agent_done = Signal()
    render_log = Signal(str)
    error = Signal(str)
    refresh = Signal()
    render_done = Signal(str)


class KeyDialog(QDialog):
    def __init__(self, pool: GeminiKeyPool, parent=None) -> None:
        super().__init__(parent)
        self.pool = pool
        self.setWindowTitle("Kelola Gemini Key")
        self.resize(650, 455)
        self.setMinimumSize(560, 390)

        icon = asset_path("logo.png")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))

        layout = QVBoxLayout(self)
        compact_layout(layout, (12, 12, 12, 12), 8)

        head = QHBoxLayout()
        compact_layout(head, (0, 0, 0, 0), 6)
        title = QLabel("Gemini API / Auth Key")
        title.setObjectName("panelTitle")
        self.status = QLabel()
        self.status.setObjectName("statusChip")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.status)
        layout.addLayout(head)
        layout.addWidget(muted_label("Tempel satu key per baris. Maksimal 100 key. Key disimpan lokal dengan Windows DPAPI."))

        self.list = QListWidget()
        self.list.setTextElideMode(Qt.ElideMiddle)
        layout.addWidget(self.list, 2)

        self.input = QPlainTextEdit()
        self.input.setMaximumHeight(100)
        self.input.setPlaceholderText("Paste key di sini — satu key per baris.")
        layout.addWidget(self.input)

        row = QHBoxLayout()
        compact_layout(row, (0, 0, 0, 0), 6)
        add = QPushButton("+ Tambah")
        remove = QPushButton("Hapus")
        reactivate = QPushButton("Aktifkan Lagi")
        add.clicked.connect(self.add_keys)
        remove.clicked.connect(self.remove_key)
        reactivate.clicked.connect(self.reactivate_key)
        row.addWidget(add)
        row.addWidget(remove)
        row.addWidget(reactivate)
        row.addStretch(1)
        layout.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        for i, rec in enumerate(self.pool.records):
            state = "SIAP" if rec.available else ("NONAKTIF" if not rec.enabled else "COOLDOWN")
            detail = f" • {rec.last_error[:42]}" if rec.last_error else ""
            self.list.addItem(f"{i + 1:02d}. {rec.masked}  •  {state}{detail}")
        s = self.pool.summary()
        self.status.setText(
            f"{s['total']}/{MAX_KEYS} • siap {s['ready']} • cooldown {s['cooldown']} • nonaktif {s['disabled']}"
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

    def reactivate_key(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        rec = self.pool.records[row]
        rec.enabled = True
        rec.cooldown_until = 0.0
        rec.failures = 0
        rec.last_error = ""
        self.pool.save()
        self.refresh()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Full Album Maker")
        self.resize(1440, 840)
        self.setMinimumSize(1120, 690)

        logo = asset_path("logo.png")
        if logo.exists():
            self.setWindowIcon(QIcon(str(logo)))

        self.project = Project()
        self.controller = ProjectController(self.project)
        self.pool = GeminiKeyPool()
        self.agent = None
        self.agent_busy = False

        self.bridge = Bridge()
        self.bridge.agent_message.connect(self._agent_message)
        self.bridge.agent_done.connect(self._agent_done)
        self.bridge.render_log.connect(self._render_log)
        self.bridge.error.connect(self._error)
        self.bridge.refresh.connect(self.refresh)
        self.bridge.render_done.connect(self._render_done)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        compact_layout(outer, (9, 9, 9, 9), 8)

        outer.addWidget(self._header())

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self._media_panel())
        self.splitter.addWidget(self._center_panel())
        self.splitter.addWidget(self._agent_panel())
        self.splitter.setSizes([375, 535, 430])
        outer.addWidget(self.splitter, 1)

        self.refresh()

    def _frame(self, name: str, margins=(9, 9, 9, 9), spacing=7) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName(name)
        layout = QVBoxLayout(frame)
        compact_layout(layout, margins, spacing)
        return frame, layout

    def _header(self) -> QFrame:
        frame, row_wrap = self._frame("headerBar", (12, 8, 12, 8), 0)
        row = QHBoxLayout()
        compact_layout(row, (0, 0, 0, 0), 10)

        logo_label = QLabel()
        logo_label.setFixedSize(58, 58)
        logo = asset_path("logo.png")
        if logo.exists():
            pix = QPixmap(str(logo))
            logo_label.setPixmap(
                pix.scaled(54, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        row.addWidget(logo_label)

        brand = QVBoxLayout()
        compact_layout(brand, (0, 0, 0, 0), 0)
        title_row = QHBoxLayout()
        compact_layout(title_row, (0, 0, 0, 0), 4)
        title_a = QLabel("Full Album")
        title_a.setObjectName("brandTitle")
        title_b = QLabel("Maker")
        title_b.setObjectName("brandAccent")
        title_row.addWidget(title_a)
        title_row.addWidget(title_b)
        title_row.addStretch(1)
        brand.addLayout(title_row)
        subtitle = QLabel("TURN YOUR MUSIC INTO VISUAL ALBUMS")
        subtitle.setObjectName("brandSubtitle")
        brand.addWidget(subtitle)
        row.addLayout(brand)
        row.addStretch(1)

        self.project_name = QComboBox()
        self.project_name.addItem("Proyek Album Baru")
        self.project_name.setMinimumWidth(155)
        row.addWidget(self.project_name)

        open_output = QToolButton()
        open_output.setText("Folder")
        open_output.setToolTip("Buka folder output")
        open_output.clicked.connect(self.open_output_folder)
        row.addWidget(open_output)

        settings = QToolButton()
        settings.setText("Key")
        settings.setToolTip("Kelola Gemini API key")
        settings.clicked.connect(self.open_keys)
        row.addWidget(settings)

        row_wrap.addLayout(row)
        return frame

    def _media_panel(self) -> QFrame:
        panel, lay = self._frame("panel")
        panel.setMinimumWidth(310)

        top = QHBoxLayout()
        compact_layout(top, (0, 0, 0, 0), 6)
        title = QLabel("Media")
        title.setObjectName("panelTitle")
        top.addWidget(title)
        top.addStretch(1)
        lay.addLayout(top)

        self.media_tabs = QTabWidget()
        self.media_tabs.setDocumentMode(True)
        self.media_tabs.addTab(self._video_tab(), "Footage  0")
        self.media_tabs.addTab(self._audio_tab(), "Lagu  0")
        lay.addWidget(self.media_tabs, 1)
        return panel

    def _video_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        compact_layout(layout, (8, 8, 8, 8), 6)

        title = QLabel("Footage Video")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        layout.addWidget(muted_label("Video visual yang akan diperlambat atau di-loop mengikuti durasi album."))

        self.video_list = QListWidget()
        self.video_list.setTextElideMode(Qt.ElideMiddle)
        layout.addWidget(self.video_list, 1)

        buttons = QHBoxLayout()
        compact_layout(buttons, (0, 0, 0, 0), 5)
        add = QPushButton("+ Tambah Video")
        remove = QPushButton("Hapus")
        add.clicked.connect(self.add_video)
        remove.clicked.connect(self.remove_video)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return page

    def _audio_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        compact_layout(layout, (8, 8, 8, 8), 6)

        title = QLabel("Album Songs")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        layout.addWidget(muted_label("Urutan lagu di sini menjadi urutan album dan chapter YouTube."))

        self.audio_list = QListWidget()
        self.audio_list.setTextElideMode(Qt.ElideMiddle)
        layout.addWidget(self.audio_list, 1)

        buttons = QHBoxLayout()
        compact_layout(buttons, (0, 0, 0, 0), 5)
        add = QPushButton("+ Tambah Lagu")
        remove = QPushButton("Hapus")
        sort = QPushButton("Urut A–Z")
        add.clicked.connect(self.add_audio)
        remove.clicked.connect(self.remove_audio)
        sort.clicked.connect(self.sort_audio)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addWidget(sort)
        layout.addLayout(buttons)
        return page

    def _center_panel(self) -> QFrame:
        panel, lay = self._frame("panel")
        panel.setMinimumWidth(410)

        top = QHBoxLayout()
        compact_layout(top, (0, 0, 0, 0), 7)
        title = QLabel("Pengaturan Video")
        title.setObjectName("panelTitle")
        top.addWidget(title)
        top.addStretch(1)

        preset_label = QLabel("Preset")
        preset_label.setObjectName("muted")
        top.addWidget(preset_label)

        self.preset = QComboBox()
        self.preset.addItem("YouTube 1080p", ((1920, 1080), 30, "12M", "h264"))
        self.preset.addItem("YouTube 1440p", ((2560, 1440), 30, "20M", "h264"))
        self.preset.addItem("YouTube 4K", ((3840, 2160), 30, "45M", "h264"))
        self.preset.currentIndexChanged.connect(self.apply_preset)
        top.addWidget(self.preset)
        lay.addLayout(top)

        settings_card, card_layout = self._frame("card", (10, 10, 10, 10), 7)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(7)

        self.resolution = QComboBox()
        for label, data in [
            ("1920 × 1080 (Full HD)", (1920, 1080)),
            ("2560 × 1440 (2K)", (2560, 1440)),
            ("3840 × 2160 (4K UHD)", (3840, 2160)),
        ]:
            self.resolution.addItem(label, data)

        self.aspect = QComboBox()
        self.aspect.addItem("16:9 Landscape", "16:9")

        self.fps = QComboBox()
        for value in (24, 25, 30, 50, 60):
            self.fps.addItem(f"{value} fps", value)
        self.fps.setCurrentIndex(self.fps.findData(30))

        self.video_bitrate = QComboBox()
        self.video_bitrate.addItem("Standard 12 Mbps", "12M")
        self.video_bitrate.addItem("Tinggi 20 Mbps", "20M")
        self.video_bitrate.addItem("4K 45 Mbps", "45M")

        self.codec = QComboBox()
        self.codec.addItem("H.264 (MP4)", "h264")
        self.codec.addItem("H.265 / HEVC", "h265")

        self.audio_bitrate = QComboBox()
        self.audio_bitrate.addItem("AAC 192 kbps", "192k")
        self.audio_bitrate.addItem("AAC 256 kbps", "256k")
        self.audio_bitrate.addItem("AAC 320 kbps", "320k")
        self.audio_bitrate.setCurrentIndex(self.audio_bitrate.findData("320k"))

        self.auto_match = QCheckBox("Cocokkan durasi otomatis")
        self.auto_match.setChecked(True)

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
        self.loop_mode.addItem("Auto + Loop", "auto")
        self.loop_mode.addItem("Loop", "loop")
        self.loop_mode.addItem("Ping-Pong", "pingpong")
        self.loop_mode.addItem("Tanpa Loop", "none")

        controls = (
            self.resolution,
            self.fps,
            self.video_bitrate,
            self.codec,
            self.audio_bitrate,
            self.loop_mode,
        )
        for control in controls:
            control.currentIndexChanged.connect(self.apply_settings)
        self.auto_match.toggled.connect(self.apply_settings)
        self.manual_speed.valueChanged.connect(self.apply_settings)
        self.min_speed.valueChanged.connect(self.apply_settings)

        self._grid_field(grid, 0, 0, "Resolusi", self.resolution)
        self._grid_field(grid, 0, 1, "Aspect Ratio", self.aspect)
        self._grid_field(grid, 1, 0, "Frame Rate", self.fps)
        self._grid_field(grid, 1, 1, "Bitrate", self.video_bitrate)
        self._grid_field(grid, 2, 0, "Video Codec", self.codec)
        self._grid_field(grid, 2, 1, "Audio Codec", self.audio_bitrate)
        self._grid_field(grid, 3, 0, "Speed Manual", self.manual_speed)
        self._grid_field(grid, 3, 1, "Batas Slowmo", self.min_speed)
        self._grid_field(grid, 4, 0, "Jika Footage Kurang", self.loop_mode)

        auto_wrap = QWidget()
        auto_layout = QVBoxLayout(auto_wrap)
        compact_layout(auto_layout, (0, 0, 0, 0), 2)
        auto_layout.addWidget(self.auto_match)
        auto_layout.addWidget(muted_label("Audio tidak ikut diperlambat."))
        grid.addWidget(auto_wrap, 4, 1)

        card_layout.addLayout(grid)
        lay.addWidget(settings_card)

        log_header = QHBoxLayout()
        compact_layout(log_header, (0, 2, 0, 0), 6)
        log_title = QLabel("Render Log")
        log_title.setObjectName("panelTitle")
        clear_log = QPushButton("Bersihkan")
        clear_log.clicked.connect(lambda: self.log.clear())
        log_header.addWidget(log_title)
        log_header.addStretch(1)
        log_header.addWidget(clear_log)
        lay.addLayout(log_header)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(125)
        self.log.setPlaceholderText("Log FFmpeg dan status render akan muncul di sini.")
        lay.addWidget(self.log, 1)

        chips = QHBoxLayout()
        compact_layout(chips, (0, 0, 0, 0), 5)
        self.status_labels: dict[str, QLabel] = {}
        for key in ("video", "album", "speed", "loop"):
            label = QLabel()
            label.setObjectName("statusChip")
            label.setMinimumHeight(22)
            label.setAlignment(Qt.AlignCenter)
            self.status_labels[key] = label
            chips.addWidget(label, 1)
        lay.addLayout(chips)

        render_card, render_layout = self._frame("renderCard", (10, 8, 10, 9), 6)
        ready_row = QHBoxLayout()
        compact_layout(ready_row, (0, 0, 0, 0), 7)

        ready_text = QVBoxLayout()
        compact_layout(ready_text, (0, 0, 0, 0), 0)
        ready_title = QLabel("Siap dirender")
        ready_title.setObjectName("readyTitle")
        self.ready_summary = QLabel("Tambahkan footage dan lagu untuk memulai.")
        self.ready_summary.setObjectName("muted")
        ready_text.addWidget(ready_title)
        ready_text.addWidget(self.ready_summary)
        ready_row.addLayout(ready_text, 1)

        open_folder = QPushButton("Buka Output")
        open_folder.clicked.connect(self.open_output_folder)
        ready_row.addWidget(open_folder)
        render_layout.addLayout(ready_row)

        self.render_btn = QPushButton("▶  Render Full Album")
        self.render_btn.setObjectName("renderButton")
        self.render_btn.clicked.connect(self.render)
        render_layout.addWidget(self.render_btn)

        lay.addWidget(render_card)
        return panel

    def _grid_field(self, grid: QGridLayout, row: int, column: int, title: str, widget: QWidget) -> None:
        box = QWidget()
        lay = QVBoxLayout(box)
        compact_layout(lay, (0, 0, 0, 0), 3)
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        lay.addWidget(label)
        lay.addWidget(widget)
        grid.addWidget(box, row, column)

    def _agent_panel(self) -> QFrame:
        panel, lay = self._frame("panel")
        panel.setMinimumWidth(330)

        top = QHBoxLayout()
        compact_layout(top, (0, 0, 0, 0), 6)
        title = QLabel("✦  Gemini Agent")
        title.setObjectName("panelTitle")
        self.key_status = QLabel()
        self.key_status.setObjectName("statusChip")
        keys = QPushButton("API Key")
        keys.clicked.connect(self.open_keys)
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(self.key_status)
        top.addWidget(keys)
        lay.addLayout(top)
        lay.addWidget(muted_label("Gunakan bahasa alami untuk mengatur slowmo, loop, resolusi, FPS, codec, dan urutan lagu."))

        self.agent_tabs = QTabWidget()
        self.agent_tabs.setDocumentMode(True)
        self.agent_tabs.addTab(self._agent_chat_tab(), "Chat")
        self.agent_tabs.addTab(
            self._agent_actions_tab(
                "Ide Video",
                [
                    ("Konsep album", "Analisis proyek ini dan berikan konsep visual full album yang konsisten."),
                    ("Pilih footage", "Analisis durasi proyek dan sarankan penggunaan footage terbaik untuk album ini."),
                    ("Ritme visual", "Sarankan ritme visual dan strategi slowmo yang nyaman untuk album ini."),
                ],
            ),
            "Ide Video",
        )
        self.agent_tabs.addTab(
            self._agent_actions_tab(
                "Gaya",
                [
                    ("Sinematik", "Atur proyek ini untuk tampilan sinematik 16:9 yang halus dan jelaskan setelannya."),
                    ("Minimalis", "Sarankan setelan proyek full album dengan gaya visual minimalis dan tidak berlebihan."),
                    ("YouTube 4K", "Atur proyek ke 4K 30 fps H.264 dengan kualitas tinggi dan strategi durasi yang aman."),
                ],
            ),
            "Gaya",
        )
        self.agent_tabs.addTab(
            self._agent_actions_tab(
                "Otomasi",
                [
                    ("Auto durasi", "Aktifkan pencocokan durasi otomatis minimal 0,5x dan gunakan loop jika kurang."),
                    ("Standar YouTube", "Atur proyek ke 1080p 30 fps H.264 dan auto loop."),
                    ("Urutkan lagu", "Urutkan semua lagu berdasarkan nama file lalu jelaskan hasilnya."),
                ],
            ),
            "Otomasi",
        )
        lay.addWidget(self.agent_tabs, 1)
        return panel

    def _agent_chat_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        compact_layout(layout, (8, 8, 8, 8), 7)

        welcome, wlay = self._frame("welcomeCard", (12, 10, 12, 10), 4)
        welcome_title = QLabel("✦  Halo, saya Gemini Agent")
        welcome_title.setObjectName("readyTitle")
        welcome_text = muted_label(
            "Saya bisa membaca kondisi proyek dan mengubah pengaturan melalui tool internal aplikasi."
        )
        wlay.addWidget(welcome_title)
        wlay.addWidget(welcome_text)
        layout.addWidget(welcome)

        for label, prompt in [
            ("Analisis album dan sarankan setelan", "Analisis proyek ini dan sarankan setelan terbaik berdasarkan durasi footage dan album."),
            ("Cocokkan footage dengan durasi lagu", "Aktifkan pencocokan durasi otomatis minimal 0,5x dan gunakan loop bila footage masih kurang."),
            ("Buat setelan YouTube 1080p", "Atur proyek ke 1080p 30 fps H.264 dengan kualitas yang cocok untuk YouTube."),
        ]:
            btn = QPushButton(label + "  ›")
            btn.setObjectName("quickAction")
            btn.clicked.connect(lambda _=False, p=prompt: self.quick_prompt(p))
            layout.addWidget(btn)

        self.chat = QPlainTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setPlaceholderText("Percakapan Gemini akan tampil di sini.")
        layout.addWidget(self.chat, 1)

        model_row = QHBoxLayout()
        compact_layout(model_row, (0, 0, 0, 0), 5)
        model_label = QLabel("Model")
        model_label.setObjectName("muted")
        self.model = QLineEdit("gemini-3.8-flash")
        model_row.addWidget(model_label)
        model_row.addWidget(self.model, 1)
        layout.addLayout(model_row)

        self.prompt = QPlainTextEdit()
        self.prompt.setMaximumHeight(72)
        self.prompt.setPlaceholderText("Tulis perintah untuk Gemini Agent…")
        layout.addWidget(self.prompt)

        self.agent_send_btn = QPushButton("Kirim ke Gemini  ➜")
        self.agent_send_btn.setObjectName("primaryButton")
        self.agent_send_btn.clicked.connect(self.ask_agent)
        layout.addWidget(self.agent_send_btn)
        return page

    def _agent_actions_tab(self, title: str, actions: list[tuple[str, str]]) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        compact_layout(layout, (9, 9, 9, 9), 7)

        heading = QLabel(title)
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)
        layout.addWidget(muted_label("Klik aksi untuk mengirim instruksi yang sesuai ke Gemini Agent."))

        for label, prompt in actions:
            btn = QPushButton(label + "  ›")
            btn.setObjectName("quickAction")
            btn.clicked.connect(lambda _=False, p=prompt: self.quick_prompt(p))
            layout.addWidget(btn)
        layout.addStretch(1)
        return page

    def apply_preset(self, *_):
        data = self.preset.currentData()
        if not data:
            return
        resolution, fps, bitrate, codec = data
        controls = [self.resolution, self.fps, self.video_bitrate, self.codec]
        for control in controls:
            control.blockSignals(True)
        try:
            idx = self.resolution.findData(resolution)
            if idx >= 0:
                self.resolution.setCurrentIndex(idx)
            idx = self.fps.findData(fps)
            if idx >= 0:
                self.fps.setCurrentIndex(idx)
            idx = self.video_bitrate.findData(bitrate)
            if idx >= 0:
                self.video_bitrate.setCurrentIndex(idx)
            idx = self.codec.findData(codec)
            if idx >= 0:
                self.codec.setCurrentIndex(idx)
        finally:
            for control in controls:
                control.blockSignals(False)
        self.apply_settings()

    def apply_settings(self, *_):
        s = self.project.settings
        s.auto_speed = bool(self.auto_match.isChecked())
        s.manual_speed = float(self.manual_speed.value())
        s.min_speed = float(self.min_speed.value())
        s.loop_mode = self.loop_mode.currentData()
        s.width, s.height = self.resolution.currentData()
        s.fps = int(self.fps.currentData())
        s.codec = self.codec.currentData()
        s.video_bitrate = self.video_bitrate.currentData()
        s.audio_bitrate = self.audio_bitrate.currentData()
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
            self.video_list.addItem(f"▣  {item.name}\n     {fmt(item.duration)}")

        self.audio_list.clear()
        current = 0.0
        for index, item in enumerate(self.project.audios, start=1):
            self.audio_list.addItem(
                f"{index:02d}   ♪  {item.name}\n       mulai {fmt(current)}  •  durasi {fmt(item.duration)}"
            )
            current += item.duration

        self.media_tabs.setTabText(0, f"Footage  {len(self.project.videos)}")
        self.media_tabs.setTabText(1, f"Lagu  {len(self.project.audios)}")

        p = self.project
        self.status_labels["video"].setText(f"Footage  {fmt(p.total_video_duration)}")
        self.status_labels["album"].setText(f"Album  {fmt(p.total_audio_duration)}")
        self.status_labels["speed"].setText(f"Speed  {p.planned_speed():.3f}×")
        self.status_labels["loop"].setText(f"Loop  {'YA' if p.needs_loop() else 'TIDAK'}")

        if p.videos and p.audios:
            self.ready_summary.setText(
                f"{len(p.audios)} lagu • {len(p.videos)} footage • album {fmt(p.total_audio_duration)} • video hasil {fmt(p.adjusted_video_duration())}"
            )
        else:
            self.ready_summary.setText("Tambahkan footage dan lagu untuk memulai.")

        settings = p.settings
        controls = [
            self.auto_match,
            self.manual_speed,
            self.min_speed,
            self.loop_mode,
            self.resolution,
            self.fps,
            self.video_bitrate,
            self.audio_bitrate,
            self.codec,
        ]
        for control in controls:
            control.blockSignals(True)
        try:
            self.auto_match.setChecked(settings.auto_speed)
            self.manual_speed.setValue(settings.manual_speed)
            self.min_speed.setValue(settings.min_speed)

            for widget, value in [
                (self.loop_mode, settings.loop_mode),
                (self.resolution, (settings.width, settings.height)),
                (self.fps, settings.fps),
                (self.video_bitrate, settings.video_bitrate),
                (self.audio_bitrate, settings.audio_bitrate),
                (self.codec, settings.codec),
            ]:
                idx = widget.findData(value)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
        finally:
            for control in controls:
                control.blockSignals(False)

        summary = self.pool.summary()
        self.key_status.setText(f"{summary['ready']}/{summary['total']} key")

    def open_keys(self):
        KeyDialog(self.pool, self).exec()
        self.refresh()

    def open_output_folder(self):
        folder = output_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def quick_prompt(self, text: str):
        self.agent_tabs.setCurrentIndex(0)
        self.prompt.setPlainText(text)
        self.ask_agent()

    def ask_agent(self):
        text = self.prompt.toPlainText().strip()
        if not text or self.agent_busy:
            return

        self.agent_busy = True
        self.agent_send_btn.setEnabled(False)
        self.agent_send_btn.setText("Gemini sedang bekerja…")
        self.prompt.clear()
        self.chat.appendPlainText(f"ANDA\n{text}\n")
        model = self.model.text().strip() or "gemini-3.8-flash"

        def work():
            try:
                if self.agent is None or self.agent.model != model:
                    self.agent = GeminiAgent(self.pool, self.controller, model=model)
                answer = self.agent.ask(text)
                self.bridge.agent_message.emit(answer)
                self.bridge.refresh.emit()
            except Exception as exc:
                self.bridge.error.emit(str(exc))
            finally:
                self.bridge.agent_done.emit()

        threading.Thread(target=work, daemon=True).start()

    def _agent_message(self, text):
        self.chat.appendPlainText(f"GEMINI\n{text}\n")

    def _agent_done(self):
        self.agent_busy = False
        self.agent_send_btn.setEnabled(True)
        self.agent_send_btn.setText("Kirim ke Gemini  ➜")

    def render(self):
        if not self.project.videos:
            self._error("Tambahkan minimal satu footage video sebelum render.")
            return
        if not self.project.audios:
            self._error("Tambahkan minimal satu lagu sebelum render.")
            return

        default_path = str(output_dir() / "FULL_ALBUM_FINAL.mp4")
        path, _ = QFileDialog.getSaveFileName(
            self, "Simpan Full Album", default_path, "MP4 (*.mp4)"
        )
        if not path:
            return

        self.render_btn.setEnabled(False)
        self.render_btn.setText("Rendering…")
        self.log.clear()
        self.log.appendPlainText("Menyiapkan proyek render…")

        project_snapshot = deepcopy(self.project)

        def work():
            try:
                renderer = FFmpegRenderer(project_snapshot)
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
        self.render_btn.setText("▶  Render Full Album")
        if path:
            self.log.appendPlainText("Render selesai.")
            QMessageBox.information(self, "Render selesai", f"Video selesai:\n{path}")

    def _error(self, text):
        QMessageBox.critical(self, "Full Album Maker", text)


def run() -> int:
    app = QApplication([])
    app.setApplicationName("Full Album Maker")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)

    logo = asset_path("logo.png")
    if logo.exists():
        app.setWindowIcon(QIcon(str(logo)))

    win = MainWindow()
    win.show()
    return app.exec()
