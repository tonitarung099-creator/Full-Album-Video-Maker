from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .project import Project


class ProjectController:
    def __init__(self, project: Project) -> None:
        self.project = project

    def summary(self) -> dict[str, Any]:
        p = self.project
        return {
            "video_count": len(p.videos),
            "audio_count": len(p.audios),
            "videos": [
                {"position": i + 1, "name": x.name, "duration_seconds": round(x.duration, 3)}
                for i, x in enumerate(p.videos)
            ],
            "tracks": [
                {"position": i + 1, "name": x.name, "duration_seconds": round(x.duration, 3)}
                for i, x in enumerate(p.audios)
            ],
            "video_duration_seconds": round(p.total_video_duration, 3),
            "album_duration_seconds": round(p.total_audio_duration, 3),
            "planned_speed": round(p.planned_speed(), 4),
            "adjusted_video_duration_seconds": round(p.adjusted_video_duration(), 3),
            "needs_loop": p.needs_loop(),
            "settings": asdict(p.settings),
            "validation": p.validation(),
        }

    def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        s = self.project.settings

        if name == "project_summary":
            return self.summary()

        if name == "validate_project":
            return {
                "validation": self.project.validation(),
                "summary": self.summary(),
            }

        if name == "optimize_youtube":
            quality = str(args.get("quality", "1080p"))
            result = self.project.optimize_youtube(quality)
            return {"optimized": result, "summary": self.summary()}

        if name == "set_slowmo":
            speed = float(args["speed"])
            if not 0.05 <= speed <= 2.0:
                raise ValueError("speed harus 0.05–2.0")
            s.auto_speed = False
            s.manual_speed = speed

        elif name == "set_auto_speed":
            s.auto_speed = True
            if "min_speed" in args:
                s.min_speed = min(1.0, max(0.05, float(args["min_speed"])))

        elif name == "set_loop_mode":
            mode = str(args["mode"])
            if mode not in {"auto", "loop", "pingpong", "none"}:
                raise ValueError("loop mode tidak valid")
            s.loop_mode = mode

        elif name == "set_resolution":
            width = int(args["width"])
            height = int(args["height"])
            if not 320 <= width <= 7680 or not 240 <= height <= 4320:
                raise ValueError("resolusi di luar batas 320×240 sampai 7680×4320")
            if width % 2 or height % 2:
                raise ValueError("width dan height harus angka genap untuk output H.264/H.265")
            s.width = width
            s.height = height

        elif name == "set_fps":
            fps = int(args["fps"])
            if fps not in {24, 25, 30, 50, 60}:
                raise ValueError("fps harus 24/25/30/50/60")
            s.fps = fps

        elif name == "set_codec":
            codec = str(args["codec"])
            if codec not in {"h264", "h265"}:
                raise ValueError("codec harus h264/h265")
            s.codec = codec

        elif name == "set_quality":
            video_bitrate = str(args.get("video_bitrate", s.video_bitrate))
            audio_bitrate = str(args.get("audio_bitrate", s.audio_bitrate))
            allowed_video = {"6M", "8M", "12M", "20M", "30M", "45M", "60M"}
            allowed_audio = {"128k", "192k", "256k", "320k"}
            if video_bitrate not in allowed_video:
                raise ValueError("video_bitrate tidak didukung")
            if audio_bitrate not in allowed_audio:
                raise ValueError("audio_bitrate tidak didukung")
            s.video_bitrate = video_bitrate
            s.audio_bitrate = audio_bitrate

        elif name == "sort_audio_by_name":
            self.project.sort_audio_by_name()

        elif name == "move_audio":
            self.project.move_audio(
                int(args["from_position"]),
                int(args["to_position"]),
            )

        else:
            raise ValueError(f"Tool tidak dikenal: {name}")

        return self.summary()
