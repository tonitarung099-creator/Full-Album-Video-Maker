from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from .paths import ffmpeg_path, output_dir, temp_dir
from .project import Project

PINGPONG_MAX_RAW_BYTES = 512 * 1024 * 1024


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
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        last_lines: list[str] = []
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                last_lines.append(line)
                last_lines = last_lines[-20:]
            if log and ("time=" in line or "Error" in line or "error" in line):
                log(line)
        code = proc.wait()
        if code != 0:
            detail = "\n".join(last_lines[-8:])
            raise RenderError(
                f"FFmpeg keluar dengan kode {code}."
                + (f"\n{detail}" if detail else "")
            )

    def render(
        self,
        destination: str | None = None,
        log: Callable[[str], None] | None = None,
    ) -> str:
        p = self.project
        if not p.videos:
            raise RenderError("Belum ada footage video.")
        if not p.audios:
            raise RenderError("Belum ada lagu.")
        if p.total_video_duration <= 0:
            raise RenderError("Durasi footage tidak valid.")
        if p.total_audio_duration <= 0:
            raise RenderError("Durasi album tidak valid.")

        self._ensure_encoder()

        destination = destination or str(output_dir() / "FULL_ALBUM_FINAL.mp4")
        dest_path = Path(destination).resolve()
        source_paths = {Path(x.path).resolve() for x in [*p.videos, *p.audios]}
        if dest_path in source_paths:
            raise RenderError("Lokasi output tidak boleh sama dengan file sumber.")

        need_loop = p.needs_loop()
        if need_loop and p.settings.loop_mode == "none":
            raise RenderError(
                "Footage lebih pendek dari album tetapi mode loop dimatikan. "
                "Aktifkan Auto, Loop, atau Ping-pong."
            )

        root = temp_dir()
        with tempfile.TemporaryDirectory(prefix="fam_render_", dir=root) as work_dir:
            work = Path(work_dir)
            album_audio = work / "album_audio.m4a"
            base_video = work / "footage_base.mp4"
            ping_video = work / "footage_pingpong.mp4"

            self._build_audio(album_audio, log)
            self._build_video(base_video, log)

            source_video = base_video
            if need_loop and p.settings.loop_mode == "pingpong":
                if self._pingpong_is_safe():
                    self._build_pingpong(base_video, ping_video, log)
                    source_video = ping_video
                elif log:
                    log(
                        "Ping-pong dialihkan ke loop biasa untuk mencegah pemakaian RAM "
                        "berlebihan pada footage/resolusi ini."
                    )

            self._build_final(source_video, album_audio, destination, need_loop, log)

        self._write_chapters(dest_path.with_name("YouTube_Chapter.txt"))
        return destination

    def _encoder_name(self) -> str:
        return "libx264" if self.project.settings.codec == "h264" else "libx265"

    def _ensure_encoder(self) -> None:
        encoder = self._encoder_name()
        try:
            result = subprocess.run(
                [self.ffmpeg, "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=True,
            )
        except Exception as exc:
            raise RenderError(f"Gagal memeriksa encoder FFmpeg: {exc}") from exc
        if encoder not in result.stdout:
            raise RenderError(
                f"FFmpeg ini tidak menyediakan encoder {encoder}. "
                "Gunakan FFmpeg build GPL yang menyertakan libx264/libx265."
            )

    def _pingpong_is_safe(self) -> bool:
        s = self.project.settings
        seconds = max(0.0, self.project.adjusted_video_duration())
        estimated_raw = seconds * s.width * s.height * 1.5 * s.fps
        return estimated_raw <= PINGPONG_MAX_RAW_BYTES

    def _build_audio(self, out: Path, log=None) -> None:
        args = [self.ffmpeg, "-y"]
        filters: list[str] = []
        labels: list[str] = []

        for i, item in enumerate(self.project.audios):
            args += ["-i", _q(item.path)]
            filters.append(
                f"[{i}:a]aresample=48000,"
                f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a{i}]"
            )
            labels.append(f"[a{i}]")

        filters.append(
            "".join(labels) + f"concat=n={len(labels)}:v=0:a=1[aout]"
        )
        args += [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[aout]",
            "-c:a",
            "aac",
            "-b:a",
            self.project.settings.audio_bitrate,
            str(out),
        ]
        self._run(args, log)

    def _build_video(self, out: Path, log=None) -> None:
        s = self.project.settings
        args = [self.ffmpeg, "-y"]
        filters: list[str] = []
        labels: list[str] = []

        for i, item in enumerate(self.project.videos):
            args += ["-i", _q(item.path)]
            filters.append(
                f"[{i}:v]"
                f"scale={s.width}:{s.height}:force_original_aspect_ratio=decrease,"
                f"pad={s.width}:{s.height}:(ow-iw)/2:(oh-ih)/2,"
                f"setsar=1,fps={s.fps},format=yuv420p,setpts=PTS-STARTPTS[v{i}]"
            )
            labels.append(f"[v{i}]")

        filters.append(
            "".join(labels) + f"concat=n={len(labels)}:v=1:a=0[vcat]"
        )
        filters.append(
            f"[vcat]setpts=PTS/{self.project.planned_speed():.8f}[vout]"
        )

        codec = self._encoder_name()
        args += [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-an",
            "-c:v",
            codec,
            "-preset",
            "medium",
            "-b:v",
            s.video_bitrate,
            "-pix_fmt",
            "yuv420p",
            str(out),
        ]
        self._run(args, log)

    def _build_pingpong(self, base: Path, out: Path, log=None) -> None:
        s = self.project.settings
        codec = self._encoder_name()
        args = [
            self.ffmpeg,
            "-y",
            "-i",
            str(base),
            "-filter_complex",
            "[0:v]split[f][r];[r]reverse,setpts=PTS-STARTPTS[rev];"
            "[f][rev]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-an",
            "-c:v",
            codec,
            "-preset",
            "medium",
            "-b:v",
            s.video_bitrate,
            "-pix_fmt",
            "yuv420p",
            str(out),
        ]
        if log:
            log("Membuat ping-pong untuk footage yang aman diproses di RAM.")
        self._run(args, log)

    def _build_final(
        self,
        video: Path,
        audio: Path,
        dest: str,
        need_loop: bool,
        log=None,
    ) -> None:
        s = self.project.settings
        args = [self.ffmpeg, "-y"]
        if need_loop and s.loop_mode in {"auto", "loop", "pingpong"}:
            args += ["-stream_loop", "-1"]

        args += ["-i", str(video), "-i", str(audio)]
        args += [
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-t",
            f"{self.project.total_audio_duration:.3f}",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            dest,
        ]
        self._run(args, log)

    def _write_chapters(self, path: Path) -> None:
        current = 0.0
        lines: list[str] = []
        for item in self.project.audios:
            total = int(round(current))
            h, rem = divmod(total, 3600)
            m, sec = divmod(rem, 60)
            stamp = f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
            lines.append(f"{stamp} {Path(item.path).stem}")
            current += item.duration
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
