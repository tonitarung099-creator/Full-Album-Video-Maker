from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

from .paths import ffmpeg_path, ffprobe_path


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wmv"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus"}


class MediaProbeError(RuntimeError):
    pass


def _positive_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _probe_stream_duration(path: Path, selector: str | None) -> float:
    tool = ffprobe_path()
    if not tool:
        raise MediaProbeError(
            "FFprobe tidak ditemukan. Pastikan tools/ffmpeg/ffprobe.exe tersedia."
        )

    cmd = [tool, "-v", "error"]
    if selector:
        cmd += ["-select_streams", selector]
    cmd += [
        "-show_entries",
        "stream=duration:stream_tags=DURATION:format=duration",
        "-of",
        "json",
        str(path),
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=30,
        )
        payload = json.loads(proc.stdout or "{}")
        for stream in payload.get("streams", []):
            value = _positive_float(stream.get("duration"))
            if value is not None:
                return value
            tagged = _parse_ffmpeg_time((stream.get("tags") or {}).get("DURATION", ""))
            if tagged is not None:
                return tagged
        value = _positive_float((payload.get("format") or {}).get("duration"))
        if value is not None:
            return value
    except Exception as exc:
        raise MediaProbeError(f"Gagal membaca durasi {path.name}: {exc}") from exc

    raise MediaProbeError(f"Durasi media tidak ditemukan: {path.name}")


def _parse_ffmpeg_time(value: str) -> float | None:
    try:
        hours, minutes, seconds = value.strip().split(":")
        total = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (TypeError, ValueError):
        return None
    return total if math.isfinite(total) and total > 0 else None


def _probe_decoded_audio_duration(path: Path) -> float:
    """Return the real decoded/gapless audio duration.

    MP3/AAC containers can include encoder delay or padding in their nominal
    duration. FFmpeg's decoded progress already applies skip/discard metadata,
    so this value matches the samples that will actually be rendered.
    """

    tool = ffmpeg_path()
    if not tool:
        return _probe_stream_duration(path, "a:0")

    cmd = [
        tool,
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-progress",
        "pipe:1",
        "-nostats",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or "").strip() or f"FFmpeg exit {proc.returncode}")

        duration = 0.0
        for raw in (proc.stdout or "").splitlines():
            key, sep, value = raw.partition("=")
            if not sep:
                continue
            if key == "out_time_us":
                parsed = _positive_float(value)
                if parsed is not None:
                    duration = max(duration, parsed / 1_000_000.0)
            elif key == "out_time":
                parsed = _parse_ffmpeg_time(value)
                if parsed is not None:
                    duration = max(duration, parsed)

        if duration > 0:
            return duration
    except Exception:
        # Keep imports usable even if a particular FFmpeg build cannot emit
        # progress for this codec; stream probing is still better than failing
        # the whole project import.
        pass

    return _probe_stream_duration(path, "a:0")


def probe_duration(path: str, media_kind: str | None = None) -> float:
    target = Path(path)
    if not target.exists():
        raise MediaProbeError(f"File tidak ditemukan: {target}")

    kind = (media_kind or "").strip().casefold()
    if not kind:
        suffix = target.suffix.casefold()
        if suffix in VIDEO_EXTENSIONS:
            kind = "video"
        elif suffix in AUDIO_EXTENSIONS:
            kind = "audio"

    try:
        if kind == "video":
            return _probe_stream_duration(target, "v:0")
        if kind == "audio":
            return _probe_decoded_audio_duration(target)
        return _probe_stream_duration(target, None)
    except MediaProbeError:
        raise
    except Exception as exc:
        raise MediaProbeError(f"Gagal membaca durasi {target.name}: {exc}") from exc
