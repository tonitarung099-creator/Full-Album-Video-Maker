from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from .project import Project

EPSILON = 1e-6
MAX_TIMELINE_CLIPS = 10_000


class TimelineError(ValueError):
    pass


Direction = Literal["forward", "reverse"]
ClipKind = Literal["source", "loop", "pingpong"]


@dataclass
class AudioTimelineClip:
    source: str
    source_index: int
    name: str
    source_in: float
    source_out: float
    timeline_in: float
    timeline_out: float

    @property
    def timeline_duration(self) -> float:
        return self.timeline_out - self.timeline_in


@dataclass
class VideoTimelineClip:
    source: str
    source_index: int
    name: str
    source_in: float
    source_out: float
    timeline_in: float
    timeline_out: float
    speed: float
    direction: Direction = "forward"
    kind: ClipKind = "source"
    cycle: int = 0

    @property
    def source_duration(self) -> float:
        return self.source_out - self.source_in

    @property
    def timeline_duration(self) -> float:
        return self.timeline_out - self.timeline_in


@dataclass
class TimelinePlan:
    version: int = 1
    duration: float = 0.0
    planned_speed: float = 1.0
    source_video_duration: float = 0.0
    adjusted_video_duration: float = 0.0
    auto_cut_seconds: float = 0.0
    loop_fill_seconds: float = 0.0
    loop_mode: str = "none"
    project_signature: str = ""
    video_clips: list[VideoTimelineClip] = field(default_factory=list)
    audio_clips: list[AudioTimelineClip] = field(default_factory=list)

    @property
    def needs_loop(self) -> bool:
        return self.loop_fill_seconds > EPSILON

    @property
    def video_duration(self) -> float:
        if not self.video_clips:
            return 0.0
        return self.video_clips[-1].timeline_out

    @property
    def audio_duration(self) -> float:
        if not self.audio_clips:
            return 0.0
        return self.audio_clips[-1].timeline_out

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.duration <= 0:
            errors.append("Durasi timeline harus lebih dari 0.")
        if self.planned_speed <= 0:
            errors.append("Speed timeline harus lebih dari 0.")
        if not self.video_clips:
            errors.append("Timeline tidak memiliki clip video.")
        if not self.audio_clips:
            errors.append("Timeline tidak memiliki clip audio.")

        def check_contiguous(clips: list[Any], label: str) -> None:
            expected = 0.0
            for index, clip in enumerate(clips):
                if clip.timeline_out <= clip.timeline_in:
                    errors.append(f"{label} clip {index + 1} memiliki durasi tidak valid.")
                if abs(clip.timeline_in - expected) > 0.002:
                    errors.append(f"{label} clip {index + 1} tidak sambung dengan clip sebelumnya.")
                if clip.source_out <= clip.source_in:
                    errors.append(f"{label} clip {index + 1} memiliki source range tidak valid.")
                expected = clip.timeline_out

        check_contiguous(self.video_clips, "Video")
        check_contiguous(self.audio_clips, "Audio")

        if self.video_clips and abs(self.video_duration - self.duration) > 0.002:
            errors.append("Track video tidak menutup durasi timeline.")
        if self.audio_clips and abs(self.audio_duration - self.duration) > 0.002:
            errors.append("Track audio tidak menutup durasi timeline.")

        for index, clip in enumerate(self.video_clips):
            expected = clip.source_duration / clip.speed
            if abs(expected - clip.timeline_duration) > 0.003:
                errors.append(f"Video clip {index + 1} memiliki mapping speed yang tidak konsisten.")

        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "duration": self.duration,
            "planned_speed": self.planned_speed,
            "source_video_duration": self.source_video_duration,
            "adjusted_video_duration": self.adjusted_video_duration,
            "auto_cut_seconds": self.auto_cut_seconds,
            "loop_fill_seconds": self.loop_fill_seconds,
            "loop_mode": self.loop_mode,
            "project_signature": self.project_signature,
            "video_clips": [asdict(x) for x in self.video_clips],
            "audio_clips": [asdict(x) for x in self.audio_clips],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TimelinePlan":
        if int(data.get("version", 1)) != 1:
            raise TimelineError("Versi Timeline JSON belum didukung.")
        plan = cls(
            version=1,
            duration=float(data.get("duration", 0.0)),
            planned_speed=float(data.get("planned_speed", 1.0)),
            source_video_duration=float(data.get("source_video_duration", 0.0)),
            adjusted_video_duration=float(data.get("adjusted_video_duration", 0.0)),
            auto_cut_seconds=float(data.get("auto_cut_seconds", 0.0)),
            loop_fill_seconds=float(data.get("loop_fill_seconds", 0.0)),
            loop_mode=str(data.get("loop_mode", "none")),
            project_signature=str(data.get("project_signature", "")),
            video_clips=[VideoTimelineClip(**x) for x in data.get("video_clips", [])],
            audio_clips=[AudioTimelineClip(**x) for x in data.get("audio_clips", [])],
        )
        errors = plan.validate()
        if errors:
            raise TimelineError("Timeline JSON tidak valid: " + " ".join(errors))
        return plan


def project_signature(project: Project) -> str:
    payload = {
        "videos": [{"path": x.path, "duration": round(float(x.duration), 6)} for x in project.videos],
        "audios": [{"path": x.path, "duration": round(float(x.duration), 6)} for x in project.audios],
        "settings": {
            "auto_speed": project.settings.auto_speed,
            "manual_speed": round(float(project.settings.manual_speed), 8),
            "min_speed": round(float(project.settings.min_speed), 8),
            "loop_mode": project.settings.loop_mode,
            "width": project.settings.width,
            "height": project.settings.height,
            "fps": project.settings.fps,
            "codec": project.settings.codec,
            "video_bitrate": project.settings.video_bitrate,
            "audio_bitrate": project.settings.audio_bitrate,
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def timeline_matches_project(plan: TimelinePlan, project: Project) -> bool:
    return bool(plan.project_signature) and plan.project_signature == project_signature(project)


def validate_timeline_against_project(
    plan: TimelinePlan,
    project: Project,
) -> list[str]:
    errors = list(plan.validate())

    if not timeline_matches_project(plan, project):
        errors.append("Timeline tidak cocok dengan proyek atau setting saat ini.")
        return errors

    for index, clip in enumerate(plan.video_clips):
        if not 0 <= clip.source_index < len(project.videos):
            errors.append(f"Video clip {index + 1} menunjuk source_index yang tidak valid.")
            continue
        source = project.videos[clip.source_index]
        if Path(clip.source) != Path(source.path):
            errors.append(f"Video clip {index + 1} tidak cocok dengan source proyek.")
        if clip.source_in < -0.002 or clip.source_out > source.duration + 0.002:
            errors.append(f"Video clip {index + 1} melewati batas durasi source.")
        if clip.direction not in {"forward", "reverse"}:
            errors.append(f"Video clip {index + 1} memiliki arah yang tidak valid.")
        if clip.kind not in {"source", "loop", "pingpong"}:
            errors.append(f"Video clip {index + 1} memiliki jenis yang tidak valid.")

    for index, clip in enumerate(plan.audio_clips):
        if not 0 <= clip.source_index < len(project.audios):
            errors.append(f"Audio clip {index + 1} menunjuk source_index yang tidak valid.")
            continue
        source = project.audios[clip.source_index]
        if Path(clip.source) != Path(source.path):
            errors.append(f"Audio clip {index + 1} tidak cocok dengan source proyek.")
        if clip.source_in < -0.002 or clip.source_out > source.duration + 0.002:
            errors.append(f"Audio clip {index + 1} melewati batas durasi source.")
        if abs((clip.source_out - clip.source_in) - clip.timeline_duration) > 0.003:
            errors.append(f"Audio clip {index + 1} memiliki mapping durasi yang tidak konsisten.")

    return errors


class TimelineEngine:
    """Pure local engine. No Gemini and no FFmpeg are used here."""

    def build(self, project: Project) -> TimelinePlan:
        self._validate_project_for_timeline(project)

        album_duration = project.total_audio_duration
        speed = project.planned_speed()
        adjusted_duration = project.total_video_duration / speed
        auto_cut = max(0.0, adjusted_duration - album_duration)
        loop_fill = max(0.0, album_duration - adjusted_duration)

        mode = project.settings.loop_mode
        if mode == "auto":
            mode = "loop" if loop_fill > EPSILON else "none"
        if loop_fill <= EPSILON:
            mode = "none"
        if loop_fill > EPSILON and mode == "none":
            raise TimelineError(
                "Footage lebih pendek dari album tetapi mode loop dimatikan."
            )

        plan = TimelinePlan(
            duration=album_duration,
            planned_speed=speed,
            source_video_duration=project.total_video_duration,
            adjusted_video_duration=adjusted_duration,
            auto_cut_seconds=auto_cut,
            loop_fill_seconds=loop_fill,
            loop_mode=mode,
            project_signature=project_signature(project),
        )
        plan.audio_clips = self._build_audio_track(project)
        plan.video_clips = self._build_video_track(project, plan)

        errors = plan.validate()
        if errors:
            raise TimelineError("Timeline gagal divalidasi: " + " ".join(errors))
        return plan

    @staticmethod
    def _validate_project_for_timeline(project: Project) -> None:
        if not project.videos:
            raise TimelineError("Belum ada footage video.")
        if not project.audios:
            raise TimelineError("Belum ada lagu.")
        if project.total_video_duration <= 0:
            raise TimelineError("Durasi footage tidak valid.")
        if project.total_audio_duration <= 0:
            raise TimelineError("Durasi album tidak valid.")
        if project.planned_speed() <= 0:
            raise TimelineError("Speed video tidak valid.")
        for item in project.videos:
            if item.duration <= 0:
                raise TimelineError(f"Durasi footage tidak valid: {item.name}")
        for item in project.audios:
            if item.duration <= 0:
                raise TimelineError(f"Durasi lagu tidak valid: {item.name}")

    @staticmethod
    def _build_audio_track(project: Project) -> list[AudioTimelineClip]:
        clips: list[AudioTimelineClip] = []
        cursor = 0.0
        for index, item in enumerate(project.audios):
            end = cursor + item.duration
            clips.append(
                AudioTimelineClip(
                    source=item.path,
                    source_index=index,
                    name=Path(item.path).stem,
                    source_in=0.0,
                    source_out=item.duration,
                    timeline_in=cursor,
                    timeline_out=end,
                )
            )
            cursor = end
        return clips

    def _build_video_track(
        self,
        project: Project,
        plan: TimelinePlan,
    ) -> list[VideoTimelineClip]:
        clips: list[VideoTimelineClip] = []
        cursor = 0.0

        cursor = self._append_cycle(
            clips=clips,
            project=project,
            cursor=cursor,
            timeline_end=plan.duration,
            speed=plan.planned_speed,
            cycle=0,
            direction="forward",
            kind="source",
        )

        if cursor >= plan.duration - EPSILON:
            return clips

        if plan.loop_mode not in {"loop", "pingpong"}:
            raise TimelineError("Timeline video belum menutup durasi album.")

        cycle = 1
        while cursor < plan.duration - EPSILON:
            if len(clips) >= MAX_TIMELINE_CLIPS:
                raise TimelineError(
                    "Timeline membutuhkan terlalu banyak clip loop. Gunakan footage yang lebih panjang."
                )

            if plan.loop_mode == "pingpong" and cycle % 2 == 1:
                direction: Direction = "reverse"
                kind: ClipKind = "pingpong"
            elif plan.loop_mode == "pingpong":
                direction = "forward"
                kind = "pingpong"
            else:
                direction = "forward"
                kind = "loop"

            before = cursor
            cursor = self._append_cycle(
                clips=clips,
                project=project,
                cursor=cursor,
                timeline_end=plan.duration,
                speed=plan.planned_speed,
                cycle=cycle,
                direction=direction,
                kind=kind,
            )
            if cursor <= before + EPSILON:
                raise TimelineError("Loop timeline tidak dapat menambah durasi.")
            cycle += 1

        return clips

    @staticmethod
    def _append_cycle(
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


def save_timeline(path: str, plan: TimelinePlan) -> str:
    target = Path(path)
    if target.suffix.lower() != ".json":
        target = target.with_suffix(".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(target)


def load_timeline(path: str) -> TimelinePlan:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TimelineError("Format Timeline JSON tidak valid.")
    return TimelinePlan.from_dict(data)
