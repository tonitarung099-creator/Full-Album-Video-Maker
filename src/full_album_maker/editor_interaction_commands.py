from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from .editor_commands import CommandError, EditorCommand
from .editor_models import ProjectDocument, Transform


@dataclass
class SetLayerTransform(EditorCommand):
    layer_id: str
    transform: Transform

    def apply(self, document: ProjectDocument) -> EditorCommand:
        layer = document.layer_map().get(self.layer_id)
        if layer is None:
            raise CommandError("Layer tidak ditemukan.")
        if layer.locked:
            raise CommandError("Layer terkunci tidak dapat diubah.")
        replacement = deepcopy(self.transform)
        replacement.validate()
        old = deepcopy(layer.transform)
        layer.transform = replacement
        return SetLayerTransform(self.layer_id, old)


@dataclass
class SetLayerOpacity(EditorCommand):
    layer_id: str
    opacity: float

    def apply(self, document: ProjectDocument) -> EditorCommand:
        layer = document.layer_map().get(self.layer_id)
        if layer is None:
            raise CommandError("Layer tidak ditemukan.")
        if layer.locked:
            raise CommandError("Layer terkunci tidak dapat diubah.")
        try:
            value = float(self.opacity)
        except (TypeError, ValueError) as exc:
            raise CommandError("Opacity tidak valid.") from exc
        if not 0.0 <= value <= 1.0:
            raise CommandError("Opacity harus 0..1.")
        old = layer.opacity
        layer.opacity = value
        return SetLayerOpacity(self.layer_id, old)


@dataclass
class SetLayerEnabled(EditorCommand):
    layer_id: str
    enabled: bool

    def apply(self, document: ProjectDocument) -> EditorCommand:
        layer = document.layer_map().get(self.layer_id)
        if layer is None:
            raise CommandError("Layer tidak ditemukan.")
        if not isinstance(self.enabled, bool):
            raise CommandError("Status layer tidak valid.")
        old = layer.enabled
        layer.enabled = self.enabled
        return SetLayerEnabled(self.layer_id, old)


@dataclass
class SetLayerLocked(EditorCommand):
    layer_id: str
    locked: bool

    def apply(self, document: ProjectDocument) -> EditorCommand:
        layer = document.layer_map().get(self.layer_id)
        if layer is None:
            raise CommandError("Layer tidak ditemukan.")
        if not isinstance(self.locked, bool):
            raise CommandError("Status lock layer tidak valid.")
        old = layer.locked
        layer.locked = self.locked
        return SetLayerLocked(self.layer_id, old)


@dataclass
class SetLayerBindingPosition(EditorCommand):
    """Set the editable position field for the layer's current binding kind.

    absolute -> start_tick
    album -> start_offset_tick
    song/song_range -> offset_tick
    """

    layer_id: str
    position_tick: int

    def apply(self, document: ProjectDocument) -> EditorCommand:
        layer = document.layer_map().get(self.layer_id)
        if layer is None:
            raise CommandError("Layer tidak ditemukan.")
        if layer.locked:
            raise CommandError("Layer terkunci tidak dapat dipindahkan.")
        try:
            value = int(self.position_tick)
        except (TypeError, ValueError) as exc:
            raise CommandError("Posisi layer tidak valid.") from exc
        if value < 0:
            raise CommandError("Posisi layer tidak boleh negatif.")

        binding = layer.time_binding
        if binding.kind == "absolute":
            old = binding.start_tick
            binding.start_tick = value
        elif binding.kind == "album":
            old = binding.start_offset_tick
            binding.start_offset_tick = value
        elif binding.kind in {"song", "song_range"}:
            old = binding.offset_tick
            binding.offset_tick = value
        else:
            raise CommandError("Binding layer belum mendukung pemindahan timeline.")
        return SetLayerBindingPosition(self.layer_id, old)


@dataclass
class SetLayerDuration(EditorCommand):
    layer_id: str
    duration_tick: int | None

    def apply(self, document: ProjectDocument) -> EditorCommand:
        layer = document.layer_map().get(self.layer_id)
        if layer is None:
            raise CommandError("Layer tidak ditemukan.")
        if layer.locked:
            raise CommandError("Layer terkunci tidak dapat ditrim.")
        value = self.duration_tick
        if value is not None:
            try:
                value = int(value)
            except (TypeError, ValueError) as exc:
                raise CommandError("Durasi layer tidak valid.") from exc
            if value <= 0:
                raise CommandError("Durasi layer harus > 0.")
        old = layer.time_binding.duration_tick
        layer.time_binding.duration_tick = value
        return SetLayerDuration(self.layer_id, old)


@dataclass
class SetTrackEnabled(EditorCommand):
    track_id: str
    enabled: bool

    def apply(self, document: ProjectDocument) -> EditorCommand:
        track = next((item for item in document.tracks if item.track_id == self.track_id), None)
        if track is None:
            raise CommandError("Track tidak ditemukan.")
        if not isinstance(self.enabled, bool):
            raise CommandError("Status track tidak valid.")
        old = track.enabled
        track.enabled = self.enabled
        return SetTrackEnabled(self.track_id, old)


@dataclass
class SetTrackLocked(EditorCommand):
    track_id: str
    locked: bool

    def apply(self, document: ProjectDocument) -> EditorCommand:
        track = next((item for item in document.tracks if item.track_id == self.track_id), None)
        if track is None:
            raise CommandError("Track tidak ditemukan.")
        if not isinstance(self.locked, bool):
            raise CommandError("Status lock track tidak valid.")
        old = track.locked
        track.locked = self.locked
        return SetTrackLocked(self.track_id, old)
