from __future__ import annotations

from dataclasses import asdict, dataclass, field
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

    def move_audio(self, from_position: int, to_position: int) -> None:
        if not 1 <= from_position <= len(self.audios):
            raise ValueError("Posisi lagu asal tidak valid.")
        if not 1 <= to_position <= len(self.audios):
            raise ValueError("Posisi lagu tujuan tidak valid.")
        item = self.audios.pop(from_position - 1)
        self.audios.insert(to_position - 1, item)

    def reorder_audio(self, order: Iterable[int]) -> None:
        indices = list(order)
        if sorted(indices) != list(range(len(self.audios))):
            raise ValueError("Urutan audio tidak valid.")
        self.audios = [self.audios[i] for i in indices]

    def validation(self) -> dict[str, list[str]]:
        errors: list[str] = []
        warnings: list[str] = []

        if not self.videos:
            errors.append("Belum ada footage video.")
        if not self.audios:
            errors.append("Belum ada lagu.")
        if self.videos and self.total_video_duration <= 0:
            errors.append("Durasi footage tidak valid.")
        if self.audios and self.total_audio_duration <= 0:
            errors.append("Durasi album tidak valid.")

        missing = [x.name for x in [*self.videos, *self.audios] if not Path(x.path).exists()]
        if missing:
            errors.append(f"{len(missing)} file sumber tidak ditemukan.")

        duplicate_audio = len({str(Path(x.path).resolve()).casefold() for x in self.audios}) != len(self.audios)
        if duplicate_audio:
            warnings.append("Ada lagu yang sama dimasukkan lebih dari sekali.")

        if self.videos and self.audios:
            if self.needs_loop() and self.settings.loop_mode == "none":
                errors.append("Footage terlalu pendek tetapi mode loop dimatikan.")
            if self.planned_speed() < 0.35:
                warnings.append("Slow motion sangat rendah; gerakan video bisa terlihat terlalu lambat.")
            if self.total_video_duration < self.total_audio_duration * 0.15:
                warnings.append("Footage sangat pendek dibanding album; loop akan cukup sering terlihat.")

        return {"errors": errors, "warnings": warnings}

    def optimize_youtube(self, quality: str = "1080p") -> dict[str, object]:
        profiles = {
            "1080p": (1920, 1080, 30, "12M"),
            "1440p": (2560, 1440, 30, "20M"),
            "4k": (3840, 2160, 30, "45M"),
        }
        key = quality.casefold()
        if key not in profiles:
            raise ValueError("quality harus 1080p, 1440p, atau 4k.")

        width, height, fps, bitrate = profiles[key]
        s = self.settings
        s.width = width
        s.height = height
        s.fps = fps
        s.codec = "h264"
        s.video_bitrate = bitrate
        s.audio_bitrate = "320k"
        s.auto_speed = True
        s.min_speed = 0.50
        s.loop_mode = "auto"

        return {
            "quality": key,
            "resolution": [width, height],
            "fps": fps,
            "codec": s.codec,
            "video_bitrate": bitrate,
            "audio_bitrate": s.audio_bitrate,
            "planned_speed": round(self.planned_speed(), 4),
            "needs_loop": self.needs_loop(),
        }

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "videos": [asdict(x) for x in self.videos],
            "audios": [asdict(x) for x in self.audios],
            "settings": asdict(self.settings),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        if not isinstance(data, dict):
            raise ValueError("Format file proyek tidak valid.")
        try:
            version = int(data.get("version", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError("Versi file proyek tidak valid.") from exc
        if version != 1:
            raise ValueError("Versi file proyek belum didukung.")

        def parse_media(items, label: str) -> list[MediaItem]:
            if not isinstance(items, list):
                raise ValueError(f"{label} proyek harus berupa daftar.")
            result: list[MediaItem] = []
            for index, raw in enumerate(items, start=1):
                if not isinstance(raw, dict):
                    raise ValueError(f"{label} #{index} tidak valid.")
                path = raw.get("path")
                if not isinstance(path, str) or not path.strip():
                    raise ValueError(f"Path {label.lower()} #{index} tidak valid.")
                try:
                    duration = float(raw.get("duration", 0.0))
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Durasi {label.lower()} #{index} tidak valid."
                    ) from exc
                if not math.isfinite(duration) or duration < 0:
                    raise ValueError(f"Durasi {label.lower()} #{index} tidak valid.")
                result.append(MediaItem(path=path, duration=duration))
            return result

        videos = parse_media(data.get("videos", []), "Video")
        audios = parse_media(data.get("audios", []), "Audio")

        settings_data = data.get("settings", {})
        if not isinstance(settings_data, dict):
            raise ValueError("Setting proyek tidak valid.")

        defaults = ProjectSettings()
        auto_speed = settings_data.get("auto_speed", defaults.auto_speed)
        if not isinstance(auto_speed, bool):
            raise ValueError("Setting auto_speed tidak valid.")

        def finite_number(name: str, default: float) -> float:
            try:
                value = float(settings_data.get(name, default))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Setting {name} tidak valid.") from exc
            if not math.isfinite(value):
                raise ValueError(f"Setting {name} tidak valid.")
            return value

        manual_speed = finite_number("manual_speed", defaults.manual_speed)
        min_speed = finite_number("min_speed", defaults.min_speed)
        if not 0.05 <= manual_speed <= 2.0:
            raise ValueError("Setting manual_speed harus 0.05–2.0.")
        if not 0.05 <= min_speed <= 1.0:
            raise ValueError("Setting min_speed harus 0.05–1.0.")

        loop_mode = settings_data.get("loop_mode", defaults.loop_mode)
        if loop_mode not in {"auto", "loop", "pingpong", "none"}:
            raise ValueError("Setting loop_mode tidak valid.")

        def valid_int(name: str, default: int) -> int:
            raw = settings_data.get(name, default)
            if isinstance(raw, bool):
                raise ValueError(f"Setting {name} tidak valid.")
            try:
                return int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Setting {name} tidak valid.") from exc

        width = valid_int("width", defaults.width)
        height = valid_int("height", defaults.height)
        fps = valid_int("fps", defaults.fps)
        if not 320 <= width <= 7680 or not 240 <= height <= 4320 or width % 2 or height % 2:
            raise ValueError("Resolusi proyek tidak valid.")
        if fps not in {24, 25, 30, 50, 60}:
            raise ValueError("FPS proyek tidak valid.")

        codec = settings_data.get("codec", defaults.codec)
        if codec not in {"h264", "h265"}:
            raise ValueError("Codec proyek tidak valid.")

        video_bitrate = settings_data.get("video_bitrate", defaults.video_bitrate)
        audio_bitrate = settings_data.get("audio_bitrate", defaults.audio_bitrate)
        if not isinstance(video_bitrate, str) or not video_bitrate.strip():
            raise ValueError("Video bitrate proyek tidak valid.")
        if not isinstance(audio_bitrate, str) or not audio_bitrate.strip():
            raise ValueError("Audio bitrate proyek tidak valid.")

        settings = ProjectSettings(
            auto_speed=auto_speed,
            manual_speed=manual_speed,
            min_speed=min_speed,
            loop_mode=loop_mode,
            width=width,
            height=height,
            fps=fps,
            codec=codec,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
        )
        return cls(videos=videos, audios=audios, settings=settings)
