from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
from typing import Any

from .editor_models import (
    CanvasSettings,
    Layer,
    MediaAsset,
    Playlist,
    ProjectDocument,
    ProjectSchemaError,
    SongInstance,
    TimeBinding,
    Track,
    Transform,
    infer_asset_kind,
    seconds_to_tick,
)


class MigrationError(ProjectSchemaError):
    pass


def detect_project_payload(data: Any) -> str:
    if not isinstance(data, dict):
        return "invalid"
    if data.get("format") == "full-album-maker-project":
        try:
            version = int(data.get("schema_version", 0))
        except (TypeError, ValueError):
            return "invalid"
        return "project_v2" if version == 2 else "future_project" if version > 2 else "invalid"
    if data.get("version") == 1 and any(key in data for key in ("audio_clips", "video_clips")):
        return "timeline_v1"
    if data.get("version", 1) == 1 and any(key in data for key in ("videos", "audios", "images", "settings")):
        return "project_v1"
    return "unknown"


def _finite_duration(raw: Any, label: str) -> int:
    try:
        value = float(raw or 0.0)
    except (TypeError, ValueError) as exc:
        raise MigrationError(f"Durasi {label} legacy tidak valid.") from exc
    if not math.isfinite(value) or value < 0:
        raise MigrationError(f"Durasi {label} legacy tidak valid.")
    return seconds_to_tick(value)


def _path_key(path: str) -> str:
    return str(Path(path).expanduser()).replace("\\", "/").casefold()


def migrate_project_v1(data: dict[str, Any], *, name: str = "Proyek Migrasi") -> ProjectDocument:
    if detect_project_payload(data) != "project_v1":
        raise MigrationError("Payload bukan Project v1 yang dapat dimigrasikan.")

    settings = data.get("settings", {}) or {}
    if not isinstance(settings, dict):
        raise MigrationError("Setting proyek legacy tidak valid.")
    try:
        width = int(settings.get("width", 1920))
        height = int(settings.get("height", 1080))
        fps = int(settings.get("fps", 30))
    except (TypeError, ValueError) as exc:
        raise MigrationError("Resolusi/FPS legacy tidak valid.") from exc

    visual_track = Track(name="Elemen Visual", kind="visual", order=0)
    audio_track = Track(name="Audio Master", kind="audio", order=1)
    doc = ProjectDocument(
        name=name,
        canvas=CanvasSettings(width=width, height=height, fps_num=fps, fps_den=1),
        playlist=Playlist(mode="packed", entries=[]),
        tracks=[visual_track, audio_track],
        render_settings={
            "auto_speed": settings.get("auto_speed", True),
            "manual_speed": settings.get("manual_speed", 1.0),
            "min_speed": settings.get("min_speed", 0.50),
            "loop_mode": settings.get("loop_mode", "auto"),
            "codec": settings.get("codec", "h264"),
            "video_bitrate": settings.get("video_bitrate", "12M"),
            "audio_bitrate": settings.get("audio_bitrate", "320k"),
        },
        extensions={"legacy_v1": deepcopy(data)},
    )

    asset_by_kind_path: dict[tuple[str, str], str] = {}
    audio_raw_by_asset: dict[str, dict[str, Any]] = {}

    def add_asset(raw: Any, kind: str, index: int) -> str:
        if not isinstance(raw, dict):
            raise MigrationError(f"{kind} legacy #{index} tidak valid.")
        path = raw.get("path")
        if not isinstance(path, str) or not path.strip():
            raise MigrationError(f"Path {kind} legacy #{index} tidak valid.")
        key = (kind, _path_key(path))
        if key in asset_by_kind_path:
            return asset_by_kind_path[key]
        metadata = {k: deepcopy(v) for k, v in raw.items() if k not in {"path", "duration"}}
        asset = MediaAsset(
            kind=kind,
            locator=path,
            source_duration_tick=_finite_duration(raw.get("duration", 0.0), f"{kind} #{index}"),
            original_name=Path(path).name,
            metadata=metadata,
        )
        doc.media.append(asset)
        asset_by_kind_path[key] = asset.asset_id
        if kind == "audio":
            audio_raw_by_asset[asset.asset_id] = raw
        return asset.asset_id

    raw_videos = data.get("videos", []) or []
    raw_audios = data.get("audios", []) or []
    raw_images = data.get("images", []) or []
    for label, value in (("videos", raw_videos), ("audios", raw_audios), ("images", raw_images)):
        if not isinstance(value, list):
            raise MigrationError(f"Daftar {label} legacy tidak valid.")

    for i, raw in enumerate(raw_videos, 1):
        add_asset(raw, "video", i)
    audio_asset_ids = [add_asset(raw, "audio", i) for i, raw in enumerate(raw_audios, 1)]
    for i, raw in enumerate(raw_images, 1):
        add_asset(raw, "image", i)

    def add_linked_asset(path: Any) -> str | None:
        if not isinstance(path, str) or not path.strip():
            return None
        kind = infer_asset_kind(path, "image")
        key = (kind, _path_key(path))
        existing = asset_by_kind_path.get(key)
        if existing:
            return existing
        asset = MediaAsset(kind=kind, locator=path, original_name=Path(path).name)
        doc.media.append(asset)
        asset_by_kind_path[key] = asset.asset_id
        return asset.asset_id

    # Legacy semantics: active_audio_paths absent/empty means use every audio.
    active = data.get("active_audio_paths", [])
    if active is None:
        active = []
    if not isinstance(active, list) or not all(isinstance(x, str) for x in active):
        raise MigrationError("active_audio_paths legacy tidak valid.")

    audio_by_path = {_path_key(raw.get("path", "")): asset_id for raw, asset_id in zip(raw_audios, audio_asset_ids)}
    selected_asset_ids: list[str] = []
    if active:
        for path in active:
            asset_id = audio_by_path.get(_path_key(path))
            if asset_id is None:
                raise MigrationError(f"Playlist legacy merujuk lagu yang tidak ada di Media: {Path(path).name}")
            selected_asset_ids.append(asset_id)
    else:
        selected_asset_ids = list(audio_asset_ids)

    for asset_id in selected_asset_ids:
        raw = audio_raw_by_asset.get(asset_id, {})
        asset = next(item for item in doc.media if item.asset_id == asset_id)
        source_out = asset.source_duration_tick or None
        doc.playlist.entries.append(
            SongInstance(
                asset_id=asset_id,
                display_title=str(raw.get("display_title", "") or ""),
                display_artist=str(raw.get("display_artist", "") or ""),
                cover_asset_id=add_linked_asset(raw.get("cover_path")),
                visual_asset_id=add_linked_asset(raw.get("visual_path")),
                source_in_tick=0,
                source_out_tick=source_out,
            )
        )

    visual_settings = data.get("visual_settings", {}) or {}
    if not isinstance(visual_settings, dict):
        raise MigrationError("visual_settings legacy tidak valid.")
    visual_order = data.get("visual_order", []) or []
    if not isinstance(visual_order, list) or not all(isinstance(x, str) for x in visual_order):
        raise MigrationError("visual_order legacy tidak valid.")

    visual_asset_refs: list[str] = []
    for path in visual_order:
        key_candidates = [("video", _path_key(path)), ("image", _path_key(path))]
        asset_id = next((asset_by_kind_path.get(k) for k in key_candidates if asset_by_kind_path.get(k)), None)
        if asset_id is None:
            asset_id = add_linked_asset(path)
        if asset_id:
            visual_asset_refs.append(asset_id)

    if not visual_asset_refs:
        visual_asset_refs = [a.asset_id for a in doc.media if a.kind in {"video", "image"}]

    if visual_asset_refs:
        doc.layers.append(
            Layer(
                track_id=visual_track.track_id,
                type="background",
                name="Visual Legacy",
                order=0,
                time_binding=TimeBinding(kind="album"),
                transform=Transform(),
                asset_refs=visual_asset_refs,
                origin="migration",
                properties={
                    "legacy_visual_mode": visual_settings.get("visual_mode", "sequential"),
                    "photo_duration": visual_settings.get("photo_duration", 10.0),
                    "photo_fit": visual_settings.get("photo_fit", "fit_blur"),
                    "photo_motion": visual_settings.get("photo_motion", "zoom"),
                    "photo_zoom_end": visual_settings.get("photo_zoom_end", 1.08),
                    "visual_transition": visual_settings.get("visual_transition", "none"),
                },
            )
        )

    title_mode = str(visual_settings.get("title_mode", "full"))
    if title_mode != "off":
        doc.layers.append(
            Layer(
                track_id=visual_track.track_id,
                type="song_title",
                name="Judul Lagu Legacy",
                order=max([x.order for x in doc.layers], default=-1) + 1,
                time_binding=TimeBinding(kind="album"),
                origin="migration",
                properties={
                    "binding": "active_song",
                    "legacy_title_mode": title_mode,
                    "intro_duration_tick": seconds_to_tick(6.0) if title_mode == "intro6" else None,
                    "animation": visual_settings.get("title_animation", "fade"),
                },
            )
        )

    doc.validate()
    return doc
