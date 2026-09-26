from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QFileDialog,
)

from . import agent_actions as agent_actions_module
from . import gemini_agent as gemini_agent_module
from . import playlist_feature as playlist_feature_module
from . import playlist_hardening as playlist_hardening_module
from . import renderer as renderer_module
from . import timeline as timeline_module
from . import ui as ui_module
from .media import MediaProbeError, probe_duration
from .paths import ffprobe_path, output_dir, temp_dir
from .project import MediaItem, Project
from .renderer import FFmpegRenderer, RenderError, _concat_path, _q
from .timeline import (
    AudioTimelineClip,
    EPSILON,
    MAX_TIMELINE_CLIPS,
    TimelineError,
    TimelinePlan,
    VideoTimelineClip,
    save_timeline,
)


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VISUAL_ACTIONS = {
    "set_visual_mode",
    "set_photo_duration",
    "set_photo_fit",
    "set_photo_motion",
    "set_title_style",
    "assign_song_cover",
    "assign_song_visual",
}

_DEFAULT_SETTINGS = {
    "visual_mode": "sequential",
    "photo_duration": 10.0,
    "photo_fit": "fit_blur",
    "photo_motion": "zoom",
    "photo_zoom_end": 1.08,
    "title_mode": "full",
    "title_animation": "fade",
    "visual_transition": "none",
}

_installed = False
_originals: dict[str, Any] = {}


def _path_key(value: str) -> str:
    return str(Path(value).expanduser().resolve()).casefold()


def _ensure_project(project: Project) -> Project:
    if not hasattr(project, "images") or not isinstance(getattr(project, "images"), list):
        setattr(project, "images", [])
    if not hasattr(project, "_visual_settings") or not isinstance(
        getattr(project, "_visual_settings"), dict
    ):
        setattr(project, "_visual_settings", {})
    settings = getattr(project, "_visual_settings")
    for key, value in _DEFAULT_SETTINGS.items():
        settings.setdefault(key, value)
    if not hasattr(project, "_visual_order") or not isinstance(
        getattr(project, "_visual_order"), list
    ):
        setattr(project, "_visual_order", [])
    return project


def images(project: Project) -> list[MediaItem]:
    _ensure_project(project)
    return getattr(project, "images")


def visual_settings(project: Project) -> dict[str, Any]:
    _ensure_project(project)
    return getattr(project, "_visual_settings")


def _get_item_attr(item: MediaItem, name: str, default: Any = None) -> Any:
    return getattr(item, name, default)


def _set_item_attr(item: MediaItem, name: str, value: Any) -> None:
    setattr(item, name, value)


def display_title(item: MediaItem) -> str:
    value = str(_get_item_attr(item, "display_title", "") or "").strip()
    return value or Path(item.path).stem


def display_artist(item: MediaItem) -> str:
    return str(_get_item_attr(item, "display_artist", "") or "").strip()


def probe_image(path: str) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        raise MediaProbeError(f"File tidak ditemukan: {target}")
    if target.suffix.casefold() not in IMAGE_EXTENSIONS:
        raise MediaProbeError(f"Format foto belum didukung: {target.suffix or '(tanpa ekstensi)'}")

    reader = QImageReader(str(target))
    reader.setAutoTransform(True)
    if not reader.canRead():
        detail = reader.errorString() or "decoder tidak dapat membaca file"
        raise MediaProbeError(f"Foto tidak valid: {target.name} ({detail})")
    try:
        animated = bool(reader.supportsAnimation()) and int(reader.imageCount()) not in {0, 1}
    except Exception:
        animated = bool(reader.supportsAnimation())
    if animated:
        raise MediaProbeError(
            f"Foto animasi belum didukung: {target.name}. Gunakan JPG/PNG/WebP statis."
        )
    image = reader.read()
    if image.isNull():
        detail = reader.errorString() or "decode gagal"
        raise MediaProbeError(f"Foto tidak dapat didekode: {target.name} ({detail})")
    return {
        "width": int(image.width()),
        "height": int(image.height()),
        "format": target.suffix.casefold().lstrip("."),
    }


def probe_audio_tags(path: str) -> tuple[str, str]:
    tool = ffprobe_path()
    if not tool:
        return "", ""
    try:
        proc = subprocess.run(
            [
                tool,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "format_tags=title,artist:stream_tags=title,artist",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=True,
        )
        payload = json.loads(proc.stdout or "{}")
        tags: dict[str, Any] = {}
        tags.update((payload.get("format") or {}).get("tags") or {})
        streams = payload.get("streams") or []
        if streams:
            for key, value in ((streams[0].get("tags") or {}).items()):
                tags.setdefault(key, value)
        title = str(tags.get("title") or tags.get("TITLE") or "").strip()
        artist = str(tags.get("artist") or tags.get("ARTIST") or "").strip()
        return title, artist
    except Exception:
        return "", ""


def _enrich_audio_metadata(project: Project) -> None:
    for item in project.audios:
        if _get_item_attr(item, "metadata_probed", False):
            continue
        title, artist = probe_audio_tags(item.path)
        if title and not _get_item_attr(item, "display_title", ""):
            _set_item_attr(item, "display_title", title)
        if artist and not _get_item_attr(item, "display_artist", ""):
            _set_item_attr(item, "display_artist", artist)
        _set_item_attr(item, "metadata_probed", True)


def _serialize_audio(item: MediaItem) -> dict[str, Any]:
    data = {"path": item.path, "duration": float(item.duration)}
    for name in ("display_title", "display_artist", "cover_path", "visual_path"):
        value = _get_item_attr(item, name, "")
        if value:
            data[name] = value
    return data


def _serialize_image(item: MediaItem) -> dict[str, Any]:
    return {
        "path": item.path,
        "duration": 0.0,
        "width": int(_get_item_attr(item, "width", 0) or 0),
        "height": int(_get_item_attr(item, "height", 0) or 0),
        "fit": str(_get_item_attr(item, "fit", "") or ""),
        "motion": str(_get_item_attr(item, "motion", "") or ""),
        "display_duration": float(_get_item_attr(item, "display_duration", 0.0) or 0.0),
    }


def _restore_audio_extras(project: Project, raw_audios: Any) -> None:
    if not isinstance(raw_audios, list):
        return
    for item, raw in zip(project.audios, raw_audios):
        if not isinstance(raw, dict):
            continue
        for name in ("display_title", "display_artist", "cover_path", "visual_path"):
            value = raw.get(name, "")
            if value is not None and not isinstance(value, str):
                raise ValueError(f"Field {name} pada lagu tidak valid.")
            if value:
                _set_item_attr(item, name, value)
        _set_item_attr(item, "metadata_probed", True)


def _restore_images(project: Project, raw_images: Any) -> None:
    if raw_images is None:
        raw_images = []
    if not isinstance(raw_images, list):
        raise ValueError("Daftar foto proyek tidak valid.")
    restored: list[MediaItem] = []
    for index, raw in enumerate(raw_images, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Foto #{index} tidak valid.")
        path = raw.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"Path foto #{index} tidak valid.")
        item = MediaItem(path=path, duration=0.0)
        try:
            width = int(raw.get("width", 0) or 0)
            height = int(raw.get("height", 0) or 0)
            display_duration = float(raw.get("display_duration", 0.0) or 0.0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Metadata foto #{index} tidak valid.") from exc
        if width < 0 or height < 0 or not math.isfinite(display_duration) or display_duration < 0:
            raise ValueError(f"Metadata foto #{index} tidak valid.")
        _set_item_attr(item, "width", width)
        _set_item_attr(item, "height", height)
        _set_item_attr(item, "fit", str(raw.get("fit") or ""))
        _set_item_attr(item, "motion", str(raw.get("motion") or ""))
        _set_item_attr(item, "display_duration", display_duration)
        restored.append(item)
    setattr(project, "images", restored)


def _patched_project_to_dict(self: Project) -> dict[str, Any]:
    _ensure_project(self)
    data = _originals["project_to_dict"](self)
    data["audios"] = [_serialize_audio(item) for item in self.audios]
    data["images"] = [_serialize_image(item) for item in images(self)]
    data["visual_settings"] = dict(visual_settings(self))
    data["visual_order"] = list(getattr(self, "_visual_order", []))
    return data


def _patched_project_from_dict(cls, data: dict[str, Any]) -> Project:
    project = _originals["project_from_dict_bound"](data)
    _ensure_project(project)
    _restore_audio_extras(project, data.get("audios", []) if isinstance(data, dict) else [])
    _restore_images(project, data.get("images", []) if isinstance(data, dict) else [])

    raw_settings = data.get("visual_settings", {}) if isinstance(data, dict) else {}
    if raw_settings is None:
        raw_settings = {}
    if not isinstance(raw_settings, dict):
        raise ValueError("Pengaturan visual proyek tidak valid.")
    settings = visual_settings(project)
    settings.update(raw_settings)
    _validate_visual_settings(settings)

    raw_order = data.get("visual_order", []) if isinstance(data, dict) else []
    if raw_order is None:
        raw_order = []
    if not isinstance(raw_order, list) or not all(isinstance(x, str) for x in raw_order):
        raise ValueError("Urutan visual proyek tidak valid.")
    setattr(project, "_visual_order", list(raw_order))
    return project


def _validate_visual_settings(settings: dict[str, Any]) -> None:
    if settings.get("visual_mode") not in {"sequential", "per_song"}:
        raise ValueError("Mode visual tidak valid.")
    try:
        photo_duration = float(settings.get("photo_duration", 10.0))
        zoom_end = float(settings.get("photo_zoom_end", 1.08))
    except (TypeError, ValueError) as exc:
        raise ValueError("Pengaturan durasi/zoom foto tidak valid.") from exc
    if not math.isfinite(photo_duration) or not 0.2 <= photo_duration <= 3600:
        raise ValueError("Durasi foto harus 0.2–3600 detik.")
    if not math.isfinite(zoom_end) or not 1.0 <= zoom_end <= 1.5:
        raise ValueError("Zoom akhir foto harus 1.0–1.5.")
    if settings.get("photo_fit") not in {"fit", "fill", "fit_blur"}:
        raise ValueError("Mode fit foto tidak valid.")
    if settings.get("photo_motion") not in {"static", "zoom"}:
        raise ValueError("Gerak foto tidak valid.")
    if settings.get("title_mode") not in {"full", "intro6", "off"}:
        raise ValueError("Mode judul lagu tidak valid.")
    if settings.get("title_animation") not in {"none", "fade", "slide"}:
        raise ValueError("Animasi judul tidak valid.")
    if settings.get("visual_transition") not in {"none", "fade"}:
        raise ValueError("Transisi visual tidak valid.")


def _patched_validation(self: Project) -> dict[str, list[str]]:
    _ensure_project(self)
    report = _originals["project_validation"](self)
    errors = list(report.get("errors", []))
    warnings = list(report.get("warnings", []))
    if images(self):
        errors = [
            err
            for err in errors
            if err not in {"Belum ada footage video.", "Durasi footage tidak valid."}
        ]
    if not self.videos and not images(self):
        errors = [err for err in errors if err != "Belum ada footage video."]
        errors.append("Belum ada visual. Tambahkan minimal satu video atau foto.")
    missing_images = [item.name for item in images(self) if not Path(item.path).exists()]
    if missing_images:
        errors.append(f"{len(missing_images)} file foto tidak ditemukan.")
    try:
        _validate_visual_settings(visual_settings(self))
    except ValueError as exc:
        errors.append(str(exc))
    return {"errors": errors, "warnings": warnings}


def _photo_seconds(project: Project, item: MediaItem | None = None) -> float:
    if item is not None:
        override = float(_get_item_attr(item, "display_duration", 0.0) or 0.0)
        if override > 0:
            return override
    return float(visual_settings(project)["photo_duration"])


def _base_visual_capacity(project: Project, speed: float) -> float:
    mode = visual_settings(project)["visual_mode"]
    if mode == "per_song" and images(project):
        return float(project.total_audio_duration)
    video = sum(max(0.0, item.duration) for item in project.videos)
    photo = sum(_photo_seconds(project, item) for item in images(project))
    return (video / max(speed, 0.01)) + photo


def _patched_planned_speed(self: Project) -> float:
    _ensure_project(self)
    if not self.videos:
        return 1.0
    if not self.settings.auto_speed:
        return max(0.01, self.settings.manual_speed)
    album = float(self.total_audio_duration)
    if album <= 0:
        return 1.0
    photo = 0.0
    if visual_settings(self)["visual_mode"] == "sequential":
        photo = sum(_photo_seconds(self, item) for item in images(self))
    elif images(self):
        return 1.0
    remaining = album - photo
    if remaining <= 0:
        return 1.0
    video = sum(max(0.0, item.duration) for item in self.videos)
    desired = video / remaining if remaining else 1.0
    if desired >= 1.0:
        return 1.0
    return max(self.settings.min_speed, desired)


def _patched_adjusted_visual_duration(self: Project) -> float:
    return _base_visual_capacity(self, self.planned_speed())


def _patched_needs_loop(self: Project) -> bool:
    return self.adjusted_video_duration() + 1e-6 < self.total_audio_duration


def visual_project_signature(project: Project) -> str:
    _ensure_project(project)
    base = _originals["project_signature"](project)
    payload = {
        "base": base,
        "images": [
            {
                "path": item.path,
                "width": int(_get_item_attr(item, "width", 0) or 0),
                "height": int(_get_item_attr(item, "height", 0) or 0),
                "fit": _get_item_attr(item, "fit", ""),
                "motion": _get_item_attr(item, "motion", ""),
                "display_duration": float(_get_item_attr(item, "display_duration", 0.0) or 0.0),
            }
            for item in images(project)
        ],
        "visual_settings": visual_settings(project),
        "visual_order": list(getattr(project, "_visual_order", [])),
        "audio_display": [
            {
                "title": display_title(item),
                "artist": display_artist(item),
                "cover": _get_item_attr(item, "cover_path", ""),
                "visual": _get_item_attr(item, "visual_path", ""),
            }
            for item in project.audios
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _patched_plan_validate(self: TimelinePlan) -> list[str]:
    changed: list[tuple[VideoTimelineClip, str]] = []
    for clip in self.video_clips:
        if clip.kind == "image":
            changed.append((clip, clip.kind))
            clip.kind = "source"
    try:
        return _originals["plan_validate"](self)
    finally:
        for clip, kind in changed:
            clip.kind = kind


def validate_visual_timeline(plan: TimelinePlan, project: Project) -> list[str]:
    _ensure_project(project)
    errors = list(plan.validate())
    if plan.project_signature != visual_project_signature(project):
        errors.append("Timeline tidak cocok dengan proyek atau setting saat ini.")
        return errors

    for index, clip in enumerate(plan.video_clips):
        if clip.kind == "image":
            if not 0 <= clip.source_index < len(images(project)):
                errors.append(f"Foto clip {index + 1} menunjuk source_index yang tidak valid.")
                continue
            source = images(project)[clip.source_index]
            if Path(clip.source) != Path(source.path):
                errors.append(f"Foto clip {index + 1} tidak cocok dengan source proyek.")
            if clip.direction != "forward":
                errors.append(f"Foto clip {index + 1} tidak boleh reverse.")
            continue

        if not 0 <= clip.source_index < len(project.videos):
            errors.append(f"Video clip {index + 1} menunjuk source_index yang tidak valid.")
            continue
        source = project.videos[clip.source_index]
        if Path(clip.source) != Path(source.path):
            errors.append(f"Video clip {index + 1} tidak cocok dengan source proyek.")
        if clip.source_in < -0.002 or clip.source_out > source.duration + 0.002:
            errors.append(f"Video clip {index + 1} melewati batas durasi source.")

    for index, clip in enumerate(plan.audio_clips):
        if not 0 <= clip.source_index < len(project.audios):
            errors.append(f"Audio clip {index + 1} menunjuk source_index yang tidak valid.")
            continue
        source = project.audios[clip.source_index]
        if Path(clip.source) != Path(source.path):
            errors.append(f"Audio clip {index + 1} tidak cocok dengan source proyek.")
        if clip.source_in < -0.002 or clip.source_out > source.duration + 0.002:
            errors.append(f"Audio clip {index + 1} melewati batas durasi source.")
    return errors


BasePlaylistTimelineEngine = playlist_feature_module.PlaylistTimelineEngine


class VisualPlaylistTimelineEngine(BasePlaylistTimelineEngine):
    @staticmethod
    def _validate_project_for_timeline(project: Project) -> None:
        _ensure_project(project)
        if not project.videos and not images(project):
            raise TimelineError("Belum ada visual. Tambahkan minimal satu video atau foto.")
        if not project.audios:
            raise TimelineError("Belum ada lagu di Media.")
        selected = playlist_feature_module.active_audio_items(project, strict=True)
        if not selected:
            raise TimelineError("Playlist aktif tidak memiliki lagu.")
        if playlist_feature_module.active_audio_duration(project) <= 0:
            raise TimelineError("Durasi playlist tidak valid.")
        for item in project.videos:
            if item.duration <= 0:
                raise TimelineError(f"Durasi footage tidak valid: {item.name}")
        for item in selected:
            if item.duration <= 0:
                raise TimelineError(f"Durasi lagu tidak valid: {item.name}")

    @staticmethod
    def _build_audio_track(project: Project) -> list[AudioTimelineClip]:
        clips: list[AudioTimelineClip] = []
        cursor = 0.0
        for source_index in playlist_feature_module.active_audio_indices(project, strict=True):
            item = project.audios[source_index]
            end = cursor + item.duration
            clips.append(
                AudioTimelineClip(
                    source=item.path,
                    source_index=source_index,
                    name=display_title(item),
                    source_in=0.0,
                    source_out=item.duration,
                    timeline_in=cursor,
                    timeline_out=end,
                )
            )
            cursor = end
        return clips

    def build(self, project: Project) -> TimelinePlan:
        self._validate_project_for_timeline(project)
        album_duration = playlist_feature_module.active_audio_duration(project)
        speed = project.planned_speed()
        capacity = _base_visual_capacity(project, speed)
        auto_cut = max(0.0, capacity - album_duration)
        loop_fill = max(0.0, album_duration - capacity)
        mode = project.settings.loop_mode
        if mode == "auto":
            mode = "loop" if loop_fill > EPSILON else "none"
        if loop_fill <= EPSILON:
            mode = "none"
        if loop_fill > EPSILON and mode == "none":
            raise TimelineError("Visual lebih pendek dari playlist tetapi mode loop dimatikan.")

        plan = TimelinePlan(
            duration=album_duration,
            planned_speed=speed,
            source_video_duration=sum(max(0.0, x.duration) for x in project.videos),
            adjusted_video_duration=capacity,
            auto_cut_seconds=auto_cut,
            loop_fill_seconds=loop_fill,
            loop_mode=mode,
            project_signature=visual_project_signature(project),
        )
        plan.audio_clips = self._build_audio_track(project)
        if visual_settings(project)["visual_mode"] == "per_song" and images(project):
            plan.video_clips = self._build_per_song_images(project, plan.audio_clips)
        else:
            plan.video_clips = self._build_sequential_visuals(project, plan, mode)

        errors = plan.validate()
        if errors:
            raise TimelineError("Timeline gagal divalidasi: " + " ".join(errors))
        return plan

    @staticmethod
    def _ordered_visuals(project: Project) -> list[tuple[str, int, MediaItem]]:
        video_by_key = {_path_key(item.path): ("video", index, item) for index, item in enumerate(project.videos)}
        image_by_key = {_path_key(item.path): ("image", index, item) for index, item in enumerate(images(project))}
        all_by_key = {**video_by_key, **image_by_key}
        ordered: list[tuple[str, int, MediaItem]] = []
        used: set[str] = set()
        for raw in getattr(project, "_visual_order", []):
            key = _path_key(raw)
            value = all_by_key.get(key)
            if value is not None and key not in used:
                ordered.append(value)
                used.add(key)
        for key, value in [*video_by_key.items(), *image_by_key.items()]:
            if key not in used:
                ordered.append(value)
                used.add(key)
        return ordered

    @staticmethod
    def _build_per_song_images(
        project: Project,
        audio_clips: list[AudioTimelineClip],
    ) -> list[VideoTimelineClip]:
        result: list[VideoTimelineClip] = []
        image_items = images(project)
        by_key = {_path_key(item.path): index for index, item in enumerate(image_items)}
        for position, audio_clip in enumerate(audio_clips):
            audio_item = project.audios[audio_clip.source_index]
            explicit = str(_get_item_attr(audio_item, "visual_path", "") or "").strip()
            image_index = by_key.get(_path_key(explicit)) if explicit else None
            if explicit and image_index is None:
                raise TimelineError(
                    f"Visual yang dipetakan untuk lagu {position + 1} sudah tidak tersedia di Media: "
                    f"{Path(explicit).name}"
                )
            if image_index is None:
                image_index = position % len(image_items)
            image = image_items[image_index]
            duration = audio_clip.timeline_duration
            result.append(
                VideoTimelineClip(
                    source=image.path,
                    source_index=image_index,
                    name=Path(image.path).stem,
                    source_in=0.0,
                    source_out=duration,
                    timeline_in=audio_clip.timeline_in,
                    timeline_out=audio_clip.timeline_out,
                    speed=1.0,
                    direction="forward",
                    kind="image",  # type: ignore[arg-type]
                    cycle=0,
                )
            )
        return result

    @classmethod
    def _build_sequential_visuals(
        cls,
        project: Project,
        plan: TimelinePlan,
        resolved_mode: str,
    ) -> list[VideoTimelineClip]:
        ordered = cls._ordered_visuals(project)
        if not ordered:
            raise TimelineError("Tidak ada visual yang dapat disusun.")
        result: list[VideoTimelineClip] = []
        cursor = 0.0
        cycle = 0
        target = plan.duration
        while cursor < target - EPSILON:
            for kind, source_index, item in ordered:
                if cursor >= target - EPSILON:
                    break
                if len(result) >= MAX_TIMELINE_CLIPS:
                    raise TimelineError(
                        f"Timeline melebihi batas {MAX_TIMELINE_CLIPS} clip visual."
                    )
                if kind == "image":
                    natural = _photo_seconds(project, item)
                    used = min(natural, target - cursor)
                    result.append(
                        VideoTimelineClip(
                            source=item.path,
                            source_index=source_index,
                            name=Path(item.path).stem,
                            source_in=0.0,
                            source_out=used,
                            timeline_in=cursor,
                            timeline_out=cursor + used,
                            speed=1.0,
                            direction="forward",
                            kind="image",  # type: ignore[arg-type]
                            cycle=cycle,
                        )
                    )
                    cursor += used
                    continue

                direction = "forward"
                clip_kind = "source" if cycle == 0 else "loop"
                if cycle > 0 and resolved_mode == "pingpong" and cycle % 2 == 1:
                    direction = "reverse"
                    clip_kind = "pingpong"
                natural = item.duration / plan.planned_speed
                used = min(natural, target - cursor)
                source_amount = used * plan.planned_speed
                if direction == "reverse":
                    source_in = max(0.0, item.duration - source_amount)
                    source_out = item.duration
                else:
                    source_in = 0.0
                    source_out = min(item.duration, source_amount)
                result.append(
                    VideoTimelineClip(
                        source=item.path,
                        source_index=source_index,
                        name=Path(item.path).stem,
                        source_in=source_in,
                        source_out=source_out,
                        timeline_in=cursor,
                        timeline_out=cursor + used,
                        speed=plan.planned_speed,
                        direction=direction,  # type: ignore[arg-type]
                        kind=clip_kind,  # type: ignore[arg-type]
                        cycle=cycle,
                    )
                )
                cursor += used
            if cursor >= target - EPSILON:
                break
            if resolved_mode == "none":
                raise TimelineError("Visual tidak cukup untuk menutup durasi playlist.")
            cycle += 1
        return result


def _image_filters(project: Project, item: MediaItem, duration: float) -> str:
    settings = project.settings
    config = visual_settings(project)
    fit = str(_get_item_attr(item, "fit", "") or config["photo_fit"])
    motion = str(_get_item_attr(item, "motion", "") or config["photo_motion"])
    w, h, fps = settings.width, settings.height, settings.fps
    if fit == "fill":
        chain = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1"
        )
    elif fit == "fit":
        chain = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
        )
    else:
        chain = (
            f"split=2[bg][fg];"
            f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},boxblur=20:1[bg2];"
            f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fg2];"
            f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )
    if motion == "zoom":
        frames = max(1, int(round(duration * fps)))
        zoom_end = float(config["photo_zoom_end"])
        if ";" in chain:
            chain += (
                f",zoompan=z='1+({zoom_end - 1.0:.6f})*min(on/{max(1, frames - 1)},1)':"
                f"d=1:s={w}x{h}:fps={fps}"
            )
        else:
            chain += (
                f",zoompan=z='1+({zoom_end - 1.0:.6f})*min(on/{max(1, frames - 1)},1)':"
                f"d=1:s={w}x{h}:fps={fps}"
            )
    return chain + ",format=yuv420p"


def _encode_image_segment(
    self: FFmpegRenderer,
    clip: VideoTimelineClip,
    item: MediaItem,
    out: Path,
    log=None,
    target_frames: int | None = None,
) -> None:
    settings = self.project.settings
    duration = clip.timeline_duration
    target_frames = target_frames or max(1, int(round(duration * settings.fps)))
    filters = _image_filters(self.project, item, duration)
    args = [
        self.ffmpeg,
        "-y",
        "-loop",
        "1",
        "-framerate",
        str(settings.fps),
        "-i",
        _q(clip.source),
    ]
    if ";" in filters:
        args += ["-filter_complex", f"[0:v]{filters}[v]", "-map", "[v]"]
    else:
        args += ["-vf", filters]
    args += [
        "-an",
        "-c:v",
        self._encoder_name(),
        "-preset",
        "medium",
        "-b:v",
        settings.video_bitrate,
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(settings.fps),
        "-frames:v",
        str(target_frames),
        str(out),
    ]
    self._run(args, log)


def _patched_encode_video_segment(
    self: FFmpegRenderer,
    *,
    source: str,
    source_in: float,
    source_out: float,
    speed: float,
    timeline_duration: float,
    reverse: bool,
    out: Path,
    log=None,
    target_frames: int | None = None,
) -> None:
    if source_out <= source_in + EPSILON:
        raise RenderError("Video timeline memiliki source range kosong.")
    if speed <= 0:
        raise RenderError("Video timeline memiliki speed tidak valid.")
    settings = self.project.settings
    source_duration = source_out - source_in
    target_frames = target_frames or max(1, int(round(timeline_duration * settings.fps)))
    filters = [
        "scale='trunc(iw*sar/2)*2':ih",
        "setsar=1",
        f"scale={settings.width}:{settings.height}:force_original_aspect_ratio=decrease",
        f"pad={settings.width}:{settings.height}:(ow-iw)/2:(oh-ih)/2",
        "format=yuv420p",
    ]
    if reverse:
        filters.append("reverse")
    filters += [
        f"setpts=(PTS-STARTPTS)/{speed:.10f}",
        f"fps={settings.fps}",
        "tpad=stop_mode=clone:stop_duration=1.0",
        f"trim=end_frame={target_frames}",
        "setpts=PTS-STARTPTS",
    ]
    args = [
        self.ffmpeg,
        "-y",
        "-ss",
        f"{source_in:.6f}",
        "-t",
        f"{source_duration:.6f}",
        "-i",
        _q(source),
        "-vf",
        ",".join(filters),
        "-an",
        "-c:v",
        self._encoder_name(),
        "-preset",
        "medium",
        "-b:v",
        settings.video_bitrate,
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(settings.fps),
        "-frames:v",
        str(target_frames),
        str(out),
    ]
    self._run(args, log)


def _render_title_card(
    project: Project,
    audio_clip: AudioTimelineClip,
    track_number: int,
    path: Path,
) -> None:
    audio_item = project.audios[audio_clip.source_index]
    title = display_title(audio_item)
    artist = display_artist(audio_item)
    cover_path = str(_get_item_attr(audio_item, "cover_path", "") or "")

    scale = max(0.7, min(1.6, project.settings.height / 1080.0))
    card_w = int(760 * scale)
    card_h = int((170 if cover_path else 132) * scale)
    image = QImage(card_w, card_h, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(6, 14, 24, 208))
    painter.drawRoundedRect(QRectF(0, 0, card_w, card_h), 18 * scale, 18 * scale)

    x = int(22 * scale)
    cover_size = 0
    if cover_path and Path(cover_path).exists():
        reader = QImageReader(cover_path)
        reader.setAutoTransform(True)
        cover = reader.read()
        if not cover.isNull():
            cover_size = int((card_h - 28 * scale))
            cover = cover.scaled(
                cover_size,
                cover_size,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            painter.drawImage(QRectF(x, 14 * scale, cover_size, cover_size), cover)
            x += cover_size + int(20 * scale)

    painter.setPen(QColor("#91a4bb"))
    small = QFont()
    small.setPixelSize(max(12, int(15 * scale)))
    small.setBold(True)
    painter.setFont(small)
    painter.drawText(
        QRectF(x, 14 * scale, card_w - x - 18 * scale, 24 * scale),
        Qt.AlignLeft | Qt.AlignVCenter,
        f"TRACK {track_number:02d}",
    )

    painter.setPen(QColor("#ffffff"))
    title_font = QFont()
    title_font.setPixelSize(max(18, int(29 * scale)))
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.drawText(
        QRectF(x, 38 * scale, card_w - x - 20 * scale, 60 * scale),
        Qt.AlignLeft | Qt.AlignVCenter,
        title,
    )

    if artist:
        painter.setPen(QColor("#c8d5e5"))
        artist_font = QFont()
        artist_font.setPixelSize(max(14, int(19 * scale)))
        painter.setFont(artist_font)
        painter.drawText(
            QRectF(x, 94 * scale, card_w - x - 20 * scale, 38 * scale),
            Qt.AlignLeft | Qt.AlignVCenter,
            artist,
        )
    painter.end()
    if not image.save(str(path), "PNG"):
        raise RenderError(f"Gagal membuat kartu judul: {path.name}")


def _title_overlay_filter(project: Project, duration: float) -> str:
    config = visual_settings(project)
    mode = config["title_mode"]
    animation = config["title_animation"]
    visible = duration if mode == "full" else min(duration, 6.0)
    visible = max(0.0, visible)
    fade = min(0.4, visible / 2.0) if visible > 0 else 0.0
    x = "main_w*0.05"
    y = "main_h-overlay_h-main_h*0.05"
    card_chain = "[1:v]format=rgba"
    if animation == "fade" and fade > 0:
        card_chain += f",fade=t=in:st=0:d={fade:.3f}:alpha=1"
        if visible < duration or mode == "full":
            card_chain += (
                f",fade=t=out:st={max(0.0, visible - fade):.3f}:d={fade:.3f}:alpha=1"
            )
    card_chain += "[card]"
    if animation == "slide" and fade > 0:
        target = "main_w*0.05"
        x = (
            f"if(lt(t\\,{fade:.3f})\\,-overlay_w+({target}+overlay_w)*t/{fade:.3f}\\,"
            f"if(gt(t\\,{max(0.0, visible - fade):.3f})\\,{target}-({target}+overlay_w)*(t-{max(0.0, visible - fade):.3f})/{fade:.3f}\\,{target}))"
        )
    enable = f"between(t,0,{max(0.0, visible):.3f})"
    return f"{card_chain};[0:v][card]overlay=x='{x}':y='{y}':enable='{enable}',format=yuv420p[vout]"


def _apply_title_cards(
    self: FFmpegRenderer,
    base_video: Path,
    out: Path,
    work: Path,
    log=None,
) -> None:
    config = visual_settings(self.project)
    if config["title_mode"] == "off" or not self.timeline.audio_clips:
        if base_video != out:
            import shutil
            shutil.copyfile(base_video, out)
        return

    title_dir = work / "title_segments"
    title_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    for index, clip in enumerate(self.timeline.audio_clips, start=1):
        card = title_dir / f"title_{index:04d}.png"
        segment = title_dir / f"song_{index:04d}.mp4"
        _render_title_card(self.project, clip, index, card)
        fps = self.project.settings.fps
        start_frame = int(round(clip.timeline_in * fps))
        end_frame = int(round(clip.timeline_out * fps))
        frame_count = max(1, end_frame - start_frame)
        duration = frame_count / fps
        if log:
            log(f"Judul lagu {index}/{len(self.timeline.audio_clips)}: {clip.name}")
        args = [
            self.ffmpeg,
            "-y",
            "-ss",
            f"{start_frame / fps:.9f}",
            "-t",
            f"{duration:.6f}",
            "-i",
            str(base_video),
            "-loop",
            "1",
            "-i",
            str(card),
            "-filter_complex",
            _title_overlay_filter(self.project, duration),
            "-map",
            "[vout]",
            "-an",
            "-c:v",
            self._encoder_name(),
            "-preset",
            "medium",
            "-b:v",
            self.project.settings.video_bitrate,
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(self.project.settings.fps),
            "-frames:v",
            str(frame_count),
            str(segment),
        ]
        self._run(args, log)
        rendered.append(segment)
    self._concat_video_files(rendered, out, title_dir / "concat.txt", log)


def _patched_build_video_from_timeline(
    self: FFmpegRenderer,
    out: Path,
    work: Path,
    log=None,
) -> None:
    clip_dir = work / "visual_clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    img_items = images(self.project)
    fps = self.project.settings.fps
    for index, clip in enumerate(self.timeline.video_clips):
        clip_out = clip_dir / f"clip_{index:05d}.mp4"
        start_frame = int(round(clip.timeline_in * fps))
        end_frame = int(round(clip.timeline_out * fps))
        target_frames = max(1, end_frame - start_frame)
        if clip.kind == "image":
            if not 0 <= clip.source_index < len(img_items):
                raise RenderError(f"Foto clip {index + 1} tidak valid.")
            if log:
                log(
                    f"Foto timeline {index + 1}/{len(self.timeline.video_clips)}: "
                    f"{clip.name} selama {clip.timeline_duration:.3f}s."
                )
            _encode_image_segment(
                self, clip, img_items[clip.source_index], clip_out, log, target_frames
            )
        elif clip.direction == "reverse":
            self._build_reverse_clip(clip, clip_out, clip_dir, index, log)
        else:
            self._encode_video_segment(
                source=clip.source,
                source_in=clip.source_in,
                source_out=clip.source_out,
                speed=clip.speed,
                timeline_duration=clip.timeline_duration,
                reverse=False,
                out=clip_out,
                log=log,
                target_frames=target_frames,
            )
        files.append(clip_out)
    base = work / "visual_base.mp4"
    self._concat_video_files(files, base, work / "visual_concat.txt", log)
    _apply_title_cards(self, base, out, work, log)


def _patched_build_audio_from_timeline(self: FFmpegRenderer, out: Path, log=None) -> None:
    clips = self.timeline.audio_clips
    if not clips:
        raise RenderError("Timeline tidak memiliki audio.")
    work = out.parent / "audio_parts"
    work.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    for index, clip in enumerate(clips):
        part = work / f"part_{index:04d}.wav"
        duration = clip.timeline_duration
        args = [
            self.ffmpeg,
            "-y",
            "-ss",
            f"{clip.source_in:.6f}",
            "-t",
            f"{clip.source_out - clip.source_in:.6f}",
            "-i",
            _q(clip.source),
            "-map",
            "0:a:0",
            "-vn",
            "-af",
            "aresample=48000,aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS",
            "-t",
            f"{duration:.6f}",
            "-c:a",
            "pcm_s16le",
            str(part),
        ]
        if log:
            log(f"Normalisasi audio {index + 1}/{len(clips)}: {clip.name}")
        self._run(args, log)
        parts.append(part)

    manifest = work / "concat.txt"
    manifest.write_text(
        "\n".join(f"file '{_concat_path(path)}'" for path in parts) + "\n",
        encoding="utf-8",
    )
    args = [
        self.ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(manifest),
        "-c:a",
        "aac",
        "-b:a",
        self.project.settings.audio_bitrate,
        "-t",
        f"{self.timeline.duration:.6f}",
        str(out),
    ]
    self._run(args, log)


def _same_file(a: Path, b: Path) -> bool:
    try:
        if a.exists() and b.exists() and os.path.samefile(a, b):
            return True
    except OSError:
        pass
    return str(a.resolve()).casefold() == str(b.resolve()).casefold()


def _patched_render(
    self: FFmpegRenderer,
    destination: str | None = None,
    log=None,
) -> str:
    plan = self.timeline
    errors = validate_visual_timeline(plan, self.project)
    if errors:
        raise RenderError("Timeline berubah/tidak valid sebelum render:\n• " + "\n• ".join(errors))

    _ensure_project(self.project)
    protected_paths = [
        Path(item.path).resolve()
        for item in [*self.project.videos, *self.project.audios, *images(self.project)]
    ]
    active_paths = {
        Path(clip.source).resolve()
        for clip in [*plan.video_clips, *plan.audio_clips]
    }
    missing = [str(path) for path in active_paths if not path.exists()]
    if missing:
        preview = "\n".join(f"• {x}" for x in missing[:8])
        raise RenderError(f"File sumber timeline tidak ditemukan:\n{preview}")

    self._ensure_encoder()
    destination = destination or str(output_dir() / "FULL_ALBUM_FINAL.mp4")
    dest_path = Path(destination).resolve()
    sidecars = [
        dest_path.with_name(f"{dest_path.stem}_YouTube_Chapter.txt"),
        dest_path.with_name(f"{dest_path.stem}_Tracklist.txt"),
        dest_path.with_name(f"{dest_path.stem}_Timeline_Final.json"),
    ]
    for target in [dest_path, *sidecars]:
        if any(_same_file(target, source) for source in protected_paths):
            raise RenderError(
                "Lokasi output/sidecar tidak boleh menimpa file sumber proyek."
            )

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    fd, staged_name = tempfile.mkstemp(
        prefix=f".{dest_path.stem}.",
        suffix=f".rendering{dest_path.suffix or '.mp4'}",
        dir=str(dest_path.parent),
    )
    os.close(fd)
    staged_path = Path(staged_name)
    staged_path.unlink(missing_ok=True)
    root = temp_dir()
    try:
        with tempfile.TemporaryDirectory(prefix="fam_render_", dir=root) as work_dir:
            work = Path(work_dir)
            album_audio = work / "timeline_audio.m4a"
            timeline_video = work / "timeline_video.mp4"
            self._build_audio_from_timeline(album_audio, log)
            self._build_video_from_timeline(timeline_video, work, log)
            self._build_final(timeline_video, album_audio, str(staged_path), log)
        staged_path.replace(dest_path)
    finally:
        staged_path.unlink(missing_ok=True)

    self._write_chapters(sidecars[0])
    self._write_tracklist(sidecars[1])
    save_timeline(str(sidecars[2]), self.timeline)
    if log:
        log(f"Render selesai. Sidecar memakai prefix {dest_path.stem}_ agar tidak saling menimpa.")
    return str(dest_path)


def _patched_controller_summary(self) -> dict[str, Any]:
    summary = _originals["controller_summary"](self)
    _ensure_project(self.project)
    summary["image_count"] = len(images(self.project))
    summary["visual_settings"] = dict(visual_settings(self.project))
    summary["song_display"] = [
        {
            "position": index + 1,
            "title": display_title(item),
            "artist": display_artist(item),
            "cover": Path(str(_get_item_attr(item, "cover_path", "") or "")).name,
            "visual": Path(str(_get_item_attr(item, "visual_path", "") or "")).name,
        }
        for index, item in enumerate(self.project.audios)
    ]
    return summary


def _resolve_active_song(project: Project, position: int) -> MediaItem:
    indices = playlist_feature_module.active_audio_indices(project, strict=True)
    if not 1 <= position <= len(indices):
        raise ValueError("Posisi lagu playlist tidak valid.")
    return project.audios[indices[position - 1]]


def _resolve_image(project: Project, position: int) -> MediaItem:
    if not 1 <= position <= len(images(project)):
        raise ValueError("Posisi foto tidak valid.")
    return images(project)[position - 1]


def _patched_controller_execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
    _ensure_project(self.project)
    settings = visual_settings(self.project)
    if name == "set_visual_mode":
        mode = str(args.get("mode", "")).strip().casefold()
        if mode not in {"sequential", "per_song"}:
            raise ValueError("mode harus sequential atau per_song.")
        settings["visual_mode"] = mode
        return {"visual_mode": mode, "summary": self.summary()}
    if name == "set_photo_duration":
        seconds = float(args.get("seconds"))
        if not math.isfinite(seconds) or not 0.2 <= seconds <= 3600:
            raise ValueError("Durasi foto harus 0.2–3600 detik.")
        settings["photo_duration"] = seconds
        return {"photo_duration": seconds, "summary": self.summary()}
    if name == "set_photo_fit":
        fit = str(args.get("fit", "")).strip().casefold()
        if fit not in {"fit", "fill", "fit_blur"}:
            raise ValueError("fit harus fit, fill, atau fit_blur.")
        settings["photo_fit"] = fit
        return {"photo_fit": fit, "summary": self.summary()}
    if name == "set_photo_motion":
        motion = str(args.get("motion", "")).strip().casefold()
        if motion not in {"static", "zoom"}:
            raise ValueError("motion harus static atau zoom.")
        settings["photo_motion"] = motion
        return {"photo_motion": motion, "summary": self.summary()}
    if name == "set_title_style":
        mode = str(args.get("mode", settings["title_mode"])).strip().casefold()
        animation = str(args.get("animation", settings["title_animation"])).strip().casefold()
        if mode not in {"full", "intro6", "off"}:
            raise ValueError("mode judul harus full, intro6, atau off.")
        if animation not in {"none", "fade", "slide"}:
            raise ValueError("animasi judul harus none, fade, atau slide.")
        settings["title_mode"] = mode
        settings["title_animation"] = animation
        return {"title_mode": mode, "title_animation": animation, "summary": self.summary()}
    if name == "assign_song_cover":
        song = _resolve_active_song(self.project, int(args.get("song_position")))
        image = _resolve_image(self.project, int(args.get("image_position")))
        _set_item_attr(song, "cover_path", image.path)
        return {"cover": image.name, "summary": self.summary()}
    if name == "assign_song_visual":
        song = _resolve_active_song(self.project, int(args.get("song_position")))
        image = _resolve_image(self.project, int(args.get("image_position")))
        _set_item_attr(song, "visual_path", image.path)
        settings["visual_mode"] = "per_song"
        return {"visual": image.name, "summary": self.summary()}
    return _originals["controller_execute"](self, name, args)


def _visual_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "set_visual_mode",
            "description": "Atur visual menjadi berurutan sepanjang album atau satu visual per lagu.",
            "parameters": {
                "type": "object",
                "properties": {"mode": {"type": "string", "enum": ["sequential", "per_song"]}},
                "required": ["mode"],
            },
        },
        {
            "name": "set_photo_duration",
            "description": "Atur lama default foto pada mode visual berurutan.",
            "parameters": {
                "type": "object",
                "properties": {"seconds": {"type": "number", "minimum": 0.2, "maximum": 3600}},
                "required": ["seconds"],
            },
        },
        {
            "name": "set_photo_fit",
            "description": "Atur cara foto memenuhi frame. fit_blur adalah default aman tanpa merusak rasio.",
            "parameters": {
                "type": "object",
                "properties": {"fit": {"type": "string", "enum": ["fit_blur", "fit", "fill"]}},
                "required": ["fit"],
            },
        },
        {
            "name": "set_photo_motion",
            "description": "Atur foto diam atau zoom pelan.",
            "parameters": {
                "type": "object",
                "properties": {"motion": {"type": "string", "enum": ["static", "zoom"]}},
                "required": ["motion"],
            },
        },
        {
            "name": "set_title_style",
            "description": "Atur judul lagu di MP4 dan animasinya saat lagu berganti.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["full", "intro6", "off"]},
                    "animation": {"type": "string", "enum": ["fade", "slide", "none"]},
                },
                "required": ["mode", "animation"],
            },
        },
        {
            "name": "assign_song_cover",
            "description": "Jadikan foto Media sebagai cover kecil kartu judul untuk satu lagu playlist.",
            "parameters": {
                "type": "object",
                "properties": {
                    "song_position": {"type": "integer", "minimum": 1},
                    "image_position": {"type": "integer", "minimum": 1},
                },
                "required": ["song_position", "image_position"],
            },
        },
        {
            "name": "assign_song_visual",
            "description": "Hubungkan foto Media ke satu lagu playlist dan aktifkan mode visual per lagu.",
            "parameters": {
                "type": "object",
                "properties": {
                    "song_position": {"type": "integer", "minimum": 1},
                    "image_position": {"type": "integer", "minimum": 1},
                },
                "required": ["song_position", "image_position"],
            },
        },
    ]


def _patched_media_panel(self):
    panel = _originals["ui_media_panel"](self)
    lay = panel.layout()
    image_card = QFrame()
    image_card.setObjectName("mediaCard")
    image_lay = QVBoxLayout(image_card)
    image_lay.setContentsMargins(8, 8, 8, 8)
    image_lay.setSpacing(5)
    head = QHBoxLayout()
    title = QLabel("▧  Footage Foto")
    title.setObjectName("sectionTitle")
    add = QPushButton("+  Add Foto")
    add.setObjectName("accentButton")
    add.clicked.connect(self.add_image)
    head.addWidget(title)
    head.addStretch(1)
    head.addWidget(add)
    image_lay.addLayout(head)
    self.image_list = QListWidget()
    self.image_list.setMaximumHeight(105)
    self.image_list.setTextElideMode(Qt.ElideMiddle)
    image_lay.addWidget(self.image_list)
    buttons = QHBoxLayout()
    remove = QPushButton("Hapus Foto")
    remove.clicked.connect(self.remove_image_selected)
    buttons.addWidget(remove)
    buttons.addStretch(1)
    image_lay.addLayout(buttons)
    lay.addWidget(image_card)

    visual_card = QFrame()
    visual_card.setObjectName("mediaCard")
    grid = QGridLayout(visual_card)
    grid.setContentsMargins(8, 8, 8, 8)
    grid.setSpacing(5)
    heading = QLabel("✦  Foto + Judul Lagu")
    heading.setObjectName("sectionTitle")
    grid.addWidget(heading, 0, 0, 1, 2)

    self.visual_mode_combo = QComboBox()
    self.visual_mode_combo.addItem("Berurutan", "sequential")
    self.visual_mode_combo.addItem("Satu per Lagu", "per_song")
    self.photo_fit_combo = QComboBox()
    self.photo_fit_combo.addItem("Fit + Blur", "fit_blur")
    self.photo_fit_combo.addItem("Fit", "fit")
    self.photo_fit_combo.addItem("Fill", "fill")
    self.photo_motion_combo = QComboBox()
    self.photo_motion_combo.addItem("Zoom Pelan", "zoom")
    self.photo_motion_combo.addItem("Diam", "static")
    self.photo_duration_spin = QDoubleSpinBox()
    self.photo_duration_spin.setRange(0.2, 3600.0)
    self.photo_duration_spin.setValue(10.0)
    self.photo_duration_spin.setSuffix(" dtk")
    self.title_mode_combo = QComboBox()
    self.title_mode_combo.addItem("Sepanjang Lagu", "full")
    self.title_mode_combo.addItem("6 Detik Awal", "intro6")
    self.title_mode_combo.addItem("Judul Mati", "off")
    self.title_animation_combo = QComboBox()
    self.title_animation_combo.addItem("Fade", "fade")
    self.title_animation_combo.addItem("Geser Halus", "slide")
    self.title_animation_combo.addItem("Tanpa Animasi", "none")

    for row, (label, widget) in enumerate(
        [
            ("Mode Visual", self.visual_mode_combo),
            ("Fit Foto", self.photo_fit_combo),
            ("Gerak Foto", self.photo_motion_combo),
            ("Durasi Foto", self.photo_duration_spin),
            ("Judul", self.title_mode_combo),
            ("Animasi Ganti Lagu", self.title_animation_combo),
        ],
        start=1,
    ):
        grid.addWidget(QLabel(label), row, 0)
        grid.addWidget(widget, row, 1)
        widget.currentIndexChanged.connect(self.apply_visual_settings) if isinstance(widget, QComboBox) else widget.valueChanged.connect(self.apply_visual_settings)
    lay.addWidget(visual_card)
    return panel


def _patched_add_video(self):
    before = {_path_key(item.path) for item in self.project.videos}
    _originals["ui_add_video"](self)
    _ensure_project(self.project)
    order = getattr(self.project, "_visual_order")
    for item in self.project.videos:
        key = _path_key(item.path)
        if key not in before and not any(_path_key(x) == key for x in order):
            order.append(item.path)


def _patched_add_audio(self):
    _originals["ui_add_audio"](self)
    _enrich_audio_metadata(self.project)
    self.invalidate_timeline()
    self.refresh()


def _add_image(self):
    paths, _ = QFileDialog.getOpenFileNames(
        self,
        "Pilih Foto Footage",
        "",
        "Foto (*.jpg *.jpeg *.png *.webp)",
    )
    if not paths:
        return
    _ensure_project(self.project)
    target = images(self.project)
    existing = {_path_key(item.path) for item in target}
    order = getattr(self.project, "_visual_order")
    for path in paths:
        key = _path_key(path)
        if key in existing:
            continue
        try:
            info = probe_image(path)
            item = MediaItem(path=path, duration=0.0)
            _set_item_attr(item, "width", info["width"])
            _set_item_attr(item, "height", info["height"])
            target.append(item)
            existing.add(key)
            if not any(_path_key(x) == key for x in order):
                order.append(path)
        except MediaProbeError as exc:
            self._error(str(exc))
    self.invalidate_timeline()
    self.refresh()


def _remove_image_selected(self):
    row = self.image_list.currentRow() if hasattr(self, "image_list") else -1
    if not 0 <= row < len(images(self.project)):
        return
    item = images(self.project).pop(row)
    key = _path_key(item.path)
    setattr(
        self.project,
        "_visual_order",
        [path for path in getattr(self.project, "_visual_order", []) if _path_key(path) != key],
    )
    for audio in self.project.audios:
        cover_path = str(_get_item_attr(audio, "cover_path", "") or "")
        visual_path = str(_get_item_attr(audio, "visual_path", "") or "")
        if cover_path and _path_key(cover_path) == key:
            _set_item_attr(audio, "cover_path", "")
        if visual_path and _path_key(visual_path) == key:
            _set_item_attr(audio, "visual_path", "")
    self.invalidate_timeline()
    self.refresh()


def _apply_visual_settings(self, *_):
    config = visual_settings(self.project)
    config["visual_mode"] = self.visual_mode_combo.currentData()
    config["photo_fit"] = self.photo_fit_combo.currentData()
    config["photo_motion"] = self.photo_motion_combo.currentData()
    config["photo_duration"] = float(self.photo_duration_spin.value())
    config["title_mode"] = self.title_mode_combo.currentData()
    config["title_animation"] = self.title_animation_combo.currentData()
    _validate_visual_settings(config)
    self.invalidate_timeline()
    self.refresh()


def _patched_sync_controls(self):
    _originals["ui_sync_controls"](self)
    if not hasattr(self, "visual_mode_combo"):
        return
    config = visual_settings(self.project)
    controls = [
        self.visual_mode_combo,
        self.photo_fit_combo,
        self.photo_motion_combo,
        self.photo_duration_spin,
        self.title_mode_combo,
        self.title_animation_combo,
    ]
    for control in controls:
        control.blockSignals(True)
    try:
        for combo, key in [
            (self.visual_mode_combo, "visual_mode"),
            (self.photo_fit_combo, "photo_fit"),
            (self.photo_motion_combo, "photo_motion"),
            (self.title_mode_combo, "title_mode"),
            (self.title_animation_combo, "title_animation"),
        ]:
            index = combo.findData(config[key])
            if index >= 0:
                combo.setCurrentIndex(index)
        self.photo_duration_spin.setValue(float(config["photo_duration"]))
    finally:
        for control in controls:
            control.blockSignals(False)


def _patched_refresh(self):
    _originals["ui_refresh"](self)
    _ensure_project(self.project)
    if hasattr(self, "image_list"):
        self.image_list.clear()
        for index, item in enumerate(images(self.project), start=1):
            width = int(_get_item_attr(item, "width", 0) or 0)
            height = int(_get_item_attr(item, "height", 0) or 0)
            self.image_list.addItem(f"▧  {index:02d}  {item.name}  •  {width}×{height}")
    if hasattr(self, "video_total") and images(self.project):
        self.video_total.setText(
            f"▣ Video {len(self.project.videos)}  •  ▧ Foto {len(images(self.project))}  •  kapasitas visual {ui_module.fmt(self.project.adjusted_video_duration())}"
        )


def _patched_auto_build_timeline(self):
    _ensure_project(self.project)
    if not self.project.videos and not images(self.project):
        self._error("Tambahkan minimal satu visual video atau foto sebelum Auto Susun Timeline.")
        return
    if not self.project.audios:
        self._error("Tambahkan minimal satu lagu sebelum Auto Susun Timeline.")
        return
    self.auto_timeline_btn.setEnabled(False)
    self.regenerate_btn.setEnabled(False)
    self.auto_timeline_btn.setText("⚙  MENYUSUN TIMELINE…\nEngine lokal menghitung video, foto, lagu, judul, cut, dan loop")
    try:
        plan = VisualPlaylistTimelineEngine().build(self.project)
        timeline_path = save_timeline(str(output_dir() / "Timeline_Auto.json"), plan)
        self.timeline_file_path = timeline_path
        self.apply_timeline_plan(plan)
        self.chat.appendPlainText(
            "\nAPP\nAUTO TIMELINE SELESAI\n"
            f"Durasi final: {ui_module.fmt(plan.duration)}\n"
            f"Visual clips: {len(plan.video_clips)}\n"
            f"Audio clips: {len(plan.audio_clips)}\n"
            f"Foto Media: {len(images(self.project))}\n"
            f"Judul: {visual_settings(self.project)['title_mode']} / {visual_settings(self.project)['title_animation']}\n"
            f"JSON: {timeline_path}\n"
        )
    except Exception as exc:
        self.invalidate_timeline()
        self.refresh()
        self._error(f"Auto Timeline gagal:\n\n{exc}")
    finally:
        self.auto_timeline_btn.setEnabled(True)
        self.regenerate_btn.setEnabled(True)
        self.auto_timeline_btn.setText(
            "⚡  AUTO SUSUN TIMELINE\nAnalisis footage + album dan buat timeline otomatis"
        )


def _updated_system(system: str) -> str:
    return system.rstrip() + """

FITUR FOTO, JUDUL, DAN PERGANTIAN LAGU:
- Foto JPG/JPEG/PNG/WebP statis dapat menjadi footage. Jangan menganggap foto terkena slowmo video.
- Untuk satu foto per lagu, gunakan set_visual_mode(mode='per_song'). Engine lokal akan memetakan foto Media berurutan dan mengulang bila foto lebih sedikit.
- Gunakan set_photo_motion('zoom') untuk zoom pelan; set_photo_fit('fit_blur') adalah default aman tanpa merusak rasio.
- Judul lagu dirender lokal dari metadata/filename. Gunakan set_title_style. Default: sepanjang lagu + fade.
- assign_song_cover memasang foto kecil pada kartu judul; assign_song_visual memasang foto sebagai latar lagu tertentu.
- Animasi judul tidak boleh mengubah, memotong, mempercepat, atau crossfade audio.
- Jika pengguna meminta: 'pakai foto satu per lagu, zoom pelan, judul kiri bawah fade, lalu render', terjemahkan menjadi aksi visual yang sesuai, lalu auto_build_timeline dan render_timeline.
"""


def install_visual_feature() -> None:
    global _installed
    if _installed:
        return
    ProjectClass = Project
    MainWindow = ui_module.MainWindow

    _originals.update(
        {
            "project_to_dict": ProjectClass.to_dict,
            "project_from_dict_descriptor": ProjectClass.__dict__["from_dict"],
            "project_from_dict_bound": ProjectClass.from_dict,
            "project_validation": ProjectClass.validation,
            "project_planned_speed": ProjectClass.planned_speed,
            "project_adjusted_duration": ProjectClass.adjusted_video_duration,
            "project_needs_loop": ProjectClass.needs_loop,
            "project_signature": timeline_module.project_signature,
            "plan_validate": TimelinePlan.validate,
            "timeline_validate_project": timeline_module.validate_timeline_against_project,
            "renderer_validate_project": renderer_module.validate_timeline_against_project,
            "renderer_build_video": FFmpegRenderer._build_video_from_timeline,
            "renderer_build_audio": FFmpegRenderer._build_audio_from_timeline,
            "renderer_encode_video": FFmpegRenderer._encode_video_segment,
            "renderer_render": FFmpegRenderer.render,
            "controller_summary": playlist_feature_module.ProjectController.summary,
            "controller_execute": playlist_feature_module.ProjectController.execute,
            "ui_media_panel": MainWindow._media_panel,
            "ui_add_video": MainWindow.add_video,
            "ui_add_audio": MainWindow.add_audio,
            "ui_sync_controls": MainWindow._sync_controls_from_project,
            "ui_refresh": MainWindow.refresh,
            "ui_auto_build": MainWindow.auto_build_timeline,
            "ui_project_signature": ui_module.project_signature,
            "ui_timeline_engine": ui_module.TimelineEngine,
            "agent_timeline_engine": agent_actions_module.TimelineEngine,
            "playlist_engine": playlist_feature_module.PlaylistTimelineEngine,
            "playlist_signature": playlist_feature_module.playlist_project_signature,
            "hardening_signature": playlist_hardening_module.playlist_project_signature,
            "gemini_system": gemini_agent_module.SYSTEM,
            "gemini_tools": gemini_agent_module.TOOLS,
        }
    )

    ProjectClass.to_dict = _patched_project_to_dict
    ProjectClass.from_dict = classmethod(_patched_project_from_dict)
    ProjectClass.validation = _patched_validation
    ProjectClass.planned_speed = _patched_planned_speed
    ProjectClass.adjusted_video_duration = _patched_adjusted_visual_duration
    ProjectClass.needs_loop = _patched_needs_loop

    TimelinePlan.validate = _patched_plan_validate
    timeline_module.project_signature = visual_project_signature
    timeline_module.validate_timeline_against_project = validate_visual_timeline
    renderer_module.validate_timeline_against_project = validate_visual_timeline
    ui_module.project_signature = visual_project_signature

    playlist_feature_module.playlist_project_signature = visual_project_signature
    playlist_hardening_module.playlist_project_signature = visual_project_signature
    playlist_feature_module.PlaylistTimelineEngine = VisualPlaylistTimelineEngine
    ui_module.TimelineEngine = VisualPlaylistTimelineEngine
    agent_actions_module.TimelineEngine = VisualPlaylistTimelineEngine

    FFmpegRenderer._build_video_from_timeline = _patched_build_video_from_timeline
    FFmpegRenderer._build_audio_from_timeline = _patched_build_audio_from_timeline
    FFmpegRenderer._encode_video_segment = _patched_encode_video_segment
    FFmpegRenderer.render = _patched_render

    agent_actions_module.ALLOWED_ACTIONS.update(VISUAL_ACTIONS)
    playlist_feature_module.ProjectController.summary = _patched_controller_summary
    playlist_feature_module.ProjectController.execute = _patched_controller_execute

    gemini_agent_module.SYSTEM = _updated_system(gemini_agent_module.SYSTEM)
    gemini_agent_module.TOOLS = list(gemini_agent_module.TOOLS) + _visual_tools()

    MainWindow._media_panel = _patched_media_panel
    MainWindow.add_video = _patched_add_video
    MainWindow.add_audio = _patched_add_audio
    MainWindow.add_image = _add_image
    MainWindow.remove_image_selected = _remove_image_selected
    MainWindow.apply_visual_settings = _apply_visual_settings
    MainWindow._sync_controls_from_project = _patched_sync_controls
    MainWindow.refresh = _patched_refresh
    MainWindow.auto_build_timeline = _patched_auto_build_timeline

    _installed = True


def uninstall_visual_feature() -> None:
    global _installed
    if not _installed:
        return
    Project.to_dict = _originals["project_to_dict"]
    Project.from_dict = _originals["project_from_dict_descriptor"]
    Project.validation = _originals["project_validation"]
    Project.planned_speed = _originals["project_planned_speed"]
    Project.adjusted_video_duration = _originals["project_adjusted_duration"]
    Project.needs_loop = _originals["project_needs_loop"]
    TimelinePlan.validate = _originals["plan_validate"]
    timeline_module.project_signature = _originals["project_signature"]
    timeline_module.validate_timeline_against_project = _originals["timeline_validate_project"]
    renderer_module.validate_timeline_against_project = _originals["renderer_validate_project"]
    FFmpegRenderer._build_video_from_timeline = _originals["renderer_build_video"]
    FFmpegRenderer._build_audio_from_timeline = _originals["renderer_build_audio"]
    FFmpegRenderer._encode_video_segment = _originals["renderer_encode_video"]
    FFmpegRenderer.render = _originals["renderer_render"]
    playlist_feature_module.ProjectController.summary = _originals["controller_summary"]
    playlist_feature_module.ProjectController.execute = _originals["controller_execute"]
    for action in VISUAL_ACTIONS:
        agent_actions_module.ALLOWED_ACTIONS.discard(action)
    playlist_feature_module.PlaylistTimelineEngine = _originals["playlist_engine"]
    playlist_feature_module.playlist_project_signature = _originals["playlist_signature"]
    playlist_hardening_module.playlist_project_signature = _originals["hardening_signature"]
    ui_module.project_signature = _originals["ui_project_signature"]
    ui_module.TimelineEngine = _originals["ui_timeline_engine"]
    agent_actions_module.TimelineEngine = _originals["agent_timeline_engine"]
    gemini_agent_module.SYSTEM = _originals["gemini_system"]
    gemini_agent_module.TOOLS = _originals["gemini_tools"]
    MainWindow = ui_module.MainWindow
    MainWindow._media_panel = _originals["ui_media_panel"]
    MainWindow.add_video = _originals["ui_add_video"]
    MainWindow.add_audio = _originals["ui_add_audio"]
    MainWindow._sync_controls_from_project = _originals["ui_sync_controls"]
    MainWindow.refresh = _originals["ui_refresh"]
    MainWindow.auto_build_timeline = _originals["ui_auto_build"]
    for name in ("add_image", "remove_image_selected", "apply_visual_settings"):
        if hasattr(MainWindow, name):
            delattr(MainWindow, name)
    _originals.clear()
    _installed = False
