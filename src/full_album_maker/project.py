from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

@dataclass
class MediaItem:
    path: str
    duration: float = 0.0

    @property
    def name(self) -> str:
        return Path(self.path).name

@dataclass
class ProjectSettings:
    auto_speed: bool = True
    manual_speed: float = 1.0
    min_speed: float = 0.50
    loop_mode: str = "auto"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    codec: str = "h264"
    video_bitrate: str = "12M"
    audio_bitrate: str = "320k"

@dataclass
class Project:
    videos: list[MediaItem] = field(default_factory=list)
    audios: list[MediaItem] = field(default_factory=list)
    settings: ProjectSettings = field(default_factory=ProjectSettings)

    @property
    def total_video_duration(self) -> float:
        return sum(max(0.0, x.duration) for x in self.videos)

    @property
    def total_audio_duration(self) -> float:
        return sum(max(0.0, x.duration) for x in self.audios)

    def planned_speed(self) -> float:
        video = self.total_video_duration
        album = self.total_audio_duration
        if not self.settings.auto_speed:
            return max(0.01, self.settings.manual_speed)
        if video <= 0 or album <= 0:
            return 1.0
        desired = video / album
        if desired >= 1.0:
            return 1.0
        return max(self.settings.min_speed, desired)

    def adjusted_video_duration(self) -> float:
        speed = self.planned_speed()
        return self.total_video_duration / speed if speed > 0 else 0.0

    def needs_loop(self) -> bool:
        return self.adjusted_video_duration() + 0.05 < self.total_audio_duration

    def sort_audio_by_name(self) -> None:
        self.audios.sort(key=lambda x: x.name.casefold())

    def reorder_audio(self, order: Iterable[int]) -> None:
        indices = list(order)
        if sorted(indices) != list(range(len(self.audios))):
            raise ValueError("Urutan audio tidak valid.")
        self.audios = [self.audios[i] for i in indices]
