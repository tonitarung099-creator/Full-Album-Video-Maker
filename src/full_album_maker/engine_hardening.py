from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from . import playlist_feature as playlist_feature_module
from . import timeline as timeline_module
from . import visual_feature as visual_feature_module
from .project import Project
from .timeline import (
    EPSILON,
    MAX_TIMELINE_CLIPS,
    AudioTimelineClip,
    ClipKind,
    Direction,
    TimelineError,
    TimelinePlan,
    VideoTimelineClip,
)

_installed = False
_originals: dict[str, Any] = {}


def _patched_needs_loop(self: Project) -> bool:
    return self.adjusted_video_duration() + EPSILON < self.total_audio_duration


def _selected_audio_items(project: Project):
    try:
        if playlist_feature_module.get_active_audio_paths(project):
            return playlist_feature_module.active_audio_items(project, strict=False)
    except Exception:
        pass
    return list(project.audios)


def _patched_validation(self: Project) -> dict[str, list[str]]:
    report = _originals["project_validation"](self)
    errors = list(report.get("errors", []))
    warnings = list(report.get("warnings", []))

    def add(message: str) -> None:
        if message not in errors:
            errors.append(message)

    settings = self.settings
    numeric_settings = (
        ("manual_speed", settings.manual_speed, 0.05, 2.0),
        ("min_speed", settings.min_speed, 0.05, 1.0),
    )
    for label, value, low, high in numeric_settings:
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or not low <= float(value) <= high
        ):
            add(f"Setting {label} tidak valid.")

    if settings.loop_mode not in {"auto", "loop", "pingpong", "none"}:
        add("Setting loop_mode tidak valid.")
    if (
        not isinstance(settings.width, int)
        or isinstance(settings.width, bool)
        or not 320 <= settings.width <= 7680
        or settings.width % 2
        or not isinstance(settings.height, int)
        or isinstance(settings.height, bool)
        or not 240 <= settings.height <= 4320
        or settings.height % 2
    ):
        add("Resolusi proyek tidak valid.")
    if settings.fps not in {24, 25, 30, 50, 60}:
        add("FPS proyek tidak valid.")
    if settings.codec not in {"h264", "h265"}:
        add("Codec proyek tidak valid.")
    if settings.video_bitrate not in {"6M", "8M", "12M", "20M", "30M", "45M", "60M"}:
        add("Video bitrate proyek tidak valid.")
    if settings.audio_bitrate not in {"128k", "192k", "256k", "320k"}:
        add("Audio bitrate proyek tidak valid.")

    use_video_items = True
    try:
        config = visual_feature_module.visual_settings(self)
        if config.get("visual_mode") == "per_song" and visual_feature_module.images(self):
            use_video_items = False
    except Exception:
        pass

    if use_video_items:
        for item in self.videos:
            if (
                not isinstance(item.duration, (int, float))
                or isinstance(item.duration, bool)
                or not math.isfinite(float(item.duration))
                or float(item.duration) <= 0
            ):
                add(f"Durasi footage tidak valid: {item.name}")

    for item in _selected_audio_items(self):
        if (
            not isinstance(item.duration, (int, float))
            or isinstance(item.duration, bool)
            or not math.isfinite(float(item.duration))
            or float(item.duration) <= 0
        ):
            add(f"Durasi lagu tidak valid: {item.name}")

    if self.audios and self.total_audio_duration > 0 and self.needs_loop() and settings.loop_mode == "none":
        add("Footage terlalu pendek tetapi mode loop dimatikan.")

    report["errors"] = errors
    report["warnings"] = list(dict.fromkeys(warnings))
    return report


def _patched_plan_validate(self: TimelinePlan) -> list[str]:
    errors = list(_originals["plan_validate"](self))
    if len(self.video_clips) > MAX_TIMELINE_CLIPS:
        errors.append(
            f"Timeline memiliki {len(self.video_clips)} clip visual; batasnya {MAX_TIMELINE_CLIPS}."
        )
    if len(self.audio_clips) > MAX_TIMELINE_CLIPS:
        errors.append(
            f"Timeline memiliki {len(self.audio_clips)} clip audio; batasnya {MAX_TIMELINE_CLIPS}."
        )
    return errors


def _patched_build_audio_track(project: Project) -> list[AudioTimelineClip]:
    if len(project.audios) > MAX_TIMELINE_CLIPS:
        raise TimelineError(
            f"Album memiliki {len(project.audios)} lagu; batas timeline adalah {MAX_TIMELINE_CLIPS}."
        )
    return _originals["timeline_build_audio"](project)


def _patched_append_cycle(
    *,
    clips: list[VideoTimelineClip],
    project: Project,
    cursor: float,
    timeline_end: float,
    speed: float,
    cycle: int,
    direction: Direction,
    kind: ClipKind,
) -> float:
    indexed = list(enumerate(project.videos))
    if direction == "reverse":
        indexed.reverse()

    for source_index, item in indexed:
        if cursor >= timeline_end - EPSILON:
            break
        if len(clips) >= MAX_TIMELINE_CLIPS:
            raise TimelineError(
                f"Timeline membutuhkan lebih dari {MAX_TIMELINE_CLIPS} clip visual. "
                "Gunakan footage yang lebih panjang atau kurangi jumlah media."
            )

        full_timeline_duration = item.duration / speed
        remaining = timeline_end - cursor
        used_timeline_duration = min(full_timeline_duration, remaining)
        used_source_duration = used_timeline_duration * speed

        if direction == "reverse":
            source_out = item.duration
            source_in = max(0.0, source_out - used_source_duration)
        else:
            source_in = 0.0
            source_out = min(item.duration, used_source_duration)

        timeline_out = min(timeline_end, cursor + used_timeline_duration)
        clips.append(
            VideoTimelineClip(
                source=item.path,
                source_index=source_index,
                name=Path(item.path).stem,
                source_in=source_in,
                source_out=source_out,
                timeline_in=cursor,
                timeline_out=timeline_out,
                speed=speed,
                direction=direction,
                kind=kind,
                cycle=cycle,
            )
        )
        cursor = timeline_out
    return cursor


def _patched_visual_audio_track(project: Project) -> list[AudioTimelineClip]:
    indices = playlist_feature_module.active_audio_indices(project, strict=True)
    if len(indices) > MAX_TIMELINE_CLIPS:
        raise TimelineError(
            f"Playlist aktif memiliki {len(indices)} lagu; batas timeline adalah {MAX_TIMELINE_CLIPS}."
        )
    return _originals["visual_build_audio"](project)


def install_engine_hardening() -> None:
    global _installed
    if _installed:
        return

    VisualEngine = visual_feature_module.VisualPlaylistTimelineEngine
    _originals.update(
        {
            "project_validation": Project.validation,
            "project_needs_loop": Project.needs_loop,
            "plan_validate": TimelinePlan.validate,
            "timeline_build_audio": timeline_module.TimelineEngine._build_audio_track,
            "timeline_append_cycle": timeline_module.TimelineEngine._append_cycle,
            "visual_build_audio": VisualEngine._build_audio_track,
        }
    )

    Project.validation = _patched_validation
    Project.needs_loop = _patched_needs_loop
    TimelinePlan.validate = _patched_plan_validate
    timeline_module.TimelineEngine._build_audio_track = staticmethod(_patched_build_audio_track)
    timeline_module.TimelineEngine._append_cycle = staticmethod(_patched_append_cycle)
    VisualEngine._build_audio_track = staticmethod(_patched_visual_audio_track)
    _installed = True


def uninstall_engine_hardening() -> None:
    global _installed
    if not _installed:
        return
    VisualEngine = visual_feature_module.VisualPlaylistTimelineEngine
    Project.validation = _originals["project_validation"]
    Project.needs_loop = _originals["project_needs_loop"]
    TimelinePlan.validate = _originals["plan_validate"]
    timeline_module.TimelineEngine._build_audio_track = _originals["timeline_build_audio"]
    timeline_module.TimelineEngine._append_cycle = _originals["timeline_append_cycle"]
    VisualEngine._build_audio_track = _originals["visual_build_audio"]
    _originals.clear()
    _installed = False
