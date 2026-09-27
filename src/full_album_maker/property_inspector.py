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

        form = QFormLayout()
        form.setContentsMargins(0, 4, 0, 0)
        form.setSpacing(5)
        root.addLayout(form)

        self.enabled = QCheckBox("Tampil")
        self.locked = QCheckBox("Kunci")
        form.addRow("Status", self.enabled)
        form.addRow("", self.locked)

        self.x = self._spin(-2.0, 2.0, 0.01, 3)
        self.y = self._spin(-2.0, 2.0, 0.01, 3)
        self.w = self._spin(0.02, 3.0, 0.01, 3)
        self.h = self._spin(0.02, 3.0, 0.01, 3)
        self.rotation = self._spin(-180.0, 180.0, 1.0, 1)
        self.opacity = self._spin(0.0, 1.0, 0.05, 2)
        form.addRow("X", self.x)
        form.addRow("Y", self.y)
        form.addRow("Lebar", self.w)
        form.addRow("Tinggi", self.h)
        form.addRow("Rotasi", self.rotation)
        form.addRow("Opacity", self.opacity)

        self.start = self._spin(0.0, 24 * 3600.0, 0.1, 3)
        self.duration = self._spin(0.001, 24 * 3600.0, 0.1, 3)
        form.addRow("Mulai (detik)", self.start)
        form.addRow("Durasi (detik)", self.duration)

        self.text_label = QLabel("Teks")
        self.text_value = QLineEdit()
        self.text_value.setPlaceholderText("Isi teks")
        self.color_value = QLineEdit()
        self.color_value.setPlaceholderText("#ffffff")
        form.addRow(self.text_label, self.text_value)
        form.addRow("Warna", self.color_value)

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
        form.addRow("Preset Spectrum", self.spectrum_preset)
        form.addRow("Style Spectrum", self.spectrum_style)
        form.addRow("Sensitivity", self.spectrum_gain)
        form.addRow("Skala Frekuensi", self.frequency_scale)
        form.addRow("Skala Amplitudo", self.amplitude_scale)
        form.addRow("Mirror", self.spectrum_mirror)
        self._spectrum_controls = (
            self.spectrum_preset,
            self.spectrum_style,
            self.spectrum_gain,
            self.frequency_scale,
            self.amplitude_scale,
            self.spectrum_mirror,
        )
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
        self.spectrum_preset.activated.connect(self._emit_spectrum_preset)
        self.spectrum_style.activated.connect(lambda: self._emit_property("style", self.spectrum_style.currentData()))
        self.spectrum_gain.editingFinished.connect(lambda: self._emit_property("gain", self.spectrum_gain.value()))
        self.frequency_scale.activated.connect(lambda: self._emit_property("frequency_scale", self.frequency_scale.currentData()))
        self.amplitude_scale.activated.connect(lambda: self._emit_property("amplitude_scale", self.amplitude_scale.currentData()))
        self.spectrum_mirror.toggled.connect(lambda value: self._emit_property("mirror", bool(value)))
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

    def set_layer(
        self,
        layer: Layer | None,
        *,
        global_start_tick: int = 0,
        resolved_duration_tick: int = TIMEBASE,
    ) -> None:
        self._updating = True
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
            *self._spectrum_controls,
        ]
        blockers = [QSignalBlocker(control) for control in controls]
        try:
            self._layer_id = layer.layer_id if layer else ""
            self._layer_type = layer.type if layer else ""
            self.layer_name.setText(layer.name if layer else "Tidak ada layer dipilih")
            for control in controls:
                control.setEnabled(layer is not None)
            if layer is None:
                for control in self._spectrum_controls:
                    control.setVisible(False)
                return

            is_background = layer.type == "background"
            is_text = layer.type == "text"
            is_title = layer.type == "song_title"
            is_spectrum = layer.type == "spectrum"
            has_box_transform = is_background or is_spectrum
            self.w.setEnabled(has_box_transform)
            self.h.setEnabled(has_box_transform)
            self.rotation.setEnabled(has_box_transform)
            self.text_value.setEnabled(is_text or is_title)
            self.text_label.setText("Template" if is_title else "Teks")
            self.color_value.setEnabled(layer.type in {"text", "song_title", "background", "spectrum"})
            for control in self._spectrum_controls:
                control.setVisible(is_spectrum)

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

            if is_spectrum:
                self._set_combo(self.spectrum_preset, str(layer.properties.get("preset", "")))
                self._set_combo(self.spectrum_style, str(layer.properties.get("style", "bars")))
                self.spectrum_gain.setValue(float(layer.properties.get("gain", 1.0)))
                self._set_combo(self.frequency_scale, str(layer.properties.get("frequency_scale", "log")))
                self._set_combo(self.amplitude_scale, str(layer.properties.get("amplitude_scale", "sqrt")))
                self.spectrum_mirror.setChecked(bool(layer.properties.get("mirror", False)))
                style = str(layer.properties.get("style", "bars"))
                capability = SPECTRUM_CAPABILITIES.get(style)
                self.frequency_scale.setVisible(bool(capability and capability.supports_frequency_scale))
                self.amplitude_scale.setVisible(bool(capability and capability.supports_amplitude_scale))
        finally:
            del blockers
            self._updating = False

    def _emit_transform(self) -> None:
        if self._updating or not self._layer_id:
            return
        supports_rotation = self._layer_type in {"background", "spectrum"}
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
