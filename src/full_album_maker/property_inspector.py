from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from .editor_models import Layer, TIMEBASE, Transform


class PropertyInspector(QWidget):
    transformEdited = Signal(str, object)
    opacityEdited = Signal(str, float)
    enabledEdited = Signal(str, bool)
    lockedEdited = Signal(str, bool)
    startEdited = Signal(str, int)
    durationEdited = Signal(str, int)
    propertyEdited = Signal(str, str, object)

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

        self.text_value = QLineEdit()
        self.text_value.setPlaceholderText("Isi teks")
        self.color_value = QLineEdit()
        self.color_value.setPlaceholderText("#ffffff")
        form.addRow("Teks", self.text_value)
        form.addRow("Warna", self.color_value)
        root.addStretch(1)

        for spin in (self.x, self.y, self.w, self.h, self.rotation):
            spin.editingFinished.connect(self._emit_transform)
        self.opacity.editingFinished.connect(self._emit_opacity)
        self.start.editingFinished.connect(self._emit_start)
        self.duration.editingFinished.connect(self._emit_duration)
        self.enabled.toggled.connect(self._emit_enabled)
        self.locked.toggled.connect(self._emit_locked)
        self.text_value.editingFinished.connect(lambda: self._emit_property("text", self.text_value.text()))
        self.color_value.editingFinished.connect(lambda: self._emit_property("color", self.color_value.text()))
        self.set_layer(None)

    @staticmethod
    def _spin(minimum: float, maximum: float, step: float, decimals: int) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(minimum, maximum)
        box.setSingleStep(step)
        box.setDecimals(decimals)
        box.setKeyboardTracking(False)
        return box

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
        ]
        blockers = [QSignalBlocker(control) for control in controls]
        try:
            self._layer_id = layer.layer_id if layer else ""
            self._layer_type = layer.type if layer else ""
            self.layer_name.setText(layer.name if layer else "Tidak ada layer dipilih")
            for control in controls:
                control.setEnabled(layer is not None)
            if layer is None:
                return

            # S04 guarantees resize/rotation parity only for background visual.
            # Text can be positioned and styled, but the UI does not advertise
            # transforms the FFmpeg compiler would reject.
            is_background = layer.type == "background"
            is_text = layer.type == "text"
            self.w.setEnabled(is_background)
            self.h.setEnabled(is_background)
            self.rotation.setEnabled(is_background)
            self.text_value.setEnabled(is_text)
            self.color_value.setEnabled(layer.type in {"text", "background"})

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
            self.text_value.setText(str(layer.properties.get("text", "")))
            self.color_value.setText(str(layer.properties.get("color", "#ffffff")))
        finally:
            del blockers
            self._updating = False

    def _emit_transform(self) -> None:
        if self._updating or not self._layer_id:
            return
        current_rotation = self.rotation.value() if self._layer_type == "background" else 0.0
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

    def _emit_property(self, key: str, value) -> None:
        if not self._updating and self._layer_id:
            self.propertyEdited.emit(self._layer_id, key, value)
