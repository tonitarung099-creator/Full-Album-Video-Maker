from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .album_visuals import (
    make_playlist_visual_layer,
    make_progress_layer,
    make_song_cover_layer,
    make_song_time_layer,
    make_vinyl_layer,
)
from .editor_commands import (
    AddLayer,
    DeleteLayer,
    DuplicateLayer,
    SetLayerProperty,
)
from .editor_controller import EditorController
from .editor_interaction_commands import (
    SetLayerBindingPosition,
    SetLayerDuration,
    SetLayerEnabled,
    SetLayerLocked,
    SetLayerOpacity,
    SetLayerTransform,
    SetTrackEnabled,
    SetTrackLocked,
)
from .editor_models import Layer, ProjectDocument, TIMEBASE, TimeBinding, Transform
from .spectrum_feature import make_dynamic_title_layer, make_spectrum_layer
from .timeline_resolver import ResolvedTimeline, TimelineResolver


@dataclass(frozen=True)
class TimelineScale:
    pixels_per_second: float = 80.0
    timebase: int = TIMEBASE

    def __post_init__(self) -> None:
        if self.pixels_per_second <= 0:
            raise ValueError("pixels_per_second harus > 0.")
        if self.timebase <= 0:
            raise ValueError("timebase harus > 0.")

    def tick_to_px(self, tick: int) -> float:
        return (max(0, int(tick)) / self.timebase) * self.pixels_per_second

    def px_to_tick(self, px: float) -> int:
        return max(0, int(round((float(px) / self.pixels_per_second) * self.timebase)))

    def delta_px_to_tick(self, px: float) -> int:
        return int(round((float(px) / self.pixels_per_second) * self.timebase))


class EditorSession:
    """Editor-only state around the canonical ProjectDocument.

    Selection, playhead, zoom and snap are intentionally not serialized into the
    project. Every project mutation still goes through EditorController so one UI
    gesture becomes one undo transaction.
    """

    def __init__(self, document: ProjectDocument) -> None:
        self.controller = EditorController(document)
        self.selected_layer_ids: list[str] = []
        self.playhead_tick = 0
        self.pixels_per_second = 80.0
        self.snap_enabled = True
        self.snap_threshold_px = 8.0

    @property
    def revision(self) -> int:
        return self.controller.revision

    @property
    def is_dirty(self) -> bool:
        return self.controller.is_dirty

    @property
    def can_undo(self) -> bool:
        return self.controller.can_undo

    @property
    def can_redo(self) -> bool:
        return self.controller.can_redo

    def snapshot(self) -> ProjectDocument:
        return self.controller.snapshot()

    def set_document(self, document: ProjectDocument, *, mark_saved: bool = True) -> None:
        self.controller = EditorController(document, mark_saved=mark_saved)
        self.selected_layer_ids = []
        self.playhead_tick = 0

    def mark_saved(self) -> None:
        self.controller.mark_saved()

    def resolved(self) -> ResolvedTimeline:
        return TimelineResolver().resolve(self.snapshot())

    def album_end_tick(self) -> int:
        return self.resolved().duration_tick

    def set_playhead(self, tick: int) -> int:
        end = self.album_end_tick()
        self.playhead_tick = max(0, min(int(tick), max(0, end)))
        return self.playhead_tick

    def select(self, layer_ids: Iterable[str]) -> list[str]:
        available = self.snapshot().layer_map()
        result: list[str] = []
        for layer_id in layer_ids:
            if layer_id in available and layer_id not in result:
                result.append(layer_id)
        self.selected_layer_ids = result
        return list(result)

    def select_one(self, layer_id: str | None) -> list[str]:
        return self.select([] if not layer_id else [layer_id])

    def selected_layer(self) -> Layer | None:
        if len(self.selected_layer_ids) != 1:
            return None
        return self.snapshot().layer_map().get(self.selected_layer_ids[0])

    def _after_mutation(self) -> ProjectDocument:
        doc = self.snapshot()
        valid = doc.layer_map()
        self.selected_layer_ids = [x for x in self.selected_layer_ids if x in valid]
        self.set_playhead(self.playhead_tick)
        return doc

    def undo(self) -> ProjectDocument:
        self.controller.undo()
        return self._after_mutation()

    def redo(self) -> ProjectDocument:
        self.controller.redo()
        return self._after_mutation()

    def delete_selected(self) -> ProjectDocument:
        commands = [DeleteLayer(layer_id) for layer_id in self.selected_layer_ids]
        if commands:
            self.controller.dispatch(commands)
            self.selected_layer_ids = []
        return self._after_mutation()

    def duplicate_selected(self) -> ProjectDocument:
        commands = [DuplicateLayer(layer_id) for layer_id in self.selected_layer_ids]
        if not commands:
            return self.snapshot()
        self.controller.dispatch(commands)
        self.selected_layer_ids = [cmd.new_layer_id for cmd in commands if cmd.new_layer_id]
        return self._after_mutation()

    def _visual_track_and_order(self) -> tuple[str, int]:
        doc = self.snapshot()
        track = next((item for item in doc.tracks if item.kind == "visual" and item.enabled), None)
        if track is None:
            track = next((item for item in doc.tracks if item.kind == "visual"), None)
        if track is None:
            raise ValueError("Track visual tidak tersedia.")
        return track.track_id, max([item.order for item in doc.layers], default=-1) + 1

    def add_text_layer(self, text: str = "Teks Baru") -> ProjectDocument:
        track_id, order = self._visual_track_and_order()
        duration = max(TIMEBASE, self.album_end_tick())
        layer = Layer(
            track_id=track_id,
            type="text",
            name="Teks",
            order=order,
            time_binding=TimeBinding(kind="absolute", start_tick=self.playhead_tick, duration_tick=duration),
            transform=Transform(x=0.08, y=0.08, width=0.84, height=0.16),
            properties={"text": str(text), "font_size": 64, "color": "#ffffff"},
            origin="manual",
        )
        self.controller.dispatch(AddLayer(layer))
        self.selected_layer_ids = [layer.layer_id]
        return self._after_mutation()

    def add_spectrum_layer(self, preset_id: str = "neon_bars") -> ProjectDocument:
        track_id, order = self._visual_track_and_order()
        layer = make_spectrum_layer(track_id, order, preset_id=preset_id)
        self.controller.dispatch(AddLayer(layer))
        self.selected_layer_ids = [layer.layer_id]
        return self._after_mutation()

    def add_dynamic_title_layer(self) -> ProjectDocument:
        track_id, order = self._visual_track_and_order()
        layer = make_dynamic_title_layer(track_id, order)
        self.controller.dispatch(AddLayer(layer))
        self.selected_layer_ids = [layer.layer_id]
        return self._after_mutation()

    def add_song_cover_layer(self) -> ProjectDocument:
        track_id, order = self._visual_track_and_order()
        fallback = next((asset.asset_id for asset in self.snapshot().media if asset.kind == "image"), "")
        layer = make_song_cover_layer(track_id, order, fallback_asset_id=fallback)
        self.controller.dispatch(AddLayer(layer))
        self.selected_layer_ids = [layer.layer_id]
        return self._after_mutation()

    def add_vinyl_layer(self) -> ProjectDocument:
        track_id, order = self._visual_track_and_order()
        layer = make_vinyl_layer(track_id, order)
        self.controller.dispatch(AddLayer(layer))
        self.selected_layer_ids = [layer.layer_id]
        return self._after_mutation()

    def add_playlist_visual_layer(self) -> ProjectDocument:
        track_id, order = self._visual_track_and_order()
        layer = make_playlist_visual_layer(track_id, order)
        self.controller.dispatch(AddLayer(layer))
        self.selected_layer_ids = [layer.layer_id]
        return self._after_mutation()

    def add_progress_visuals(self) -> ProjectDocument:
        track_id, order = self._visual_track_and_order()
        progress = make_progress_layer(track_id, order)
        song_time = make_song_time_layer(track_id, order + 1)
        self.controller.dispatch([AddLayer(progress), AddLayer(song_time)])
        self.selected_layer_ids = [progress.layer_id]
        return self._after_mutation()

    def set_transform(self, layer_id: str, transform: Transform) -> ProjectDocument:
        self.controller.dispatch(SetLayerTransform(layer_id, transform))
        return self._after_mutation()

    def set_opacity(self, layer_id: str, opacity: float) -> ProjectDocument:
        self.controller.dispatch(SetLayerOpacity(layer_id, opacity))
        return self._after_mutation()

    def set_enabled(self, layer_id: str, enabled: bool) -> ProjectDocument:
        self.controller.dispatch(SetLayerEnabled(layer_id, enabled))
        return self._after_mutation()

    def set_locked(self, layer_id: str, locked: bool) -> ProjectDocument:
        self.controller.dispatch(SetLayerLocked(layer_id, locked))
        return self._after_mutation()

    def set_property(self, layer_id: str, key: str, value) -> ProjectDocument:
        self.controller.dispatch(SetLayerProperty(layer_id, key, value))
        return self._after_mutation()

    def set_track_enabled(self, track_id: str, enabled: bool) -> ProjectDocument:
        self.controller.dispatch(SetTrackEnabled(track_id, enabled))
        return self._after_mutation()

    def set_track_locked(self, track_id: str, locked: bool) -> ProjectDocument:
        self.controller.dispatch(SetTrackLocked(track_id, locked))
        return self._after_mutation()

    @staticmethod
    def _binding_position(layer: Layer) -> int:
        binding = layer.time_binding
        if binding.kind == "absolute":
            return binding.start_tick
        if binding.kind == "album":
            return binding.start_offset_tick
        if binding.kind in {"song", "song_range"}:
            return binding.offset_tick
        return 0

    def global_layer_start(self, layer_id: str) -> int:
        resolved = self.resolved()
        item = next((x for x in resolved.layers if x.layer_id == layer_id), None)
        if item is None or not item.intervals:
            return 0
        return min(interval.start_tick for interval in item.intervals)

    def move_layer_global_start(self, layer_id: str, target_tick: int) -> ProjectDocument:
        doc = self.snapshot()
        layer = doc.layer_map().get(layer_id)
        if layer is None:
            raise ValueError("Layer tidak ditemukan.")
        target = max(0, int(target_tick))
        resolved = TimelineResolver().resolve(doc)
        songs = {song.song_id: song for song in resolved.songs}
        binding = layer.time_binding
        if binding.kind == "absolute":
            position = target
        elif binding.kind == "album":
            position = target
        elif binding.kind == "song":
            anchor = songs.get(binding.song_id or "")
            if anchor is None:
                raise ValueError("Anchor lagu tidak ditemukan.")
            position = max(0, target - anchor.start_tick)
        elif binding.kind == "song_range":
            first_id = binding.ordered_song_ids[0] if binding.ordered_song_ids else ""
            anchor = songs.get(first_id)
            if anchor is None:
                raise ValueError("Anchor song_range tidak ditemukan.")
            position = max(0, target - anchor.start_tick)
        else:
            raise ValueError("Binding layer belum mendukung move.")
        self.controller.dispatch(SetLayerBindingPosition(layer_id, position))
        return self._after_mutation()

    def trim_layer_duration(self, layer_id: str, duration_tick: int) -> ProjectDocument:
        self.controller.dispatch(SetLayerDuration(layer_id, max(1, int(duration_tick))))
        return self._after_mutation()

    def snap_candidates(self, *, exclude_layer_id: str | None = None) -> list[int]:
        resolved = self.resolved()
        values = {0, resolved.duration_tick}
        for song in resolved.songs:
            values.add(song.start_tick)
            values.add(song.end_tick)
        for layer in resolved.layers:
            if layer.layer_id == exclude_layer_id:
                continue
            for interval in layer.intervals:
                values.add(interval.start_tick)
                values.add(interval.end_tick)
        return sorted(value for value in values if value >= 0)

    def snap_tick(
        self,
        tick: int,
        *,
        pixels_per_second: float | None = None,
        exclude_layer_id: str | None = None,
    ) -> int:
        value = max(0, int(tick))
        if not self.snap_enabled:
            return value
        scale = TimelineScale(pixels_per_second or self.pixels_per_second)
        threshold_tick = abs(scale.delta_px_to_tick(self.snap_threshold_px))
        candidates = self.snap_candidates(exclude_layer_id=exclude_layer_id)
        if not candidates:
            return value
        nearest = min(candidates, key=lambda candidate: abs(candidate - value))
        return nearest if abs(nearest - value) <= threshold_tick else value