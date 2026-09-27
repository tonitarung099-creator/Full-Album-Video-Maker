from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .editor_models import Layer, ProjectDocument, SongInstance, new_id


class CommandError(ValueError):
    pass


class EditorCommand(ABC):
    @abstractmethod
    def apply(self, document: ProjectDocument) -> "EditorCommand":
        """Mutate document and return an inverse command."""


@dataclass
class AddLayer(EditorCommand):
    layer: Layer

    def apply(self, document: ProjectDocument) -> EditorCommand:
        if self.layer.layer_id in document.layer_map():
            raise CommandError("layer_id sudah ada.")
        layer = deepcopy(self.layer)
        layer.validate()
        document.layers.append(layer)
        return DeleteLayer(layer.layer_id)


@dataclass
class DeleteLayer(EditorCommand):
    layer_id: str

    def apply(self, document: ProjectDocument) -> EditorCommand:
        for index, layer in enumerate(document.layers):
            if layer.layer_id == self.layer_id:
                if layer.locked:
                    raise CommandError("Layer terkunci tidak dapat dihapus.")
                removed = document.layers.pop(index)
                return RestoreLayer(deepcopy(removed), index)
        raise CommandError("Layer tidak ditemukan.")


@dataclass
class RestoreLayer(EditorCommand):
    layer: Layer
    index: int

    def apply(self, document: ProjectDocument) -> EditorCommand:
        if self.layer.layer_id in document.layer_map():
            raise CommandError("layer_id sudah ada.")
        index = max(0, min(self.index, len(document.layers)))
        document.layers.insert(index, deepcopy(self.layer))
        return DeleteLayer(self.layer.layer_id)


@dataclass
class DuplicateLayer(EditorCommand):
    layer_id: str
    new_layer_id: str | None = None

    def apply(self, document: ProjectDocument) -> EditorCommand:
        source = document.layer_map().get(self.layer_id)
        if source is None:
            raise CommandError("Layer sumber tidak ditemukan.")
        duplicate = deepcopy(source)
        duplicate.layer_id = self.new_layer_id or new_id()
        self.new_layer_id = duplicate.layer_id
        duplicate.name = f"{duplicate.name} Copy"
        duplicate.order = max([x.order for x in document.layers], default=-1) + 1
        document.layers.append(duplicate)
        return DeleteLayer(duplicate.layer_id)


@dataclass
class SetLayerProperty(EditorCommand):
    layer_id: str
    key: str
    value: Any
    _missing: bool = False

    def apply(self, document: ProjectDocument) -> EditorCommand:
        layer = document.layer_map().get(self.layer_id)
        if layer is None:
            raise CommandError("Layer tidak ditemukan.")
        if layer.locked:
            raise CommandError("Layer terkunci tidak dapat diubah.")
        missing = self.key not in layer.properties
        old = deepcopy(layer.properties.get(self.key))
        if self._missing:
            layer.properties.pop(self.key, None)
        else:
            layer.properties[self.key] = deepcopy(self.value)
        return SetLayerProperty(self.layer_id, self.key, old, _missing=missing)


@dataclass
class MoveAbsoluteLayer(EditorCommand):
    layer_id: str
    start_tick: int

    def apply(self, document: ProjectDocument) -> EditorCommand:
        layer = document.layer_map().get(self.layer_id)
        if layer is None:
            raise CommandError("Layer tidak ditemukan.")
        if layer.locked:
            raise CommandError("Layer terkunci tidak dapat dipindahkan.")
        if layer.time_binding.kind != "absolute":
            raise CommandError("MoveAbsoluteLayer hanya untuk binding absolute.")
        if self.start_tick < 0:
            raise CommandError("start_tick tidak boleh negatif.")
        old = layer.time_binding.start_tick
        layer.time_binding.start_tick = int(self.start_tick)
        return MoveAbsoluteLayer(self.layer_id, old)


@dataclass
class TrimAbsoluteLayer(EditorCommand):
    layer_id: str
    duration_tick: int

    def apply(self, document: ProjectDocument) -> EditorCommand:
        layer = document.layer_map().get(self.layer_id)
        if layer is None:
            raise CommandError("Layer tidak ditemukan.")
        if layer.locked:
            raise CommandError("Layer terkunci tidak dapat ditrim.")
        if layer.time_binding.kind != "absolute":
            raise CommandError("TrimAbsoluteLayer hanya untuk binding absolute.")
        if self.duration_tick <= 0:
            raise CommandError("duration_tick harus > 0.")
        old = layer.time_binding.duration_tick
        if old is None:
            raise CommandError("Layer absolute belum memiliki duration_tick.")
        layer.time_binding.duration_tick = int(self.duration_tick)
        return TrimAbsoluteLayer(self.layer_id, old)


@dataclass
class ReorderSongs(EditorCommand):
    ordered_song_ids: list[str]

    def apply(self, document: ProjectDocument) -> EditorCommand:
        current = [x.song_id for x in document.playlist.entries]
        requested = list(self.ordered_song_ids)
        if len(requested) != len(current) or set(requested) != set(current):
            raise CommandError("Urutan lagu harus memuat song_id yang sama persis.")
        by_id = document.song_map()
        document.playlist.entries = [by_id[song_id] for song_id in requested]
        return ReorderSongs(current)


@dataclass
class SetPlaylistEntries(EditorCommand):
    entries: list[SongInstance]

    def apply(self, document: ProjectDocument) -> EditorCommand:
        old = deepcopy(document.playlist.entries)
        document.playlist.entries = deepcopy(self.entries)
        return SetPlaylistEntries(old)


@dataclass
class SetCanvasBackground(EditorCommand):
    color: str

    def apply(self, document: ProjectDocument) -> EditorCommand:
        if not isinstance(self.color, str) or not self.color.strip():
            raise CommandError("Warna background tidak valid.")
        old = document.canvas.background_color
        document.canvas.background_color = self.color
        return SetCanvasBackground(old)


@dataclass
class RelinkAsset(EditorCommand):
    asset_id: str
    locator: str
    fingerprint: dict[str, Any] | None = None

    def apply(self, document: ProjectDocument) -> EditorCommand:
        asset = document.asset_map().get(self.asset_id)
        if asset is None:
            raise CommandError("Asset tidak ditemukan.")
        if not isinstance(self.locator, str) or not self.locator.strip():
            raise CommandError("Locator baru tidak valid.")
        inverse = RelinkAsset(asset.asset_id, asset.locator, deepcopy(asset.fingerprint))
        asset.locator = self.locator
        if self.fingerprint is not None:
            if not isinstance(self.fingerprint, dict):
                raise CommandError("Fingerprint tidak valid.")
            asset.fingerprint = deepcopy(self.fingerprint)
        return inverse


@dataclass
class ReplaceDocument(EditorCommand):
    replacement: ProjectDocument

    def apply(self, document: ProjectDocument) -> EditorCommand:
        old = document.clone()
        replacement = self.replacement.clone()
        replacement.project_id = document.project_id
        replacement.revision = document.revision
        replacement.validate()
        document.__dict__.clear()
        document.__dict__.update(replacement.__dict__)
        return ReplaceDocument(old)
