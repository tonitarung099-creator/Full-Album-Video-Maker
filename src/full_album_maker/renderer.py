from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from .paths import ffmpeg_path, output_dir, temp_dir
from .project import Project

class RenderError(RuntimeError):
    pass

def _q(path: str) -> str:
    return str(Path(path).resolve())

class FFmpegRenderer:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.ffmpeg = ffmpeg_path()
        if not self.ffmpeg:
            raise RenderError("FFmpeg tidak ditemukan.")

    def _run(self, args: list[str], log: Callable[[str], None] | None = None) -> None:
        if log:
            log("Menjalankan FFmpeg…")
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        assert proc.stdout is not None
        for line in proc.stdout:
            if log and ("time=" in line or "Error" in line or "error" in line):
                log(line.strip())
        code = proc.wait()
        if code != 0:
            raise RenderError(f"FFmpeg keluar dengan kode {code}.")

    def render(self, destination: str | None = None, log: Callable[[str], None] | None = None) -> str:
        p = self.project
        if not p.videos:
            raise RenderError("Belum ada footage video.")
        if not p.audios:
            raise RenderError("Belum ada lagu.")
        if p.total_audio_duration <= 0:
            raise RenderError("Durasi album tidak valid.")

        destination = destination or str(output_dir() / "FULL_ALBUM_FINAL.mp4")
        work = temp_dir()
        album_audio = work / "album_audio.m4a"
        base_video = work / "footage_base.mp4"
        ping_video = work / "footage_pingpong.mp4"

        self._build_audio(album_audio, log)
        self._build_video(base_video, log)

        loop_mode = p.settings.loop_mode
        need_loop = p.needs_loop()
        source_video = base_video
        if need_loop and loop_mode == "pingpong":
            self._build_pingpong(base_video, ping_video, log)
            source_video = ping_video

        self._build_final(source_video, album_audio, destination, need_loop, log)
        self._write_chapters(Path(destination).with_name("YouTube_Chapter.txt"))
        return destination

    def _build_audio(self, out: Path, log=None) -> None:
        args = [self.ffmpeg, "-y"]
        filters = []
        labels = []
        for i, item in enumerate(self.project.audios):
            args += ["-i", _q(item.path)]
            filters.append(f"[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]")
            labels.append(f"[a{i}]")
        filters.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[aout]")
        args += ["-filter_complex", ";".join(filters), "-map", "[aout]", "-c:a", "aac", "-b:a", self.project.settings.audio_bitrate, str(out)]
        self._run(args, log)

    def _build_video(self, out: Path, log=None) -> None:
        s = self.project.settings
        args = [self.ffmpeg, "-y"]
        filters = []
        labels = []
        for i, item in enumerate(self.project.videos):
            args += ["-i", _q(item.path)]
            filters.append(
                f"[{i}:v]scale={s.width}:{s.height}:force_original_aspect_ratio=decrease,"
                f"pad={s.width}:{s.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={s.fps},setpts=PTS-STARTPTS[v{i}]"
            )
            labels.append(f"[v{i}]")
        filters.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[vout]")
        codec = "libx264" if s.codec == "h264" else "libx265"
        args += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-an", "-c:v", codec, "-preset", "medium", "-b:v", s.video_bitrate, "-pix_fmt", "yuv420p", str(out)]
        self._run(args, log)

    def _build_pingpong(self, base: Path, out: Path, log=None) -> None:
        s = self.project.settings
        codec = "libx264" if s.codec == "h264" else "libx265"
        args = [
            self.ffmpeg, "-y", "-i", str(base),
            "-filter_complex", "[0:v]split[f][r];[r]reverse[rev];[f][rev]concat=n=2:v=1:a=0[v]",
            "-map", "[v]", "-an", "-c:v", codec, "-preset", "medium",
            "-b:v", s.video_bitrate, "-pix_fmt", "yuv420p", str(out)
        ]
        if log:
            log("Membuat footage ping-pong. Untuk footage sangat panjang, mode loop biasa lebih hemat memori.")
        self._run(args, log)

    def _build_final(self, video: Path, audio: Path, dest: str, need_loop: bool, log=None) -> None:
        s = self.project.settings
        speed = self.project.planned_speed()
        codec = "libx264" if s.codec == "h264" else "libx265"
        args = [self.ffmpeg, "-y"]
        if need_loop and s.loop_mode in {"auto", "loop", "pingpong"}:
            args += ["-stream_loop", "-1"]
        args += ["-i", str(video), "-i", str(audio)]
        args += [
            "-filter:v", f"setpts=PTS/{speed:.8f}",
            "-map", "0:v:0", "-map", "1:a:0",
            "-t", f"{self.project.total_audio_duration:.3f}",
            "-c:v", codec, "-preset", "medium", "-b:v", s.video_bitrate,
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", s.audio_bitrate,
            "-movflags", "+faststart", dest
        ]
        self._run(args, log)

    def _write_chapters(self, path: Path) -> None:
        current = 0.0
        lines = []
        for item in self.project.audios:
            total = int(round(current))
            h, rem = divmod(total, 3600)
            m, sec = divmod(rem, 60)
            stamp = f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
            lines.append(f"{stamp} {Path(item.path).stem}")
            current += item.duration
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
