from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from .editor_commands import CommandError, EditorCommand
from .editor_models import Layer, ProjectDocument, TimeBinding, Transform, new_id
from .playlist_service_v2 import PlaylistServiceV2

AUTO_RECIPE_PROPERTY = "_auto_recipe"
AUTO_KEY_PROPERTY = "_auto_key"


@dataclass(frozen=True)
class AutoArrangeRecipe:
    recipe_id: str = "default-full-album"
    fallback_visual_asset_id: str | None = None
    background_fit: str = "fill"

    def validate(self, document: ProjectDocument) -> None:
        if not self.recipe_id.strip():
            raise CommandError("recipe_id Auto Susun tidak valid.")
        if self.background_fit not in {"fit", "fill", "fit_blur"}:
            raise CommandError("Mode fit Auto Susun tidak valid.")
        if self.fallback_visual_asset_id is not None:
            asset = document.asset_map().get(self.fallback_visual_asset_id)
            if asset is None or asset.kind not in {"image", "video"}:
                raise CommandError("Fallback visual Auto Susun harus image/video yang valid.")


def _owned_by(layer: Layer, recipe_id: str) -> bool:
    return layer.origin == "auto" and layer.properties.get(AUTO_RECIPE_PROPERTY) == recipe_id


def _auto_key(layer: Layer) -> str:
    value = layer.properties.get(AUTO_KEY_PROPERTY, "")
    return str(value) if isinstance(value, str) else ""


@dataclass
class ReplaceAutoRecipeLayers(EditorCommand):
    recipe_id: str
    layers: list[Layer]
    slots: list[int] | None = None

    def apply(self, document: ProjectDocument) -> EditorCommand:
        if not self.recipe_id.strip():
            raise CommandError("recipe_id Auto Susun tidak valid.")

        captured: list[Layer] = []
        captured_slots: list[int] = []
        for index, layer in enumerate(document.layers):
            if _owned_by(layer, self.recipe_id):
                if layer.locked:
                    raise CommandError(
                        f"Layer Auto Susun terkunci: {layer.name}. Buka lock sebelum susun ulang."
                    )
                captured.append(deepcopy(layer))
                captured_slots.append(index)

        replacement = [deepcopy(layer) for layer in self.layers]
        keys: set[str] = set()
        for layer in replacement:
            if layer.origin != "auto" or layer.properties.get(AUTO_RECIPE_PROPERTY) != self.recipe_id:
                raise CommandError("Layer pengganti Auto Susun memiliki ownership yang salah.")
            key = _auto_key(layer)
            if not key or key in keys:
                raise CommandError("auto_key Auto Susun kosong atau duplikat.")
            keys.add(key)
            layer.validate()

        non_owned = [layer for layer in document.layers if not _owned_by(layer, self.recipe_id)]
        desired_slots = list(self.slots) if self.slots is not None else list(range(len(replacement)))
        if len(desired_slots) != len(replacement):
            raise CommandError("Jumlah slot Auto Susun tidak cocok.")

        rebuilt = list(non_owned)
        for slot, layer in sorted(zip(desired_slots, replacement), key=lambda pair: pair[0]):
            index = max(0, min(int(slot), len(rebuilt)))
            rebuilt.insert(index, layer)
        document.layers = rebuilt
        return ReplaceAutoRecipeLayers(self.recipe_id, captured, captured_slots)


class AutoArrangePlanner:
    def plan(self, document: ProjectDocument, recipe: AutoArrangeRecipe) -> list[Layer]:
        document.validate()
        recipe.validate(document)

        visual_tracks = [track for track in document.tracks if track.kind == "visual"]
        if not visual_tracks:
            raise CommandError("Project tidak memiliki track visual untuk Auto Susun.")
        track = next((item for item in visual_tracks if item.enabled), visual_tracks[0])

        existing_by_key: dict[str, Layer] = {}
        for layer in document.layers:
            if not _owned_by(layer, recipe.recipe_id):
                continue
            key = _auto_key(layer)
            if not key or key in existing_by_key:
                raise CommandError("State Auto Susun lama memiliki auto_key rusak/duplikat.")
            existing_by_key[key] = layer

        assets = document.asset_map()
        rows = {row.song_id: row for row in PlaylistServiceV2.rows(document)}
        planned: list[Layer] = []
        for song in document.playlist.entries:
            if not song.enabled:
                continue
            visual_id = song.visual_asset_id or recipe.fallback_visual_asset_id
            if visual_id is None:
                continue
            asset = assets.get(visual_id)
            if asset is None or asset.kind not in {"image", "video"}:
                raise CommandError("Visual per lagu Auto Susun harus image/video yang valid.")

            key = f"song-visual:{song.song_id}"
            existing = existing_by_key.get(key)
            row = rows[song.song_id]
            planned.append(
                Layer(
                    layer_id=existing.layer_id if existing is not None else new_id(),
                    track_id=track.track_id,
                    type="background",
                    name=f"Visual — {row.title}",
                    enabled=True,
                    locked=False,
                    opacity=1.0,
                    order=0,
                    time_binding=TimeBinding(kind="song", song_id=song.song_id),
                    transform=Transform(),
                    properties={
                        "mode": "asset",
                        "fit": recipe.background_fit,
                        AUTO_RECIPE_PROPERTY: recipe.recipe_id,
                        AUTO_KEY_PROPERTY: key,
                    },
                    asset_refs=[visual_id],
                    origin="auto",
                )
            )
        return planned


@dataclass
class AutoArrange(EditorCommand):
    recipe: AutoArrangeRecipe = field(default_factory=AutoArrangeRecipe)

    def apply(self, document: ProjectDocument) -> EditorCommand:
        planned = AutoArrangePlanner().plan(document, self.recipe)
        return ReplaceAutoRecipeLayers(self.recipe.recipe_id, planned).apply(document)
