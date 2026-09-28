from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

PROJECT_FORMAT = "full-album-maker-project"
SCHEMA_VERSION = 2
TIMEBASE = 240_000
SUPPORTED_FPS = {(24, 1), (25, 1), (30, 1), (50, 1), (60, 1)}


class ProjectSchemaError(ValueError):
    pass


def new_id() -> str:
    return str(uuid4())


def _uuid(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectSchemaError(f"{label} tidak valid.")
    try:
        UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ProjectSchemaError(f"{label} bukan UUID valid.") from exc
    return value


def _int(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise ProjectSchemaError(f"{label} tidak valid.")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ProjectSchemaError(f"{label} tidak valid.") from exc
    if result < minimum:
        raise ProjectSchemaError(f"{label} tidak valid.")
    return result


def _float(value: Any, label: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool):
        raise ProjectSchemaError(f"{label} tidak valid.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ProjectSchemaError(f"{label} tidak valid.") from exc
    if not math.isfinite(result) or result < minimum:
        raise ProjectSchemaError(f"{label} tidak valid.")
    return result


def seconds_to_tick(seconds: float) -> int:
    return int(round(_float(seconds, "Durasi") * TIMEBASE))


@dataclass
class CanvasSettings:
    width: int = 1920
    height: int = 1080
    fps_num: int = 30
    fps_den: int = 1
    background_color: str = "#101114"

    def validate(self) -> None:
        if not 320 <= self.width <= 7680 or not 240 <= self.height <= 4320:
            raise ProjectSchemaError("Resolusi kanvas tidak valid.")
        if self.width % 2 or self.height % 2:
            raise ProjectSchemaError("Resolusi kanvas harus genap.")
        if (self.fps_num, self.fps_den) not in SUPPORTED_FPS:
            raise ProjectSchemaError("FPS kanvas belum didukung.")
        if not isinstance(self.background_color, str) or not self.background_color.strip():
            raise ProjectSchemaError("Warna latar kanvas tidak valid.")

    @classmethod
    def from_dict(cls, data: Any) -> "CanvasSettings":
        if not isinstance(data, dict):
            raise ProjectSchemaError("Canvas proyek tidak valid.")
        item = cls(
            width=_int(data.get("width", 1920), "canvas.width", 1),
            height=_int(data.get("height", 1080), "canvas.height", 1),
            fps_num=_int(data.get("fps_num", 30), "canvas.fps_num", 1),
            fps_den=_int(data.get("fps_den", 1), "canvas.fps_den", 1),
            background_color=str(data.get("background_color", "#101114")),
        )
        item.validate()
        return item


@dataclass
class MediaAsset:
    asset_id: str = field(default_factory=new_id)
    kind: str = "audio"
    locator: str = ""
    relative_path: str = ""
    fingerprint: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_duration_tick: int = 0
    original_name: str = ""

    def validate(self) -> None:
        _uuid(self.asset_id, "asset_id")
        if self.kind not in {"audio", "video", "image", "font", "overlay", "other"}:
            raise ProjectSchemaError(f"Jenis media tidak didukung: {self.kind}")
        if not isinstance(self.locator, str) or not self.locator.strip():
            raise ProjectSchemaError("Locator media tidak valid.")
        self.source_duration_tick = _int(self.source_duration_tick, "source_duration_tick")
        if not isinstance(self.fingerprint, dict) or not isinstance(self.metadata, dict):
            raise ProjectSchemaError("Metadata media tidak valid.")

    @classmethod
    def from_dict(cls, data: Any) -> "MediaAsset":
        if not isinstance(data, dict):
            raise ProjectSchemaError("MediaAsset tidak valid.")
        item = cls(
            asset_id=_uuid(data.get("asset_id"), "asset_id"),
            kind=str(data.get("kind", "other")),
            locator=str(data.get("locator", "")),
            relative_path=str(data.get("relative_path", "") or ""),
            fingerprint=deepcopy(data.get("fingerprint", {})),
            metadata=deepcopy(data.get("metadata", {})),
            source_duration_tick=_int(data.get("source_duration_tick", 0), "source_duration_tick"),
            original_name=str(data.get("original_name", "") or ""),
        )
        item.validate()
        return item


@dataclass
class SongInstance:
    song_id: str = field(default_factory=new_id)
    asset_id: str = ""
    display_title: str = ""
    display_artist: str = ""
    cover_asset_id: str | None = None
    visual_asset_id: str | None = None
    source_in_tick: int = 0
    source_out_tick: int | None = None
    gain: float = 1.0
    enabled: bool = True
    free_start_tick: int | None = None
    crossfade_in_tick: int = 0

    def validate(self) -> None:
        _uuid(self.song_id, "song_id")
        _uuid(self.asset_id, "song.asset_id")
        self.source_in_tick = _int(self.source_in_tick, "source_in_tick")
        if self.source_out_tick is not None:
            self.source_out_tick = _int(self.source_out_tick, "source_out_tick")
            if self.source_out_tick <= self.source_in_tick:
                raise ProjectSchemaError("source_out_tick harus lebih besar dari source_in_tick.")
        self.gain = _float(self.gain, "gain")
        if not isinstance(self.enabled, bool):
            raise ProjectSchemaError("enabled lagu tidak valid.")
        if self.free_start_tick is not None:
            self.free_start_tick = _int(self.free_start_tick, "free_start_tick")
        self.crossfade_in_tick = _int(self.crossfade_in_tick, "crossfade_in_tick")
        if self.cover_asset_id is not None:
            _uuid(self.cover_asset_id, "cover_asset_id")
        if self.visual_asset_id is not None:
            _uuid(self.visual_asset_id, "visual_asset_id")

    @classmethod
    def from_dict(cls, data: Any) -> "SongInstance":
        if not isinstance(data, dict):
            raise ProjectSchemaError("SongInstance tidak valid.")
        item = cls(
            song_id=_uuid(data.get("song_id"), "song_id"),
            asset_id=_uuid(data.get("asset_id"), "song.asset_id"),
            display_title=str(data.get("display_title", "") or ""),
            display_artist=str(data.get("display_artist", "") or ""),
            cover_asset_id=data.get("cover_asset_id"),
            visual_asset_id=data.get("visual_asset_id"),
            source_in_tick=_int(data.get("source_in_tick", 0), "source_in_tick"),
            source_out_tick=None if data.get("source_out_tick") is None else _int(data.get("source_out_tick"), "source_out_tick"),
            gain=_float(data.get("gain", 1.0), "gain"),
            enabled=data.get("enabled", True),
            free_start_tick=None if data.get("free_start_tick") is None else _int(data.get("free_start_tick"), "free_start_tick"),
            crossfade_in_tick=_int(data.get("crossfade_in_tick", 0), "crossfade_in_tick"),
        )
        item.validate()
        return item


@dataclass
class Playlist:
    mode: str = "packed"
    entries: list[SongInstance] = field(default_factory=list)

    def validate(self) -> None:
        if self.mode not in {"packed", "free"}:
            raise ProjectSchemaError("Mode playlist tidak valid.")
        ids: set[str] = set()
        for song in self.entries:
            song.validate()
            if song.song_id in ids:
                raise ProjectSchemaError("song_id duplikat dalam playlist.")
            ids.add(song.song_id)
        if self.mode == "packed":
            for song in self.entries:
                if song.crossfade_in_tick:
                    raise ProjectSchemaError(
                        "crossfade_in_tick hanya boleh aktif pada playlist mode free."
                    )

    @classmethod
    def from_dict(cls, data: Any) -> "Playlist":
        if not isinstance(data, dict) or not isinstance(data.get("entries", []), list):
            raise ProjectSchemaError("Playlist proyek tidak valid.")
        item = cls(str(data.get("mode", "packed")), [SongInstance.from_dict(x) for x in data.get("entries", [])])
        item.validate()
        return item


@dataclass
class Track:
    track_id: str = field(default_factory=new_id)
    name: str = "Track"
    kind: str = "visual"
    enabled: bool = True
    locked: bool = False
    order: int = 0

    def validate(self) -> None:
        _uuid(self.track_id, "track_id")
        if self.kind not in {"audio", "visual"}:
            raise ProjectSchemaError("Jenis track tidak valid.")
        if not isinstance(self.enabled, bool) or not isinstance(self.locked, bool):
            raise ProjectSchemaError("Status track tidak valid.")
        self.order = _int(self.order, "track.order")

    @classmethod
    def from_dict(cls, data: Any) -> "Track":
        if not isinstance(data, dict):
            raise ProjectSchemaError("Track tidak valid.")
        item = cls(
            track_id=_uuid(data.get("track_id"), "track_id"),
            name=str(data.get("name", "Track")),
            kind=str(data.get("kind", "visual")),
            enabled=data.get("enabled", True),
            locked=data.get("locked", False),
            order=_int(data.get("order", 0), "track.order"),
        )
        item.validate()
        return item


@dataclass
class TimeBinding:
    kind: str = "album"
    start_tick: int = 0
    duration_tick: int | None = None
    start_offset_tick: int = 0
    end_offset_tick: int = 0
    song_id: str | None = None
    offset_tick: int = 0
    ordered_song_ids: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.kind not in {"absolute", "album", "song", "song_range"}:
            raise ProjectSchemaError("time_binding.kind tidak valid.")
        self.start_tick = _int(self.start_tick, "start_tick")
        self.start_offset_tick = _int(self.start_offset_tick, "start_offset_tick")
        self.end_offset_tick = _int(self.end_offset_tick, "end_offset_tick")
        self.offset_tick = _int(self.offset_tick, "offset_tick")
        if self.duration_tick is not None:
            self.duration_tick = _int(self.duration_tick, "duration_tick")
        if self.kind == "song":
            _uuid(self.song_id, "time_binding.song_id")
        if self.kind == "song_range":
            if not self.ordered_song_ids:
                raise ProjectSchemaError("Binding song_range membutuhkan ordered_song_ids.")
            for song_id in self.ordered_song_ids:
                _uuid(song_id, "ordered_song_ids")

    @classmethod
    def from_dict(cls, data: Any) -> "TimeBinding":
        if not isinstance(data, dict):
            raise ProjectSchemaError("time_binding tidak valid.")
        item = cls(
            kind=str(data.get("kind", "album")),
            start_tick=_int(data.get("start_tick", 0), "start_tick"),
            duration_tick=None if data.get("duration_tick") is None else _int(data.get("duration_tick"), "duration_tick"),
            start_offset_tick=_int(data.get("start_offset_tick", 0), "start_offset_tick"),
            end_offset_tick=_int(data.get("end_offset_tick", 0), "end_offset_tick"),
            song_id=data.get("song_id"),
            offset_tick=_int(data.get("offset_tick", 0), "offset_tick"),
            ordered_song_ids=list(data.get("ordered_song_ids", []) or []),
        )
        item.validate()
        return item


@dataclass
class Transform:
    x: float = 0.0
    y: float = 0.0
    width: float = 1.0
    height: float = 1.0
    rotation: float = 0.0
    pivot_x: float = 0.5
    pivot_y: float = 0.5

    def validate(self) -> None:
        for name in ("x", "y", "width", "height", "rotation", "pivot_x", "pivot_y"):
            value = getattr(self, name)
            if isinstance(value, bool):
                raise ProjectSchemaError(f"transform.{name} tidak valid.")
            try:
                value = float(value)
            except (TypeError, ValueError) as exc:
                raise ProjectSchemaError(f"transform.{name} tidak valid.") from exc
            if not math.isfinite(value):
                raise ProjectSchemaError(f"transform.{name} tidak valid.")
            setattr(self, name, value)
        if self.width <= 0 or self.height <= 0:
            raise ProjectSchemaError("Ukuran layer harus > 0.")

    @classmethod
    def from_dict(cls, data: Any) -> "Transform":
        if not isinstance(data, dict):
            raise ProjectSchemaError("Transform layer tidak valid.")
        item = cls(**{name: data.get(name, getattr(cls(), name)) for name in ("x", "y", "width", "height", "rotation", "pivot_x", "pivot_y")})
        item.validate()
        return item


@dataclass
class Layer:
    layer_id: str = field(default_factory=new_id)
    track_id: str = ""
    type: str = "shape"
    name: str = "Layer"
    enabled: bool = True
    locked: bool = False
    opacity: float = 1.0
    order: int = 0
    time_binding: TimeBinding = field(default_factory=TimeBinding)
    transform: Transform = field(default_factory=Transform)
    properties: dict[str, Any] = field(default_factory=dict)
    animation: dict[str, Any] = field(default_factory=dict)
    asset_refs: list[str] = field(default_factory=list)
    origin: str = "manual"

    def validate(self) -> None:
        _uuid(self.layer_id, "layer_id")
        _uuid(self.track_id, "layer.track_id")
        if not isinstance(self.type, str) or not self.type.strip():
            raise ProjectSchemaError("Tipe layer tidak valid.")
        if not isinstance(self.enabled, bool) or not isinstance(self.locked, bool):
            raise ProjectSchemaError("Status layer tidak valid.")
        self.opacity = _float(self.opacity, "opacity")
        if self.opacity > 1.0:
            raise ProjectSchemaError("Opacity harus 0..1.")
        self.order = _int(self.order, "layer.order")
        self.time_binding.validate()
        self.transform.validate()
        if not isinstance(self.properties, dict) or not isinstance(self.animation, dict):
            raise ProjectSchemaError("Properties/animation layer tidak valid.")
        for ref in self.asset_refs:
            _uuid(ref, "layer.asset_refs")
        if self.origin not in {"manual", "template", "migration", "auto"}:
            raise ProjectSchemaError("Origin layer tidak valid.")

    @classmethod
    def from_dict(cls, data: Any) -> "Layer":
        if not isinstance(data, dict):
            raise ProjectSchemaError("Layer tidak valid.")
        item = cls(
            layer_id=_uuid(data.get("layer_id"), "layer_id"),
            track_id=_uuid(data.get("track_id"), "layer.track_id"),
            type=str(data.get("type", "shape")),
            name=str(data.get("name", "Layer")),
            enabled=data.get("enabled", True),
            locked=data.get("locked", False),
            opacity=_float(data.get("opacity", 1.0), "opacity"),
            order=_int(data.get("order", 0), "layer.order"),
            time_binding=TimeBinding.from_dict(data.get("time_binding", {})),
            transform=Transform.from_dict(data.get("transform", {})),
            properties=deepcopy(data.get("properties", {})),
            animation=deepcopy(data.get("animation", {})),
            asset_refs=list(data.get("asset_refs", []) or []),
            origin=str(data.get("origin", "manual")),
        )
        item.validate()
        return item


@dataclass
class ProjectDocument:
    format: str = PROJECT_FORMAT
    schema_version: int = SCHEMA_VERSION
    project_id: str = field(default_factory=new_id)
    revision: int = 0
    name: str = "Proyek Baru"
    album_title: str = ""
    canvas: CanvasSettings = field(default_factory=CanvasSettings)
    timebase: int = TIMEBASE
    media: list[MediaAsset] = field(default_factory=list)
    playlist: Playlist = field(default_factory=Playlist)
    tracks: list[Track] = field(default_factory=list)
    layers: list[Layer] = field(default_factory=list)
    render_settings: dict[str, Any] = field(default_factory=dict)
    editor_defaults: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new_empty(cls, name: str = "Proyek Baru") -> "ProjectDocument":
        return cls(name=name, tracks=[Track(name="Elemen Visual", kind="visual", order=0), Track(name="Audio Master", kind="audio", order=1)])

    def clone(self) -> "ProjectDocument":
        return deepcopy(self)

    def asset_map(self) -> dict[str, MediaAsset]:
        return {x.asset_id: x for x in self.media}

    def song_map(self) -> dict[str, SongInstance]:
        return {x.song_id: x for x in self.playlist.entries}

    def layer_map(self) -> dict[str, Layer]:
        return {x.layer_id: x for x in self.layers}

    def validate(self) -> None:
        if self.format != PROJECT_FORMAT:
            raise ProjectSchemaError("Format proyek tidak didukung.")
        if self.schema_version != SCHEMA_VERSION:
            if self.schema_version > SCHEMA_VERSION:
                raise ProjectSchemaError("Versi proyek lebih baru belum didukung.")
            raise ProjectSchemaError("Versi proyek tidak didukung.")
        _uuid(self.project_id, "project_id")
        self.revision = _int(self.revision, "revision")
        if self.timebase != TIMEBASE:
            raise ProjectSchemaError(f"timebase harus {TIMEBASE}.")
        self.canvas.validate()
        if not all(isinstance(x, dict) for x in (self.render_settings, self.editor_defaults, self.extensions)):
            raise ProjectSchemaError("Settings/extensions proyek tidak valid.")

        asset_ids: set[str] = set()
        for asset in self.media:
            asset.validate()
            if asset.asset_id in asset_ids:
                raise ProjectSchemaError("asset_id duplikat.")
            asset_ids.add(asset.asset_id)

        self.playlist.validate()
        assets = self.asset_map()
        for song in self.playlist.entries:
            asset = assets.get(song.asset_id)
            if asset is None:
                raise ProjectSchemaError("Playlist merujuk asset yang tidak ada.")
            if asset.kind != "audio":
                raise ProjectSchemaError("SongInstance harus merujuk asset audio.")
            if asset.source_duration_tick > 0:
                end = song.source_out_tick if song.source_out_tick is not None else asset.source_duration_tick
                if song.source_in_tick >= asset.source_duration_tick or end > asset.source_duration_tick:
                    raise ProjectSchemaError("Source range lagu melewati durasi asset.")
            if song.cover_asset_id and song.cover_asset_id not in asset_ids:
                raise ProjectSchemaError("cover_asset_id tidak ditemukan.")
            if song.visual_asset_id and song.visual_asset_id not in asset_ids:
                raise ProjectSchemaError("visual_asset_id tidak ditemukan.")

        track_ids: set[str] = set()
        for track in self.tracks:
            track.validate()
            if track.track_id in track_ids:
                raise ProjectSchemaError("track_id duplikat.")
            track_ids.add(track.track_id)

        layer_ids: set[str] = set()
        for layer in self.layers:
            layer.validate()
            if layer.layer_id in layer_ids:
                raise ProjectSchemaError("layer_id duplikat.")
            layer_ids.add(layer.layer_id)
            if layer.track_id not in track_ids:
                raise ProjectSchemaError("Layer merujuk track yang tidak ada.")
            if any(ref not in asset_ids for ref in layer.asset_refs):
                raise ProjectSchemaError("Layer merujuk asset yang tidak ada.")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "format": self.format,
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "revision": self.revision,
            "name": self.name,
            "album_title": self.album_title,
            "canvas": asdict(self.canvas),
            "timebase": self.timebase,
            "media": [asdict(x) for x in self.media],
            "playlist": {"mode": self.playlist.mode, "entries": [asdict(x) for x in self.playlist.entries]},
            "tracks": [asdict(x) for x in self.tracks],
            "layers": [asdict(x) for x in self.layers],
            "render_settings": deepcopy(self.render_settings),
            "editor_defaults": deepcopy(self.editor_defaults),
            "extensions": deepcopy(self.extensions),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "ProjectDocument":
        if not isinstance(data, dict) or data.get("format") != PROJECT_FORMAT:
            raise ProjectSchemaError("Format proyek tidak didukung.")
        version = _int(data.get("schema_version", 0), "schema_version")
        if version > SCHEMA_VERSION:
            raise ProjectSchemaError("Versi proyek lebih baru belum didukung.")
        if version != SCHEMA_VERSION:
            raise ProjectSchemaError("Versi proyek tidak didukung.")
        raw_media, raw_tracks, raw_layers = data.get("media", []), data.get("tracks", []), data.get("layers", [])
        if not isinstance(raw_media, list) or not isinstance(raw_tracks, list) or not isinstance(raw_layers, list):
            raise ProjectSchemaError("Daftar media/track/layer proyek tidak valid.")
        item = cls(
            project_id=_uuid(data.get("project_id"), "project_id"),
            revision=_int(data.get("revision", 0), "revision"),
            name=str(data.get("name", "Proyek Baru")),
            album_title=str(data.get("album_title", "") or ""),
            canvas=CanvasSettings.from_dict(data.get("canvas", {})),
            timebase=_int(data.get("timebase", TIMEBASE), "timebase", 1),
            media=[MediaAsset.from_dict(x) for x in raw_media],
            playlist=Playlist.from_dict(data.get("playlist", {})),
            tracks=[Track.from_dict(x) for x in raw_tracks],
            layers=[Layer.from_dict(x) for x in raw_layers],
            render_settings=deepcopy(data.get("render_settings", {})),
            editor_defaults=deepcopy(data.get("editor_defaults", {})),
            extensions=deepcopy(data.get("extensions", {})),
        )
        item.validate()
        return item

    def content_signature(self) -> str:
        payload = self.to_dict()
        payload.pop("revision", None)
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def infer_asset_kind(path: str, default: str = "other") -> str:
    ext = Path(path).suffix.casefold()
    if ext in {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"}:
        return "audio"
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        return "image"
    if ext in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}:
        return "video"
    return default
