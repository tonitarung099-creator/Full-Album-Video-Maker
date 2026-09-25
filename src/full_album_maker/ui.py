from __future__ import annotations

import threading
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QDoubleSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .branding import brand_icon, brand_pixmap
from .controller import ProjectController
from .gemini_agent import GeminiAgent
from .key_pool import GeminiKeyPool, MAX_KEYS
from .media import MediaProbeError, probe_duration
from .paths import output_dir
from .project import MediaItem, Project
from .project_io import load_project, save_project
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


class TimelinePreview(QWidget):
    """Visual timeline for Step 1 UI. The real timeline engine is added in Step 2."""

    VIDEO_COLORS = (
        QColor("#2e7df6"),
        QColor("#7147ef"),
        QColor("#159bd7"),
        QColor("#17b875"),
        QColor("#b650e7"),
    )
    AUDIO_COLORS = (
        QColor("#8747ef"),
        QColor("#2e8df7"),
        QColor("#24a86d"),
        QColor("#d79d2e"),
        QColor("#df6a45"),
        QColor("#d44dac"),
        QColor("#755be8"),
        QColor("#3b80e6"),
    )

    def __init__(self, project: Project, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.timeline_ready = False
        self.setMinimumHeight(260)
        self.setObjectName("timelinePreview")

    def set_project(self, project: Project) -> None:
        self.project = project
        self.update()

    def set_ready(self, ready: bool) -> None:
        self.timeline_ready = ready
        self.update()

    def _rect_for_span(self, x0: float, x1: float, y: float, h: float, duration: float, left: float, width: float) -> QRectF:
        if duration <= 0:
            return QRectF(left, y, 0, h)
        start = left + (x0 / duration) * width
        end = left + (x1 / duration) * width
        return QRectF(start, y, max(2.0, end - start - 2.0), h)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#08111d"))

        width = self.width()
        height = self.height()
        label_w = 78
        left = label_w + 12
        right = 12
        usable = max(80, width - left - right)

        album = self.project.total_audio_duration
        video_adjusted = self.project.adjusted_video_duration()
        duration = max(album, video_adjusted, 1.0)

        ruler_y = 28
        video_y = 58
        video_h = max(62, int((height - 112) * 0.48))
        audio_y = video_y + video_h + 12
        audio_h = max(54, height - audio_y - 28)

        painter.setPen(QPen(QColor("#66778e"), 1))
        painter.drawLine(int(left), ruler_y, int(left + usable), ruler_y)
        for i in range(7):
            x = left + usable * i / 6
            painter.drawLine(int(x), ruler_y - 4, int(x), ruler_y + 6)
            stamp = fmt(duration * i / 6)
            painter.setPen(QColor("#9ca9b9"))
            painter.drawText(QRectF(x - 31, 4, 62, 18), Qt.AlignCenter, stamp)
            painter.setPen(QPen(QColor("#17263a"), 1, Qt.DashLine))
            painter.drawLine(int(x), ruler_y + 8, int(x), int(audio_y + audio_h))

        painter.setPen(QColor("#56cfff"))
        painter.drawText(QRectF(8, video_y + 5, label_w - 8, 20), Qt.AlignLeft | Qt.AlignVCenter, "▣ VIDEO")
        painter.setPen(QColor("#8191a7"))
        painter.drawText(QRectF(8, video_y + 25, label_w - 8, 18), Qt.AlignLeft | Qt.AlignVCenter, "(footage)")
        painter.setPen(QColor("#70b8ff"))
        painter.drawText(QRectF(8, audio_y + 5, label_w - 8, 20), Qt.AlignLeft | Qt.AlignVCenter, "♪ AUDIO")
        painter.setPen(QColor("#8191a7"))
        painter.drawText(QRectF(8, audio_y + 25, label_w - 8, 18), Qt.AlignLeft | Qt.AlignVCenter, "(album)")

        if not self.project.videos and not self.project.audios:
            painter.setPen(QColor("#718198"))
            painter.drawText(
                QRectF(left, video_y, usable, video_h + audio_h + 12),
                Qt.AlignCenter,
                "Timeline akan muncul setelah footage dan lagu ditambahkan.",
            )
            painter.end()
            return

        speed = max(0.01, self.project.planned_speed())
        cursor = 0.0
        for index, item in enumerate(self.project.videos):
            clip_duration = max(0.0, item.duration / speed)
            if cursor >= duration:
                break
            end = min(duration, cursor + clip_duration)
            rect = self._rect_for_span(cursor, end, video_y, video_h, duration, left, usable)
            color = self.VIDEO_COLORS[index % len(self.VIDEO_COLORS)]
            painter.setPen(QPen(color.lighter(145), 1))
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(QColor("#ffffff"))
            name = Path(item.path).stem
            label = f"{name[:20]} • {speed:.2f}x"
            painter.drawText(rect.adjusted(7, 5, -5, -22), Qt.AlignLeft | Qt.AlignTop, label)
            painter.setPen(QColor("#dce8f7"))
            painter.drawText(
                rect.adjusted(7, 24, -5, -4),
                Qt.AlignLeft | Qt.AlignBottom,
                f"{fmt(cursor)} – {fmt(end)}",
            )
            cursor = end

        if album > 0 and video_adjusted < album:
            start = max(0.0, video_adjusted)
            rect = self._rect_for_span(start, album, video_y, video_h, duration, left, usable)
            painter.setPen(QPen(QColor("#4cf49a"), 1))
            painter.setBrush(QColor("#10a866"))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(rect.adjusted(7, 6, -4, -4), Qt.AlignLeft | Qt.AlignTop, "↻ Loop")

        if album > 0 and video_adjusted > album:
            cut = video_adjusted - album
            x = left + usable * (album / duration)
            marker_w = min(116.0, max(72.0, usable * cut / duration))
            rect = QRectF(max(left, x - marker_w), video_y, marker_w, video_h)
            painter.setPen(QPen(QColor("#ff6485"), 1))
            painter.setBrush(QColor("#c9325d"))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(rect.adjusted(7, 6, -4, -4), Qt.AlignLeft | Qt.AlignTop, f"✂ Auto Cut\n{fmt(cut)}")

        audio_duration = max(album, 1.0)
        cursor = 0.0
        for index, item in enumerate(self.project.audios):
            end = min(album, cursor + max(0.0, item.duration))
            rect = self._rect_for_span(cursor, end, audio_y, audio_h, audio_duration, left, usable)
            color = self.AUDIO_COLORS[index % len(self.AUDIO_COLORS)]
            painter.setPen(QPen(color.lighter(145), 1))
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(rect.adjusted(5, 4, -4, -18), Qt.AlignLeft | Qt.AlignTop, f"Song {index + 1:02d}")
            painter.setPen(QColor("#e6efff"))
            painter.drawText(rect.adjusted(5, 20, -4, -4), Qt.AlignLeft | Qt.AlignBottom, fmt(item.duration))
            cursor = end

        master = album if album > 0 else duration
        if self.timeline_ready and master > 0:
            playhead = left + usable * 0.38
            painter.setPen(QPen(QColor("#ff466d"), 2))
            painter.drawLine(int(playhead), ruler_y + 8, int(playhead), int(audio_y + audio_h))
            painter.setBrush(QColor("#ff466d"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRectF(playhead - 24, ruler_y - 22, 48, 18), 5, 5)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(QRectF(playhead - 24, ruler_y - 22, 48, 18), Qt.AlignCenter, fmt(master * 0.38))

        painter.end()


class KeyDialog(QDialog):
    def __init__(self, pool: GeminiKeyPool, parent=None) -> None:
        super().__init__(parent)
        self.pool = pool
        self.setWindowTitle("Kelola Gemini Key")
        self.resize(650, 455)
        self.setMinimumSize(560, 390)
        self.setWindowIcon(brand_icon())

        layout = QVBoxLayout(self)
        compact_layout(layout, (12, 12, 12, 12), 8)

        head = QHBoxLayout()
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
        self.resize(1600, 900)
        self.setMinimumSize(1180, 780)
        self.setWindowIcon(brand_icon())

        self.project = Project()
        self.controller = ProjectController(self.project)
        self.pool = GeminiKeyPool()
        self.agent = None
        self.agent_busy = False
        self.timeline_ready = False

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
        compact_layout(outer, (7, 7, 7, 7), 7)

        outer.addWidget(self._header())

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("mainSplitter")
        self.splitter.setHandleWidth(7)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self._media_panel())
        self.splitter.addWidget(self._center_panel())
        self.splitter.addWidget(self._agent_panel())
        self.splitter.setSizes([365, 785, 380])
        outer.addWidget(self.splitter, 1)

        outer.addWidget(self._bottom_status())
        self.refresh()

    def _frame(self, name: str, margins=(9, 9, 9, 9), spacing=7) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName(name)
        layout = QVBoxLayout(frame)
        compact_layout(layout, margins, spacing)
        return frame, layout

    def _header(self) -> QFrame:
        frame, wrap = self._frame("headerBar", (13, 7, 13, 7), 0)
        row = QHBoxLayout()
        compact_layout(row, (0, 0, 0, 0), 9)

        logo = QLabel()
        logo.setFixedSize(66, 66)
        logo.setPixmap(brand_pixmap(62))
        row.addWidget(logo)

        brand = QVBoxLayout()
        compact_layout(brand, (0, 0, 0, 0), 0)
        title = QLabel("Full Album Maker")
        title.setObjectName("brandTitle")
        subtitle = QLabel("Footage + Album Audio + Auto Timeline")
        subtitle.setObjectName("brandSubtitle")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        row.addLayout(brand)
        row.addStretch(1)

        for text, callback in [
            ("▣  Open Project", self.load_project_file),
            ("▣  Save Project", self.save_project_file),
            ("▣  Output Folder", self.open_output_folder),
            ("⚿  API Keys", self.open_keys),
        ]:
            button = QToolButton()
            button.setText(text)
            button.setObjectName("headerButton")
            button.clicked.connect(callback)
            row.addWidget(button)

        wrap.addLayout(row)
        return frame

    def _media_panel(self) -> QFrame:
        panel, lay = self._frame("panel", (9, 8, 9, 8), 7)
        panel.setMinimumWidth(285)

        title = QLabel("◉  MEDIA")
        title.setObjectName("panelTitle")
        lay.addWidget(title)

        video_card, video_lay = self._frame("mediaCard", (8, 8, 8, 8), 6)
        video_head = QHBoxLayout()
        video_title_box = QVBoxLayout()
        compact_layout(video_title_box, (0, 0, 0, 0), 0)
        video_title = QLabel("▣  Footage Videos")
        video_title.setObjectName("sectionTitle")
        video_title_box.addWidget(video_title)
        video_title_box.addWidget(muted_label("Video yang akan digunakan sebagai visual album"))
        video_head.addLayout(video_title_box, 1)
        add_video = QPushButton("+  Add Video")
        add_video.setObjectName("accentButton")
        add_video.clicked.connect(self.add_video)
        video_head.addWidget(add_video)
        video_lay.addLayout(video_head)

        self.video_list = QListWidget()
        self.video_list.setTextElideMode(Qt.ElideMiddle)
        self.video_list.setMinimumHeight(150)
        video_lay.addWidget(self.video_list, 1)

        video_controls = QHBoxLayout()
        compact_layout(video_controls, (0, 0, 0, 0), 4)
        up_video = QPushButton("↑  Move Up")
        down_video = QPushButton("↓  Move Down")
        sort_video = QPushButton("A↕Z  Sort A–Z")
        up_video.clicked.connect(lambda: self.move_video_selected(-1))
        down_video.clicked.connect(lambda: self.move_video_selected(1))
        sort_video.clicked.connect(self.sort_video)
        for button in (up_video, down_video, sort_video):
            video_controls.addWidget(button)
        video_lay.addLayout(video_controls)

        self.video_total = QLabel()
        self.video_total.setObjectName("mediaSummary")
        video_lay.addWidget(self.video_total)
        lay.addWidget(video_card, 1)

        audio_card, audio_lay = self._frame("mediaCard", (8, 8, 8, 8), 6)
        audio_head = QHBoxLayout()
        audio_title_box = QVBoxLayout()
        compact_layout(audio_title_box, (0, 0, 0, 0), 0)
        audio_title = QLabel("♫  Album Songs")
        audio_title.setObjectName("sectionTitle")
        audio_title_box.addWidget(audio_title)
        audio_title_box.addWidget(muted_label("Daftar lagu dalam album (urutan menjadi timeline)"))
        audio_head.addLayout(audio_title_box, 1)
        add_audio = QPushButton("+  Add Songs")
        add_audio.setObjectName("accentButton")
        add_audio.clicked.connect(self.add_audio)
        audio_head.addWidget(add_audio)
        audio_lay.addLayout(audio_head)

        self.audio_list = QListWidget()
        self.audio_list.setTextElideMode(Qt.ElideMiddle)
        self.audio_list.setMinimumHeight(190)
        audio_lay.addWidget(self.audio_list, 1)

        audio_controls = QHBoxLayout()
        compact_layout(audio_controls, (0, 0, 0, 0), 4)
        up_audio = QPushButton("↑  Move Up")
        down_audio = QPushButton("↓  Move Down")
        sort_audio = QPushButton("A↕Z  Sort A–Z")
        up_audio.clicked.connect(lambda: self.move_audio_selected(-1))
        down_audio.clicked.connect(lambda: self.move_audio_selected(1))
        sort_audio.clicked.connect(self.sort_audio)
        for button in (up_audio, down_audio, sort_audio):
            audio_controls.addWidget(button)
        audio_lay.addLayout(audio_controls)

        self.audio_total = QLabel()
        self.audio_total.setObjectName("mediaSummary")
        audio_lay.addWidget(self.audio_total)
        lay.addWidget(audio_card, 1)
        return panel

    def _setting_card(self, title: str, widget: QWidget, help_text: str) -> QFrame:
        card, lay = self._frame("settingCard", (9, 8, 9, 8), 4)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        lay.addWidget(heading)
        lay.addWidget(widget)
        lay.addWidget(muted_label(help_text))
        return card

    def _center_panel(self) -> QFrame:
        panel, lay = self._frame("panel", (9, 8, 9, 8), 7)
        panel.setMinimumWidth(515)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        compact_layout(title_box, (0, 0, 0, 0), 0)
        title = QLabel("▣  AUTO TIMELINE")
        title.setObjectName("panelTitle")
        title_box.addWidget(title)
        title_box.addWidget(muted_label("Susun timeline otomatis berdasarkan lagu dan footage"))
        header.addLayout(title_box)
        header.addStretch(1)
        self.timeline_status = QLabel("Timeline Belum Disusun")
        self.timeline_status.setObjectName("timelineStatusPending")
        header.addWidget(self.timeline_status)
        lay.addLayout(header)

        self.auto_timeline_btn = QPushButton("⚡  AUTO SUSUN TIMELINE\nAnalisis footage + album dan buat timeline otomatis")
        self.auto_timeline_btn.setObjectName("autoTimelineButton")
        self.auto_timeline_btn.setFixedHeight(68)
        self.auto_timeline_btn.clicked.connect(self.preview_auto_timeline_step1)
        lay.addWidget(self.auto_timeline_btn)

        settings = QGridLayout()
        settings.setContentsMargins(0, 0, 0, 0)
        settings.setHorizontalSpacing(7)
        settings.setVerticalSpacing(0)

        self.slowmo_mode = QComboBox()
        self.slowmo_mode.addItem("Auto Fit", "auto")
        self.slowmo_mode.addItem("Kunci Slowmo", "locked")
        self.slowmo_mode.currentIndexChanged.connect(self.apply_settings)

        self.min_speed = QDoubleSpinBox()
        self.min_speed.setRange(0.05, 1.0)
        self.min_speed.setSingleStep(0.05)
        self.min_speed.setDecimals(2)
        self.min_speed.setValue(0.50)
        self.min_speed.setSuffix("x")
        self.min_speed.valueChanged.connect(self.apply_settings)

        self.loop_mode = QComboBox()
        self.loop_mode.addItem("Loop", "loop")
        self.loop_mode.addItem("Ping-Pong", "pingpong")
        self.loop_mode.addItem("Auto", "auto")
        self.loop_mode.addItem("Tanpa Loop", "none")
        self.loop_mode.currentIndexChanged.connect(self.apply_settings)

        self.preset = QComboBox()
        self.preset.addItem("YouTube 1080p", ((1920, 1080), 30, "12M", "h264"))
        self.preset.addItem("YouTube 1440p", ((2560, 1440), 30, "20M", "h264"))
        self.preset.addItem("YouTube 4K", ((3840, 2160), 30, "45M", "h264"))
        self.preset.currentIndexChanged.connect(self.apply_preset)

        settings.addWidget(self._setting_card("◔  Mode Slowmo", self.slowmo_mode, "Atur kecepatan footage agar pas dengan durasi album."), 0, 0)
        settings.addWidget(self._setting_card("◉  Minimum Slowmo", self.min_speed, "Kecepatan minimal untuk memperpanjang footage."), 0, 1)
        settings.addWidget(self._setting_card("↻  Jika Footage Kurang", self.loop_mode, "Ulangi footage saat durasi masih kurang."), 0, 2)
        settings.addWidget(self._setting_card("▣  Output Preset", self.preset, "Resolusi dan format output YouTube."), 0, 3)
        for i in range(4):
            settings.setColumnStretch(i, 1)
        lay.addLayout(settings)

        calc_card, calc_lay = self._frame("calcCard", (10, 8, 10, 8), 5)
        calc_head = QHBoxLayout()
        calc_title = QLabel("●  Contoh Perhitungan (Auto Cut)")
        calc_title.setObjectName("sectionTitle")
        calc_head.addWidget(calc_title)
        calc_head.addStretch(1)
        calc_lay.addLayout(calc_head)

        calc_grid = QGridLayout()
        calc_grid.setContentsMargins(0, 0, 0, 0)
        calc_grid.setHorizontalSpacing(14)
        self.calc_album = QLabel("00:00:00")
        self.calc_album.setObjectName("calcPurple")
        self.calc_video = QLabel("00:00:00")
        self.calc_video.setObjectName("calcCyan")
        self.calc_cut = QLabel("00:00:00")
        self.calc_cut.setObjectName("calcPink")
        for col, (caption, value) in enumerate([
            ("Album (durasi audio)", self.calc_album),
            ("Footage setelah slowmo", self.calc_video),
            ("Auto Cut", self.calc_cut),
        ]):
            box = QVBoxLayout()
            compact_layout(box, (0, 0, 0, 0), 1)
            box.addWidget(muted_label(caption))
            box.addWidget(value)
            calc_grid.addLayout(box, 0, col)
            calc_grid.setColumnStretch(col, 1)
        calc_lay.addLayout(calc_grid)
        lay.addWidget(calc_card)

        self.timeline_preview = TimelinePreview(self.project)
        lay.addWidget(self.timeline_preview, 1)

        legend = QHBoxLayout()
        compact_layout(legend, (2, 0, 2, 0), 10)
        info = QLabel("ⓘ  Penjelasan Timeline:")
        info.setObjectName("muted")
        legend.addWidget(info)
        for text in (
            "● Audio adalah master timeline",
            "● Jika footage lebih panjang → Auto Cut",
            "● Jika footage lebih pendek → Loop / Ping-Pong",
        ):
            label = QLabel(text)
            label.setObjectName("legend")
            legend.addWidget(label)
        legend.addStretch(1)
        lay.addLayout(legend)

        actions = QHBoxLayout()
        compact_layout(actions, (0, 0, 0, 0), 7)
        self.regenerate_btn = QPushButton("↻  Regenerate Auto Timeline")
        self.regenerate_btn.clicked.connect(self.preview_auto_timeline_step1)
        self.preview_btn = QPushButton("▶  Preview Plan")
        self.preview_btn.clicked.connect(self.preview_plan_step1)
        self.render_btn = QPushButton("▶  Render Full Album")
        self.render_btn.setObjectName("renderButton")
        self.render_btn.setMinimumHeight(42)
        self.render_btn.clicked.connect(self.render)
        actions.addWidget(self.regenerate_btn, 1)
        actions.addWidget(self.preview_btn, 1)
        actions.addWidget(self.render_btn, 2)
        lay.addLayout(actions)

        self.log = QPlainTextEdit()
        self.log.setVisible(False)
        return panel

    def _agent_panel(self) -> QFrame:
        panel, lay = self._frame("panel", (9, 8, 9, 8), 7)
        panel.setMinimumWidth(300)

        header = QHBoxLayout()
        title = QLabel("✦  GEMINI AGENT")
        title.setObjectName("panelTitle")
        header.addWidget(title)
        header.addStretch(1)

        self.model = QComboBox()
        self.model.addItem("Gemini 3.8 Flash", "gemini-3.8-flash")
        self.model.addItem("Gemini 3.7 Flash", "gemini-3.7-flash")
        self.model.addItem("Gemini 3.6 Flash", "gemini-3.6-flash")
        header.addWidget(self.model)
        lay.addLayout(header)

        agent_desc = muted_label("Gemini memahami bahasa manusia dan menerjemahkannya menjadi perintah aplikasi. Perhitungan teknis tetap dikerjakan engine lokal.")
        lay.addWidget(agent_desc)

        self.chat = QPlainTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setObjectName("chatArea")
        self.chat.setPlainText(
            "✦ GEMINI\n"
            "Halo! Saya Gemini Agent.\n"
            "Cukup tulis perintah seperti “susun semua lagu dan video”.\n"
            "Saya akan menerjemahkan maksud Anda menjadi aksi aplikasi.\n"
        )
        lay.addWidget(self.chat, 1)

        quick_title = QLabel("⚡  Aksi Cepat")
        quick_title.setObjectName("sectionTitle")
        lay.addWidget(quick_title)

        quick = QGridLayout()
        quick.setContentsMargins(0, 0, 0, 0)
        quick.setHorizontalSpacing(5)
        quick.setVerticalSpacing(5)
        actions = [
            ("⌕  Cek kesiapan proyek", "Validasi proyek ini dan jelaskan apakah sudah siap."),
            ("⚙  Optimalkan YouTube 1080p", "Optimalkan proyek ini untuk YouTube 1080p."),
            ("◔  Kunci slowmo 0.50x", "Atur slowmo ke 0,50x."),
            ("↻  Loop jika footage kurang", "Gunakan loop jika footage kurang."),
        ]
        for index, (label, prompt) in enumerate(actions):
            button = QPushButton(label)
            button.setObjectName("quickAction")
            button.clicked.connect(lambda _=False, p=prompt: self.quick_prompt(p))
            quick.addWidget(button, index // 2, index % 2)
        lay.addLayout(quick)

        prompt_row = QHBoxLayout()
        compact_layout(prompt_row, (0, 0, 0, 0), 5)
        self.prompt = QPlainTextEdit()
        self.prompt.setMaximumHeight(62)
        self.prompt.setPlaceholderText("Tulis perintah untuk Gemini Agent…")
        prompt_row.addWidget(self.prompt, 1)
        self.agent_send_btn = QPushButton("➤")
        self.agent_send_btn.setObjectName("sendButton")
        self.agent_send_btn.setFixedWidth(42)
        self.agent_send_btn.clicked.connect(self.ask_agent)
        prompt_row.addWidget(self.agent_send_btn)
        lay.addLayout(prompt_row)

        footer = QHBoxLayout()
        self.key_status = QLabel()
        self.key_status.setObjectName("statusChip")
        footer.addWidget(self.key_status)
        footer.addStretch(1)
        reset = QPushButton("Reset Chat")
        reset.clicked.connect(self.reset_agent_chat)
        footer.addWidget(reset)
        lay.addLayout(footer)
        return panel

    def _bottom_status(self) -> QFrame:
        bar, lay = self._frame("bottomBar", (8, 5, 8, 5), 0)
        row = QHBoxLayout()
        compact_layout(row, (0, 0, 0, 0), 0)
        self.bottom_labels: dict[str, QLabel] = {}
        for key in ("footage", "album", "speed", "loop", "cut", "output"):
            label = QLabel()
            label.setObjectName("bottomMetric")
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumHeight(34)
            self.bottom_labels[key] = label
            row.addWidget(label, 1)
        lay.addLayout(row)
        return bar

    def apply_preset(self, *_):
        data = self.preset.currentData()
        if not data:
            return
        resolution, fps, bitrate, codec = data
        s = self.project.settings
        s.width, s.height = resolution
        s.fps = fps
        s.video_bitrate = bitrate
        s.codec = codec
        self.timeline_ready = False
        self.refresh()

    def apply_settings(self, *_):
        s = self.project.settings
        s.auto_speed = self.slowmo_mode.currentData() == "auto"
        if self.slowmo_mode.currentData() == "locked":
            s.auto_speed = False
            s.manual_speed = float(self.min_speed.value())
        s.min_speed = float(self.min_speed.value())
        s.loop_mode = self.loop_mode.currentData()
        self.timeline_ready = False
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
        existing = {str(Path(x.path).resolve()).casefold() for x in target}
        skipped = 0
        for path in paths:
            key = str(Path(path).resolve()).casefold()
            if key in existing:
                skipped += 1
                continue
            try:
                target.append(MediaItem(path=path, duration=probe_duration(path)))
                existing.add(key)
            except MediaProbeError as exc:
                self._error(str(exc))
        if skipped:
            self.log.appendPlainText(f"{skipped} file duplikat dilewati.")
        self.timeline_ready = False
        self.refresh()

    def move_video_selected(self, direction: int):
        row = self.video_list.currentRow()
        if row < 0:
            return
        target = row + direction
        if not 0 <= target < len(self.project.videos):
            return
        self.project.videos[row], self.project.videos[target] = self.project.videos[target], self.project.videos[row]
        self.timeline_ready = False
        self.refresh()
        self.video_list.setCurrentRow(target)

    def move_audio_selected(self, direction: int):
        row = self.audio_list.currentRow()
        if row < 0:
            return
        target = row + direction
        if not 0 <= target < len(self.project.audios):
            return
        self.project.audios[row], self.project.audios[target] = self.project.audios[target], self.project.audios[row]
        self.timeline_ready = False
        self.refresh()
        self.audio_list.setCurrentRow(target)

    def sort_video(self):
        self.project.videos.sort(key=lambda x: x.name.casefold())
        self.timeline_ready = False
        self.refresh()

    def sort_audio(self):
        self.project.sort_audio_by_name()
        self.timeline_ready = False
        self.refresh()

    def save_project_file(self):
        default = str(output_dir() / "Full_Album_Project.json")
        path, _ = QFileDialog.getSaveFileName(self, "Simpan Proyek", default, "Full Album Project (*.json)")
        if not path:
            return
        try:
            save_project(path, self.project)
        except Exception as exc:
            self._error(f"Gagal menyimpan proyek: {exc}")

    def load_project_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Buka Proyek", "", "Full Album Project (*.json)")
        if not path:
            return
        try:
            self.project = load_project(path)
            self.controller = ProjectController(self.project)
            self.agent = None
            self.timeline_ready = False
            self.timeline_preview.set_project(self.project)
            self.refresh()
        except Exception as exc:
            self._error(f"Gagal membuka proyek: {exc}")

    def open_keys(self):
        KeyDialog(self.pool, self).exec()
        self.refresh()

    def open_output_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_dir())))

    def preview_auto_timeline_step1(self):
        if not self.project.videos or not self.project.audios:
            self.timeline_ready = False
            self.refresh()
            QMessageBox.information(
                self,
                "Auto Timeline",
                "Langkah 1 saat ini baru menyelesaikan tampilan. Tambahkan footage dan lagu untuk melihat pratinjau visual. Engine timeline lokal akan dibuat pada Langkah 2.",
            )
            return
        self.timeline_ready = True
        self.timeline_preview.set_ready(True)
        self.refresh()
        self.chat.appendPlainText(
            "\nAPP\nPratinjau UI Auto Timeline ditampilkan. Engine timeline presisi belum diaktifkan pada Langkah 1.\n"
        )

    def preview_plan_step1(self):
        QMessageBox.information(
            self,
            "Preview Plan",
            "Preview Plan adalah bagian tampilan Langkah 1. Data timeline presisi akan mulai dibuat pada Langkah 2.",
        )

    def quick_prompt(self, text: str):
        self.prompt.setPlainText(text)
        self.ask_agent()

    def ask_agent(self):
        text = self.prompt.toPlainText().strip()
        if not text or self.agent_busy:
            return

        self.agent_busy = True
        self.agent_send_btn.setEnabled(False)
        self.prompt.clear()
        self.chat.appendPlainText(f"\nANDA\n{text}\n")
        model = self.model.currentData() or "gemini-3.8-flash"

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
        self.chat.appendPlainText(f"\nGEMINI\n{text}\n")

    def _agent_done(self):
        self.agent_busy = False
        self.agent_send_btn.setEnabled(True)

    def reset_agent_chat(self):
        if self.agent is not None:
            self.agent.reset()
        self.chat.setPlainText(
            "✦ GEMINI\nHalo! Saya Gemini Agent.\nCukup tulis perintah seperti “susun semua lagu dan video”.\n"
        )

    def refresh(self):
        self.video_list.clear()
        for item in self.project.videos:
            self.video_list.addItem(f"▣  {item.name}                                      {fmt(item.duration)}")

        self.audio_list.clear()
        for index, item in enumerate(self.project.audios, start=1):
            self.audio_list.addItem(f"♪  {index:02d}   {Path(item.path).stem}                              {fmt(item.duration)}")

        p = self.project
        speed = p.planned_speed()
        adjusted = p.adjusted_video_duration()
        album = p.total_audio_duration
        cut = max(0.0, adjusted - album) if album > 0 else 0.0

        self.video_total.setText(f"▣   Total Durasi Footage        {fmt(p.total_video_duration)}     {len(p.videos)} file")
        self.audio_total.setText(f"♫   Total Durasi Album          {fmt(album)}     {len(p.audios)} lagu")

        self.calc_album.setText(fmt(album))
        self.calc_video.setText(fmt(adjusted))
        self.calc_cut.setText(f"potong {fmt(cut)}" if cut > 0 else "tidak perlu")

        if self.timeline_ready:
            self.timeline_status.setText("✓  Timeline Siap")
            self.timeline_status.setObjectName("timelineStatusReady")
        else:
            self.timeline_status.setText("Timeline Perlu Diperbarui" if (p.videos or p.audios) else "Timeline Belum Disusun")
            self.timeline_status.setObjectName("timelineStatusPending")
        self.timeline_status.style().unpolish(self.timeline_status)
        self.timeline_status.style().polish(self.timeline_status)

        self.timeline_preview.set_project(self.project)
        self.timeline_preview.set_ready(self.timeline_ready)

        self.bottom_labels["footage"].setText(f"▣  Footage\n{fmt(p.total_video_duration)}")
        self.bottom_labels["album"].setText(f"♫  Album\n{fmt(album)}")
        self.bottom_labels["speed"].setText(f"◔  Planned Speed\n{speed:.2f}x")
        self.bottom_labels["loop"].setText(f"↻  Needs Loop\n{'Yes' if p.needs_loop() else 'No'}")
        self.bottom_labels["cut"].setText(f"✂  Auto Cut\n{fmt(cut)}")
        self.bottom_labels["output"].setText(
            f"⚙  Output\n{self.preset.currentText()}  •  {p.settings.width}×{p.settings.height}  •  {p.settings.fps} fps"
        )

        summary = self.pool.summary()
        self.key_status.setText(f"{summary['ready']}/{summary['total']} key")

    def render(self):
        report = self.project.validation()
        if report["errors"]:
            self._error("Proyek belum siap:\n\n" + "\n".join(f"• {x}" for x in report["errors"]))
            return

        default_path = str(output_dir() / "FULL_ALBUM_FINAL.mp4")
        path, _ = QFileDialog.getSaveFileName(self, "Simpan Full Album", default_path, "MP4 (*.mp4)")
        if not path:
            return

        self.render_btn.setEnabled(False)
        self.render_btn.setText("Rendering…")
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
            QMessageBox.information(self, "Render selesai", f"Video selesai:\n{path}")

    def _error(self, text):
        QMessageBox.critical(self, "Full Album Maker", text)


def run() -> int:
    app = QApplication([])
    app.setApplicationName("Full Album Maker")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    app.setWindowIcon(brand_icon())

    win = MainWindow()
    win.show()
    return app.exec()
