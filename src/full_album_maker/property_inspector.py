from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from .editor_models import Layer, TIMEBASE, Transform
from .spectrum_feature import SPECTRUM_CAPABILITIES, SPECTRUM_PRESETS


class PropertyInspector(QWidget):
    transformEdited = Signal(str, object)
    opacityEdited = Signal(str, float)
    enabledEdited = Signal(str, bool)
    lockedEdited = Signal(str, bool)
    startEdited = Signal(str, int)
    durationEdited = Signal(str, int)
    propertyEdited = Signal(str, str, object)
    spectrumPresetRequested = Signal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("propertyInspectorV2")
        self.setMinimumWidth(205)
        self._layer_id = ""
        self._layer_type = ""
        self._updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        title = QLabel("PROPERTI")
        title.setObjectName("panelTitle")
        root.addWidget(title)
        self.layer_name = QLabel("Tidak ada layer dipilih")
        self.layer_name.setWordWrap(True)
        root.addWidget(self.layer_name)

        self.form = QFormLayout()
        self.form.setContentsMargins(0, 4, 0, 0)
        self.form.setSpacing(5)
        root.addLayout(self.form)

        self.enabled = QCheckBox("Tampil")
        self.locked = QCheckBox("Kunci")
        self.form.addRow("Status", self.enabled)
        self.form.addRow("", self.locked)

        self.x = self._spin(-2.0, 2.0, 0.01, 3)
        self.y = self._spin(-2.0, 2.0, 0.01, 3)
        self.w = self._spin(0.02, 3.0, 0.01, 3)
        self.h = self._spin(0.02, 3.0, 0.01, 3)
        self.rotation = self._spin(-180.0, 180.0, 1.0, 1)
        self.opacity = self._spin(0.0, 1.0, 0.05, 2)
        self.form.addRow("X", self.x)
        self.form.addRow("Y", self.y)
        self.form.addRow("Lebar", self.w)
        self.form.addRow("Tinggi", self.h)
        self.form.addRow("Rotasi", self.rotation)
        self.form.addRow("Opacity", self.opacity)

        self.start = self._spin(0.0, 24 * 3600.0, 0.1, 3)
        self.duration = self._spin(0.001, 24 * 3600.0, 0.1, 3)
        self.form.addRow("Mulai (detik)", self.start)
        self.form.addRow("Durasi (detik)", self.duration)

        self.text_label = QLabel("Teks")
        self.text_value = QLineEdit()
        self.text_value.setPlaceholderText("Isi teks")
        self.color_value = QLineEdit()
        self.color_value.setPlaceholderText("#ffffff")
        self.form.addRow(self.text_label, self.text_value)
        self.form.addRow("Warna", self.color_value)

        self.background_playback = QComboBox()
        self.background_playback.addItem("Loop", "loop")
        self.background_playback.addItem("Freeze frame", "freeze")
        self.background_motion = QComboBox()
        for label, value in (
            ("Static", "static"),
            ("Zoom In", "zoom_in"),
            ("Zoom Out", "zoom_out"),
            ("Pan Left", "pan_left"),
            ("Pan Right", "pan_right"),
        ):
            self.background_motion.addItem(label, value)
        self.form.addRow("Playback", self.background_playback)
        self.form.addRow("Motion", self.background_motion)
        self._background_controls = (self.background_playback, self.background_motion)

        self.spectrum_preset = QComboBox()
        self.spectrum_preset.addItem("Custom", "")
        for preset_id, preset in SPECTRUM_PRESETS.items():
            self.spectrum_preset.addItem(str(preset["label"]), preset_id)
        self.spectrum_style = QComboBox()
        for style_id, capability in SPECTRUM_CAPABILITIES.items():
            self.spectrum_style.addItem(capability.label, style_id)
        self.spectrum_gain = self._spin(0.05, 8.0, 0.05, 2)
        self.frequency_scale = QComboBox()
        for label, value in (("Linear", "linear"), ("Log", "log"), ("Reverse Log", "rlog")):
            self.frequency_scale.addItem(label, value)
        self.amplitude_scale = QComboBox()
        for label, value in (("Linear", "linear"), ("Sqrt", "sqrt"), ("Cbrt", "cbrt"), ("Log", "log")):
            self.amplitude_scale.addItem(label, value)
        self.spectrum_mirror = QCheckBox("Aktif")
        self.spectrum_inner_ratio = self._spin(0.15, 0.85, 0.01, 2)
        self.form.addRow("Preset Spectrum", self.spectrum_preset)
        self.form.addRow("Style Spectrum", self.spectrum_style)
        self.form.addRow("Sensitivity", self.spectrum_gain)
        self.form.addRow("Skala Frekuensi", self.frequency_scale)
        self.form.addRow("Skala Amplitudo", self.amplitude_scale)
        self.form.addRow("Mirror", self.spectrum_mirror)
        self.form.addRow("Radius Dalam", self.spectrum_inner_ratio)
        self._spectrum_controls = (
            self.spectrum_preset,
            self.spectrum_style,
            self.spectrum_gain,
            self.frequency_scale,
            self.amplitude_scale,
            self.spectrum_mirror,
            self.spectrum_inner_ratio,
        )

        self.cover_fit = QComboBox()
        self.cover_fit.addItem("Fill", "fill")
        self.cover_fit.addItem("Fit", "fit")
        self.form.addRow("Fit Cover", self.cover_fit)
        self._cover_controls = (self.cover_fit,)

        self.vinyl_spin = self._spin(1.0, 60.0, 0.5, 1)
        self.vinyl_center_ratio = self._spin(0.05, 0.45, 0.01, 2)
        self.vinyl_groove_color = QLineEdit()
        self.vinyl_center_color = QLineEdit()
        self.form.addRow("Putaran (detik)", self.vinyl_spin)
        self.form.addRow("Label Tengah", self.vinyl_center_ratio)
        self.form.addRow("Warna Groove", self.vinyl_groove_color)
        self.form.addRow("Warna Label", self.vinyl_center_color)
        self._vinyl_controls = (
            self.vinyl_spin,
            self.vinyl_center_ratio,
            self.vinyl_groove_color,
            self.vinyl_center_color,
        )

        self.playlist_max_items = self._spin(1, 30, 1, 0)
        self.playlist_font_size = self._spin(8, 160, 1, 0)
        self.playlist_active_color = QLineEdit()
        self.playlist_numbered = QCheckBox("Tampilkan nomor")
        self.playlist_show_artist = QCheckBox("Tampilkan artist")
        self.playlist_bg_opacity = self._spin(0.0, 0.9, 0.05, 2)
        self.form.addRow("Jumlah Lagu", self.playlist_max_items)
        self.form.addRow("Font Playlist", self.playlist_font_size)
        self.form.addRow("Warna Aktif", self.playlist_active_color)
        self.form.addRow("Nomor", self.playlist_numbered)
        self.form.addRow("Artist", self.playlist_show_artist)
        self.form.addRow("Latar Playlist", self.playlist_bg_opacity)
        self._playlist_controls = (
            self.playlist_max_items,
            self.playlist_font_size,
            self.playlist_active_color,
            self.playlist_numbered,
            self.playlist_show_artist,
            self.playlist_bg_opacity,
        )

        self.progress_mode = QComboBox()
        self.progress_mode.addItem("Per Lagu", "song")
        self.progress_mode.addItem("Seluruh Album", "album")
        self.progress_fill_color = QLineEdit()
        self.progress_bg_color = QLineEdit()
        self.form.addRow("Mode Progress", self.progress_mode)
        self.form.addRow("Warna Isi", self.progress_fill_color)
        self.form.addRow("Warna Dasar", self.progress_bg_color)
        self._progress_controls = (self.progress_mode, self.progress_fill_color, self.progress_bg_color)

        root.addStretch(1)

        for spin in (self.x, self.y, self.w, self.h, self.rotation):
            spin.editingFinished.connect(self._emit_transform)
        self.opacity.editingFinished.connect(self._emit_opacity)
        self.start.editingFinished.connect(self._emit_start)
        self.duration.editingFinished.connect(self._emit_duration)
        self.enabled.toggled.connect(self._emit_enabled)
        self.locked.toggled.connect(self._emit_locked)
        self.text_value.editingFinished.connect(self._emit_text_property)
        self.color_value.editingFinished.connect(lambda: self._emit_property("color", self.color_value.text()))
        self.background_playback.activated.connect(lambda: self._emit_property("playback", self.background_playback.currentData()))
        self.background_motion.activated.connect(lambda: self._emit_property("motion", self.background_motion.currentData()))
        self.spectrum_preset.activated.connect(self._emit_spectrum_preset)
        self.spectrum_style.activated.connect(lambda: self._emit_property("style", self.spectrum_style.currentData()))
        self.spectrum_gain.editingFinished.connect(lambda: self._emit_property("gain", self.spectrum_gain.value()))
        self.frequency_scale.activated.connect(lambda: self._emit_property("frequency_scale", self.frequency_scale.currentData()))
        self.amplitude_scale.activated.connect(lambda: self._emit_property("amplitude_scale", self.amplitude_scale.currentData()))
        self.spectrum_mirror.toggled.connect(lambda value: self._emit_property("mirror", bool(value)))
        self.spectrum_inner_ratio.editingFinished.connect(lambda: self._emit_property("inner_ratio", self.spectrum_inner_ratio.value()))
        self.cover_fit.activated.connect(lambda: self._emit_property("fit", self.cover_fit.currentData()))
        self.vinyl_spin.editingFinished.connect(lambda: self._emit_property("spin_seconds", self.vinyl_spin.value()))
        self.vinyl_center_ratio.editingFinished.connect(lambda: self._emit_property("center_ratio", self.vinyl_center_ratio.value()))
        self.vinyl_groove_color.editingFinished.connect(lambda: self._emit_property("groove_color", self.vinyl_groove_color.text()))
        self.vinyl_center_color.editingFinished.connect(lambda: self._emit_property("center_color", self.vinyl_center_color.text()))
        self.playlist_max_items.editingFinished.connect(lambda: self._emit_property("max_items", int(self.playlist_max_items.value())))
        self.playlist_font_size.editingFinished.connect(lambda: self._emit_property("font_size", int(self.playlist_font_size.value())))
        self.playlist_active_color.editingFinished.connect(lambda: self._emit_property("active_color", self.playlist_active_color.text()))
        self.playlist_numbered.toggled.connect(lambda value: self._emit_property("numbered", bool(value)))
        self.playlist_show_artist.toggled.connect(lambda value: self._emit_property("show_artist", bool(value)))
        self.playlist_bg_opacity.editingFinished.connect(lambda: self._emit_property("background_opacity", self.playlist_bg_opacity.value()))
        self.progress_mode.activated.connect(lambda: self._emit_property("mode", self.progress_mode.currentData()))
        self.progress_fill_color.editingFinished.connect(lambda: self._emit_property("fill_color", self.progress_fill_color.text()))
        self.progress_bg_color.editingFinished.connect(lambda: self._emit_property("background_color", self.progress_bg_color.text()))
        self.set_layer(None)

    @staticmethod
    def _spin(minimum: float, maximum: float, step: float, decimals: int) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(minimum, maximum)
        box.setSingleStep(step)
        box.setDecimals(decimals)
        box.setKeyboardTracking(False)
        return box

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(max(0, index))

    def _set_field_visible(self, field: QWidget, visible: bool) -> None:
        field.setVisible(visible)
        label = self.form.labelForField(field)
        if label is not None:
            label.setVisible(visible)

    def set_layer(
        self,
        layer: Layer | None,
        *,
        global_start_tick: int = 0,
        resolved_duration_tick: int = TIMEBASE,
    ) -> None:
        self._updating = True
        special_controls = (
            *self._background_controls,
            *self._spectrum_controls,
            *self._cover_controls,
            *self._vinyl_controls,
            *self._playlist_controls,
            *self._progress_controls,
        )
        controls = [
            self.enabled,
            self.locked,
            self.x,
            self.y,
            self.w,
            self.h,
            self.rotation,
            self.opacity,
            self.start,
            self.duration,
            self.text_value,
            self.color_value,
            *special_controls,
        ]
        blockers = [QSignalBlocker(control) for control in controls]
        try:
            self._layer_id = layer.layer_id if layer else ""
            self._layer_type = layer.type if layer else ""
            self.layer_name.setText(layer.name if layer else "Tidak ada layer dipilih")
            for control in controls:
                control.setEnabled(layer is not None)
            for control in special_controls:
                self._set_field_visible(control, False)
            if layer is None:
                return

            is_background = layer.type == "background"
            is_text = layer.type == "text"
            is_title = layer.type == "song_title"
            is_spectrum = layer.type == "spectrum"
            is_cover = layer.type == "song_cover"
            is_vinyl = layer.type == "vinyl"
            is_playlist = layer.type == "playlist_visual"
            is_progress = layer.type == "progress"
            is_time = layer.type == "song_time"
            has_box_transform = layer.type in {
                "background",
                "spectrum",
                "song_cover",
                "vinyl",
                "playlist_visual",
                "progress",
                "song_time",
            }
            self.w.setEnabled(has_box_transform)
            self.h.setEnabled(has_box_transform)
            self.rotation.setEnabled(has_box_transform)
            self.text_value.setEnabled(is_text or is_title)
            self.text_label.setText("Template" if is_title else "Teks")
            self.color_value.setEnabled(layer.type in {"text", "song_title", "background", "spectrum", "vinyl", "playlist_visual", "song_time"})
            for control in self._background_controls:
                self._set_field_visible(control, is_background)
            for control in self._spectrum_controls:
                self._set_field_visible(control, is_spectrum)
            for control in self._cover_controls:
                self._set_field_visible(control, is_cover)
            for control in self._vinyl_controls:
                self._set_field_visible(control, is_vinyl)
            for control in self._playlist_controls:
                self._set_field_visible(control, is_playlist)
            for control in self._progress_controls:
                self._set_field_visible(control, is_progress or is_time)
            self._set_field_visible(self.progress_fill_color, is_progress)
            self._set_field_visible(self.progress_bg_color, is_progress)

            transform = layer.transform
            self.enabled.setChecked(layer.enabled)
            self.locked.setChecked(layer.locked)
            self.x.setValue(transform.x)
            self.y.setValue(transform.y)
            self.w.setValue(transform.width)
            self.h.setValue(transform.height)
            self.rotation.setValue(transform.rotation)
            self.opacity.setValue(layer.opacity)
            self.start.setValue(max(0, global_start_tick) / TIMEBASE)
            duration = layer.time_binding.duration_tick or max(1, resolved_duration_tick)
            self.duration.setValue(max(1, duration) / TIMEBASE)
            if is_title:
                self.text_value.setText(str(layer.properties.get("template", "{title}\n{artist}")))
            else:
                self.text_value.setText(str(layer.properties.get("text", "")))
            self.color_value.setText(str(layer.properties.get("color", "#ffffff")))

            if is_background:
                self._set_combo(self.background_playback, str(layer.properties.get("playback", "loop")))
                self._set_combo(self.background_motion, str(layer.properties.get("motion", "static")))

            if is_spectrum:
                self._set_combo(self.spectrum_preset, str(layer.properties.get("preset", "")))
                self._set_combo(self.spectrum_style, str(layer.properties.get("style", "bars")))
                self.spectrum_gain.setValue(float(layer.properties.get("gain", 1.0)))
                self._set_combo(self.frequency_scale, str(layer.properties.get("frequency_scale", "log")))
                self._set_combo(self.amplitude_scale, str(layer.properties.get("amplitude_scale", "sqrt")))
                self.spectrum_mirror.setChecked(bool(layer.properties.get("mirror", False)))
                self.spectrum_inner_ratio.setValue(float(layer.properties.get("inner_ratio", 0.58)))
                style = str(layer.properties.get("style", "bars"))
                capability = SPECTRUM_CAPABILITIES.get(style)
                self._set_field_visible(self.frequency_scale, bool(capability and capability.supports_frequency_scale))
                self._set_field_visible(self.amplitude_scale, bool(capability and capability.supports_amplitude_scale))
                self._set_field_visible(self.spectrum_inner_ratio, bool(capability and capability.supports_inner_ratio))

            if is_cover:
                self._set_combo(self.cover_fit, str(layer.properties.get("fit", "fill")))

            if is_vinyl:
                self.vinyl_spin.setValue(float(layer.properties.get("spin_seconds", 8.0)))
                self.vinyl_center_ratio.setValue(float(layer.properties.get("center_ratio", 0.18)))
                self.vinyl_groove_color.setText(str(layer.properties.get("groove_color", "#2d2d2d")))
                self.vinyl_center_color.setText(str(layer.properties.get("center_color", "#d9d9d9")))

            if is_playlist:
                self.playlist_max_items.setValue(int(layer.properties.get("max_items", 8)))
                self.playlist_font_size.setValue(int(layer.properties.get("font_size", 30)))
                self.playlist_active_color.setText(str(layer.properties.get("active_color", "#ffffff")))
                self.playlist_numbered.setChecked(bool(layer.properties.get("numbered", True)))
                self.playlist_show_artist.setChecked(bool(layer.properties.get("show_artist", False)))
                self.playlist_bg_opacity.setValue(float(layer.properties.get("background_opacity", 0.28)))

            if is_progress or is_time:
                self._set_combo(self.progress_mode, str(layer.properties.get("mode", "song")))
            if is_progress:
                self.progress_fill_color.setText(str(layer.properties.get("fill_color", "#ffffff")))
                self.progress_bg_color.setText(str(layer.properties.get("background_color", "#49515c")))
        finally:
            del blockers
            self._updating = False

    def _emit_transform(self) -> None:
        if self._updating or not self._layer_id:
            return
        supports_rotation = self._layer_type in {
            "background",
            "spectrum",
            "song_cover",
            "vinyl",
            "playlist_visual",
            "progress",
            "song_time",
        }
        current_rotation = self.rotation.value() if supports_rotation else 0.0
        self.transformEdited.emit(
            self._layer_id,
            Transform(
                x=self.x.value(),
                y=self.y.value(),
                width=self.w.value(),
                height=self.h.value(),
                rotation=current_rotation,
            ),
        )

    def _emit_opacity(self) -> None:
        if not self._updating and self._layer_id:
            self.opacityEdited.emit(self._layer_id, self.opacity.value())

    def _emit_start(self) -> None:
        if not self._updating and self._layer_id:
            self.startEdited.emit(self._layer_id, int(round(self.start.value() * TIMEBASE)))

    def _emit_duration(self) -> None:
        if not self._updating and self._layer_id:
            self.durationEdited.emit(self._layer_id, max(1, int(round(self.duration.value() * TIMEBASE))))

    def _emit_enabled(self, value: bool) -> None:
        if not self._updating and self._layer_id:
            self.enabledEdited.emit(self._layer_id, bool(value))

    def _emit_locked(self, value: bool) -> None:
        if not self._updating and self._layer_id:
            self.lockedEdited.emit(self._layer_id, bool(value))

    def _emit_text_property(self) -> None:
        key = "template" if self._layer_type == "song_title" else "text"
        self._emit_property(key, self.text_value.text())

    def _emit_spectrum_preset(self) -> None:
        if self._updating or not self._layer_id or self._layer_type != "spectrum":
            return
        preset_id = str(self.spectrum_preset.currentData() or "")
        if preset_id:
            self.spectrumPresetRequested.emit(self._layer_id, preset_id)

    def _emit_property(self, key: str, value) -> None:
        if not self._updating and self._layer_id:
            self.propertyEdited.emit(self._layer_id, key, value)
