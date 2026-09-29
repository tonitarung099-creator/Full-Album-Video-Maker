from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .agent_actions import AgentAction
from .ai_editor import (
    AIEditorAmbiguity,
    AIEditorError,
    AIEditorExecutor,
    EDITOR_SYSTEM,
    EDITOR_TOOLS,
    EditorAIContextBuilder,
    _layer_candidate,
    _normalized,
    _resolve_layer,
    _resolve_song,
    _visual_track_and_order,
)
from .cover_manager import CoverAssignmentService, normalize_cover_key
from .editor_commands import AddLayer, EditorCommand, SetLayerProperty
from .editor_models import MediaAsset, ProjectDocument, TIMEBASE
from .free_timeline import SetPlaylistTimingMode, SetSongFreeTiming
from .playlist_commands import SetSongCover, SetSongVisual
from .song_visuals import (
    SongVisualAssignmentService,
    make_song_visual_layer,
    normalize_song_visual_properties,
)
from .spectrum_feature import make_spectrum_layer, normalize_spectrum_properties


def _obj(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        result["required"] = list(required)
    return result


_SONG_REF = {
    "song_id": {"type": "string", "description": "UUID song instance dari context"},
    "song_query": {"type": "string", "description": "Judul/artist lagu bila ID belum diketahui"},
}
_LAYER_REF = {
    "layer_id": {"type": "string", "description": "UUID layer dari context"},
    "layer_query": {"type": "string", "description": "Nama layer bila ID belum diketahui"},
}
_ASSET_REF = {
    "asset_id": {"type": "string", "description": "UUID media asset dari media_candidates"},
    "asset_query": {"type": "string", "description": "Nama file media tanpa path bila ID belum diketahui"},
}


V14_EDITOR_SYSTEM = EDITOR_SYSTEM + """

Tambahan aturan v1.4:
11. Cover/Visual Lagu harus memakai asset_id dari media_candidates bila tersedia. Jangan mengarang asset_id atau path.
12. asset_query hanya boleh dipakai untuk exact-normalized match lokal. Jika ambigu, jangan menebak.
13. Auto-match cover/Visual Lagu hanya dipakai bila pengguna memang meminta pencocokan otomatis.
14. Free Timeline hanya diubah bila pengguna meminta timing/gap/crossfade/mode timeline. Jangan mengarang timestamp.
15. Circular Spectrum memakai tool khusus v1.4; jangan menyamarkannya sebagai bars/waveform.
16. Satu perintah pengguna boleh menghasilkan beberapa function call; engine lokal tetap memvalidasinya sebagai satu transaksi Undo.
"""


V14_EDITOR_TOOLS: list[dict[str, Any]] = list(EDITOR_TOOLS) + [
    {
        "name": "add_circular_spectrum",
        "description": "Tambah Circular Spectrum nyata dengan preset Circular Neon.",
        "parameters": _obj(
            {
                "inner_ratio": {"type": "number", "description": "Radius dalam 0.15..0.85"},
                "color": {"type": "string", "description": "Warna #RRGGBB"},
                "gain": {"type": "number", "description": "Sensitivity 0.05..8.0"},
            }
        ),
    },
    {
        "name": "set_circular_spectrum",
        "description": "Ubah spectrum existing menjadi Circular Spectrum / atur radius dalamnya.",
        "parameters": _obj(
            {
                **_LAYER_REF,
                "inner_ratio": {"type": "number"},
                "color": {"type": "string"},
                "gain": {"type": "number"},
            }
        ),
    },
    {
        "name": "set_song_cover",
        "description": "Pasang satu image cover ke satu atau beberapa lagu.",
        "parameters": _obj(
            {
                **_SONG_REF,
                "song_ids": {"type": "array", "items": {"type": "string"}},
                **_ASSET_REF,
            }
        ),
    },
    {
        "name": "clear_song_cover",
        "description": "Hapus cover khusus dari satu atau beberapa lagu.",
        "parameters": _obj({**_SONG_REF, "song_ids": {"type": "array", "items": {"type": "string"}}}),
    },
    {
        "name": "auto_match_covers",
        "description": "Cocokkan cover image dengan lagu berdasarkan exact-normalized nama lokal.",
        "parameters": _obj({"only_empty": {"type": "boolean"}}),
    },
    {
        "name": "set_song_visual",
        "description": "Pasang foto/video Visual Lagu ke satu atau beberapa lagu.",
        "parameters": _obj(
            {
                **_SONG_REF,
                "song_ids": {"type": "array", "items": {"type": "string"}},
                **_ASSET_REF,
            }
        ),
    },
    {
        "name": "clear_song_visual",
        "description": "Hapus visual khusus dari satu atau beberapa lagu.",
        "parameters": _obj({**_SONG_REF, "song_ids": {"type": "array", "items": {"type": "string"}}}),
    },
    {
        "name": "auto_match_song_visuals",
        "description": "Cocokkan foto/video per lagu berdasarkan exact-normalized nama lokal.",
        "parameters": _obj({"only_empty": {"type": "boolean"}}),
    },
    {
        "name": "set_song_visual_style",
        "description": "Atur style global Visual Lagu: fit, motion foto, playback video dan transisi.",
        "parameters": _obj(
            {
                **_LAYER_REF,
                "fit": {"type": "string", "enum": ["fill", "fit"]},
                "image_motion": {"type": "string", "enum": ["static", "zoom_in", "zoom_out", "pan_left", "pan_right"]},
                "video_playback": {"type": "string", "enum": ["loop", "freeze"]},
                "transition": {"type": "string", "enum": ["cut", "fade", "slide_left", "slide_right"]},
                "transition_seconds": {"type": "number"},
            }
        ),
    },
    {
        "name": "set_timeline_mode",
        "description": "Ubah audio timeline menjadi Packed atau Free.",
        "parameters": _obj({"mode": {"type": "string", "enum": ["packed", "free"]}}, ("mode",)),
    },
    {
        "name": "set_song_timing",
        "description": "Atur posisi lagu dan crossfade pada Free Timeline. Engine otomatis mengaktifkan Free bila perlu.",
        "parameters": _obj(
            {
                **_SONG_REF,
                "start_seconds": {"type": "number"},
                "crossfade_seconds": {"type": "number"},
            },
            ("start_seconds",),
        ),
    },
]


def _asset_label(asset: MediaAsset) -> str:
    return str(asset.original_name or Path(asset.locator).name or asset.asset_id)


def _asset_candidate(asset: MediaAsset) -> dict[str, Any]:
    return {
        "asset_id": asset.asset_id,
        "kind": asset.kind,
        "name": _asset_label(asset)[:120],
    }


def _resolve_media_asset(
    document: ProjectDocument,
    args: dict[str, Any],
    *,
    kinds: set[str],
) -> MediaAsset:
    asset_id = str(args.get("asset_id", "") or "").strip()
    if asset_id:
        asset = document.asset_map().get(asset_id)
        if asset is None:
            raise AIEditorError("asset_id tidak ditemukan pada revision proyek ini.")
        if asset.kind not in kinds:
            raise AIEditorError("Tipe asset tidak valid untuk intent ini.")
        return asset

    query = normalize_cover_key(str(args.get("asset_query", "") or ""))
    if not query:
        raise AIEditorError("Intent membutuhkan asset_id atau asset_query.")
    candidates = [
        asset
        for asset in document.media
        if asset.kind in kinds and normalize_cover_key(_asset_label(asset)) == query
    ]
    if not candidates:
        raise AIEditorError("Media yang dimaksud tidak ditemukan.")
    if len(candidates) > 1:
        raise AIEditorAmbiguity(
            "Ada beberapa media dengan nama yang sama. Pilih asset_id.",
            [_asset_candidate(asset) for asset in candidates[:8]],
        )
    return candidates[0]


def _resolve_song_ids(document: ProjectDocument, args: dict[str, Any]) -> list[str]:
    supplied = args.get("song_ids")
    if isinstance(supplied, list) and supplied:
        result: list[str] = []
        seen: set[str] = set()
        for value in supplied:
            song_id = str(value)
            if song_id in seen:
                continue
            seen.add(song_id)
            if song_id not in document.song_map():
                raise AIEditorError("song_ids memuat ID yang tidak tersedia pada revision proyek ini.")
            result.append(song_id)
        return result
    return [_resolve_song(document, args).song_id]


def _resolve_song_visual_layer(document: ProjectDocument, args: dict[str, Any]):
    if args.get("layer_id") or args.get("layer_query"):
        return _resolve_layer(document, args, types={"song_visual"})
    candidates = [layer for layer in document.layers if layer.type == "song_visual"]
    if len(candidates) > 1:
        raise AIEditorAmbiguity(
            "Ada beberapa layer Visual Lagu. Pilih satu layer.",
            [_layer_candidate(layer) for layer in candidates[:8]],
        )
    return candidates[0] if candidates else None


class V14EditorAIContextBuilder(EditorAIContextBuilder):
    def __init__(self, *, max_songs: int = 24, max_layers: int = 24, max_media: int = 40) -> None:
        super().__init__(max_songs=max_songs, max_layers=max_layers)
        self.max_media = max(8, min(80, int(max_media)))

    def build(
        self,
        document: ProjectDocument,
        *,
        selected_layer_ids: Iterable[str] = (),
        user_text: str = "",
        template_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        context = super().build(
            document,
            selected_layer_ids=selected_layer_ids,
            user_text=user_text,
            template_ids=template_ids,
        )
        song_map = document.song_map()
        for item in context.get("songs", []):
            song = song_map.get(str(item.get("song_id", "")))
            if song is None:
                continue
            item["cover_asset_id"] = song.cover_asset_id or ""
            item["visual_asset_id"] = song.visual_asset_id or ""
            item["free_start_seconds"] = (
                None if song.free_start_tick is None else round(song.free_start_tick / TIMEBASE, 3)
            )
            item["crossfade_seconds"] = round(song.crossfade_in_tick / TIMEBASE, 3)

        media = [asset for asset in document.media if asset.kind in {"image", "video"}]
        query = _normalized(user_text)
        media.sort(
            key=lambda asset: (
                0 if query and query in _normalized(_asset_label(asset)) else 1,
                _asset_label(asset).casefold(),
                asset.asset_id,
            )
        )
        context["playlist_mode"] = document.playlist.mode
        context["media_candidates"] = [_asset_candidate(asset) for asset in media[: self.max_media]]
        context["truncated"]["media"] = len(media) > self.max_media
        context["spectrum_layers"] = [
            {
                "layer_id": layer.layer_id,
                "name": layer.name[:80],
                "style": str(layer.properties.get("style", "")),
                "inner_ratio": layer.properties.get("inner_ratio"),
            }
            for layer in document.layers
            if layer.type == "spectrum"
        ][:16]
        visual_layer = next((layer for layer in document.layers if layer.type == "song_visual"), None)
        if visual_layer is not None:
            context["song_visual_layer"] = {
                "layer_id": visual_layer.layer_id,
                "name": visual_layer.name[:80],
                "properties": normalize_song_visual_properties(visual_layer.properties),
            }
        return context


class V14AIEditorExecutor(AIEditorExecutor):
    def _commands_for_action(
        self,
        document: ProjectDocument,
        action: AgentAction,
        side_effects: list[tuple[str, dict[str, Any]]],
    ) -> list[EditorCommand]:
        name = action.name
        args = dict(action.args)

        if name == "add_circular_spectrum":
            track_id, order = _visual_track_and_order(document)
            layer = make_spectrum_layer(track_id, order, preset_id="circular_neon")
            merged = dict(layer.properties)
            for key in ("inner_ratio", "color", "gain"):
                if key in args:
                    merged[key] = args[key]
            layer.properties = normalize_spectrum_properties(merged)
            return [AddLayer(layer)]

        if name == "set_circular_spectrum":
            layer = _resolve_layer(document, args, types={"spectrum"})
            merged = {**layer.properties, "style": "circular_spectrum", "preset": ""}
            for key in ("inner_ratio", "color", "gain"):
                if key in args:
                    merged[key] = args[key]
            props = normalize_spectrum_properties(merged)
            return [SetLayerProperty(layer.layer_id, key, value) for key, value in props.items()]

        if name == "set_song_cover":
            song_ids = _resolve_song_ids(document, args)
            asset = _resolve_media_asset(document, args, kinds={"image"})
            return CoverAssignmentService.bulk_commands(document, song_ids, asset.asset_id)

        if name == "clear_song_cover":
            return CoverAssignmentService.bulk_commands(document, _resolve_song_ids(document, args), None)

        if name == "auto_match_covers":
            commands, _report = CoverAssignmentService.auto_match_commands(
                document, only_empty=bool(args.get("only_empty", True))
            )
            return list(commands)

        if name == "set_song_visual":
            song_ids = _resolve_song_ids(document, args)
            asset = _resolve_media_asset(document, args, kinds={"image", "video"})
            return SongVisualAssignmentService.bulk_commands(document, song_ids, asset.asset_id)

        if name == "clear_song_visual":
            return SongVisualAssignmentService.bulk_commands(document, _resolve_song_ids(document, args), None)

        if name == "auto_match_song_visuals":
            commands, _report = SongVisualAssignmentService.auto_match_commands(
                document, only_empty=bool(args.get("only_empty", True))
            )
            return list(commands)

        if name == "set_song_visual_style":
            allowed = {"fit", "image_motion", "video_playback", "transition", "transition_seconds"}
            updates = {key: value for key, value in args.items() if key in allowed}
            if not updates:
                raise AIEditorError("Intent style Visual Lagu tidak berisi perubahan.")
            layer = _resolve_song_visual_layer(document, args)
            if layer is None:
                track_id, order = _visual_track_and_order(document)
                layer = make_song_visual_layer(track_id, order=order)
                layer.properties = normalize_song_visual_properties({**layer.properties, **updates})
                return [AddLayer(layer)]
            props = normalize_song_visual_properties({**layer.properties, **updates})
            return [SetLayerProperty(layer.layer_id, key, value) for key, value in props.items()]

        if name == "set_timeline_mode":
            return [SetPlaylistTimingMode(str(args.get("mode", "")))]

        if name == "set_song_timing":
            song = _resolve_song(document, args)
            try:
                start = float(args["start_seconds"])
                fade = float(args.get("crossfade_seconds", 0.0))
            except (TypeError, ValueError, KeyError) as exc:
                raise AIEditorError("Timing lagu tidak valid.") from exc
            if not 0.0 <= start <= 86_400.0:
                raise AIEditorError("start_seconds harus 0..86400.")
            if not 0.0 <= fade <= 60.0:
                raise AIEditorError("crossfade_seconds harus 0..60.")
            commands: list[EditorCommand] = []
            if document.playlist.mode != "free":
                commands.append(SetPlaylistTimingMode("free"))
            commands.append(
                SetSongFreeTiming(
                    song.song_id,
                    int(round(start * TIMEBASE)),
                    int(round(fade * TIMEBASE)),
                )
            )
            return commands

        return super()._commands_for_action(document, action, side_effects)
