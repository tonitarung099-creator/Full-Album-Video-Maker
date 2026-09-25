from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from .paths import ffmpeg_path, output_dir, temp_dir
from .project import Project
from .timeline import (
    EPSILON,
    TimelinePlan,
    VideoTimelineClip,
    load_timeline,
    save_timeline,
    validate_timeline_against_project,
)

# FFmpeg's reverse filter buffers frames. Reverse clips are therefore rendered
# in bounded chunks so a long Ping-Pong timeline does not require unbounded RAM.
REVERSE_CHUNK_RAW_BYTES = 384 * 1024 * 1024


class RenderError(RuntimeError):
    pass


def _q(path: str) -> str:
    return str(Path(path).resolve())


def _concat_path(path: Path) -> str:
    value = path.resolve().as_posix()
    return value.replace("'", "'\\''")


class FFmpegRenderer:
    """Renders exactly one validated TimelinePlan.

    Project media lists are used only to validate that the TimelinePlan still
    belongs to the same project and to obtain output encoding settings.
    Clip order, source ranges, speed, direction and final duration all come
    from TimelinePlan.
    """

    def __init__(
        self,
        project: Project,
        timeline: TimelinePlan | str | Path | None = None,
    ) -> None:
        self.project = project

        if timeline is None:
            raise RenderError(
                "Timeline belum tersedia. Klik AUTO SUSUN TIMELINE sebelum render."
            )
        try:
            self.timeline = (
                load_timeline(str(timeline))
                if isinstance(timeline, (str, Path))
                else timeline
            )
        except Exception as exc:
            raise RenderError(f"Gagal membaca Timeline JSON: {exc}") from exc

        errors = validate_timeline_against_project(self.timeline, self.project)
        if errors:
            raise RenderError(
                "Timeline tidak valid untuk proyek ini:\n• " + "\n• ".join(errors)
            )

        self.ffmpeg = ffmpeg_path()
        if not self.ffmpeg:
            raise RenderError("FFmpeg tidak ditemukan.")

    def _run(
        self,
        args: list[str],
        log: Callable[[str], None] | None = None,
    ) -> None:
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
            if log and (
                "time=" in line
                or "Error" in line
                or "error" in line
                or "Invalid" in line
            ):
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
        plan = self.timeline

        errors = validate_timeline_against_project(plan, self.project)
        if errors:
            raise RenderError(
                "Timeline berubah/tidak valid sebelum render:\n• "
                + "\n• ".join(errors)
            )

        source_paths = {
            Path(clip.source).resolve()
            for clip in [*plan.video_clips, *plan.audio_clips]
        }
        project_source_paths = {
            Path(item.path).resolve()
            for item in [*self.project.videos, *self.project.audios]
        }
        missing = [str(path) for path in source_paths if not path.exists()]
        if missing:
            preview = "\n".join(f"• {x}" for x in missing[:8])
            more = (
                f"\n• …dan {len(missing) - 8} file lain"
                if len(missing) > 8
                else ""
            )
            raise RenderError(f"File sumber timeline tidak ditemukan:\n{preview}{more}")

        self._ensure_encoder()

        destination = destination or str(output_dir() / "FULL_ALBUM_FINAL.mp4")
        dest_path = Path(destination).resolve()
        destination_key = str(dest_path).casefold()
        project_source_keys = {
            str(path).casefold()
            for path in project_source_paths
        }
        if destination_key in project_source_keys:
            raise RenderError(
                "Lokasi output tidak boleh sama dengan file sumber proyek, "
                "termasuk footage/audio yang tidak terpakai di TimelinePlan."
            )

        if log:
            log(
                "Render memakai TimelinePlan sebagai sumber kebenaran: "
                f"{len(plan.video_clips)} clip video, "
                f"{len(plan.audio_clips)} clip audio, "
                f"durasi {plan.duration:.3f} detik."
            )

        root = temp_dir()
        with tempfile.TemporaryDirectory(prefix="fam_render_", dir=root) as work_dir:
            work = Path(work_dir)
            album_audio = work / "timeline_audio.m4a"
            timeline_video = work / "timeline_video.mp4"

            self._build_audio_from_timeline(album_audio, log)
            self._build_video_from_timeline(timeline_video, work, log)
            self._build_final(timeline_video, album_audio, destination, log)

        self._write_chapters(dest_path.with_name("YouTube_Chapter.txt"))
        self._write_tracklist(dest_path.with_name("Tracklist.txt"))
        save_timeline(
            str(dest_path.with_name("Timeline_Final.json")),
            self.timeline,
        )
        if log:
            log("Timeline_Final.json disimpan di folder hasil render.")
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

        encoder_output = (result.stdout or "") + "\n" + (result.stderr or "")
        if encoder not in encoder_output:
            raise RenderError(
                f"FFmpeg ini tidak menyediakan encoder {encoder}. "
                "Gunakan FFmpeg build GPL yang menyertakan libx264/libx265."
            )

    def _build_audio_from_timeline(self, out: Path, log=None) -> None:
        clips = self.timeline.audio_clips
        args = [self.ffmpeg, "-y"]
        filters: list[str] = []
        labels: list[str] = []

        for i, clip in enumerate(clips):
            source_duration = clip.source_out - clip.source_in
            args += [
                "-ss",
                f"{clip.source_in:.6f}",
                "-t",
                f"{source_duration:.6f}",
                "-i",
                _q(clip.source),
            ]
            filters.append(
                f"[{i}:a]"
                "aresample=48000,"
                "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                "asetpts=PTS-STARTPTS,"
                f"atrim=duration={clip.timeline_duration:.6f},"
                f"asetpts=PTS-STARTPTS[a{i}]"
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
            "-vn",
            "-c:a",
            "aac",
            "-b:a",
            self.project.settings.audio_bitrate,
            "-t",
            f"{self.timeline.duration:.6f}",
            str(out),
        ]
        if log:
            log("Menyusun audio persis dari Audio Timeline.")
        self._run(args, log)

    def _build_video_from_timeline(
        self,
        out: Path,
        work: Path,
        log=None,
    ) -> None:
        clip_dir = work / "video_clips"
        clip_dir.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []

        for index, clip in enumerate(self.timeline.video_clips):
            clip_out = clip_dir / f"clip_{index:05d}.mp4"
            if log:
                log(
                    f"Video timeline {index + 1}/{len(self.timeline.video_clips)}: "
                    f"{clip.name} {clip.source_in:.3f}–{clip.source_out:.3f}s "
                    f"@ {clip.speed:.3f}x {clip.direction}."
                )

            if clip.direction == "reverse":
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
                )
            files.append(clip_out)

        self._concat_video_files(files, out, work / "video_concat.txt", log)

    def _encode_video_segment(
        self,
        *,
        source: str,
        source_in: float,
        source_out: float,
        speed: float,
        timeline_duration: float,
        reverse: bool,
        out: Path,
        log=None,
    ) -> None:
        if source_out <= source_in + EPSILON:
            raise RenderError("Video timeline memiliki source range kosong.")
        if speed <= 0:
            raise RenderError("Video timeline memiliki speed tidak valid.")

        settings = self.project.settings
        source_duration = source_out - source_in
        filters = [
            (
                f"scale={settings.width}:{settings.height}:"
                "force_original_aspect_ratio=decrease"
            ),
            (
                f"pad={settings.width}:{settings.height}:"
                "(ow-iw)/2:(oh-ih)/2"
            ),
            "setsar=1",
            f"fps={settings.fps}",
            "format=yuv420p",
        ]
        if reverse:
            filters.append("reverse")
        filters += [
            f"setpts=(PTS-STARTPTS)/{speed:.10f}",
            f"fps={settings.fps}",
            # Hold the final decoded frame briefly before trim. This prevents
            # per-clip frame rounding/seek shortfalls from accumulating into
            # visible A/V drift when many clips are concatenated.
            "tpad=stop_mode=clone:stop_duration=1.0",
            f"trim=duration={timeline_duration:.6f}",
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
            "-t",
            f"{timeline_duration:.6f}",
            str(out),
        ]
        self._run(args, log)

    def _reverse_chunk_seconds(self) -> float:
        settings = self.project.settings
        bytes_per_second = (
            float(settings.width)
            * float(settings.height)
            * 1.5
            * float(settings.fps)
        )
        if bytes_per_second <= 0:
            return 1.0
        seconds = REVERSE_CHUNK_RAW_BYTES / bytes_per_second
        return max(0.25, min(5.0, seconds))

    def _build_reverse_clip(
        self,
        clip: VideoTimelineClip,
        out: Path,
        clip_dir: Path,
        clip_index: int,
        log=None,
    ) -> None:
        chunk_seconds = self._reverse_chunk_seconds()
        part_dir = clip_dir / f"reverse_{clip_index:05d}"
        part_dir.mkdir(parents=True, exist_ok=True)

        parts: list[Path] = []
        source_end = clip.source_out
        part_index = 0

        while source_end > clip.source_in + EPSILON:
            source_start = max(clip.source_in, source_end - chunk_seconds)
            source_duration = source_end - source_start
            timeline_duration = source_duration / clip.speed
            part = part_dir / f"part_{part_index:05d}.mp4"

            self._encode_video_segment(
                source=clip.source,
                source_in=source_start,
                source_out=source_end,
                speed=clip.speed,
                timeline_duration=timeline_duration,
                reverse=True,
                out=part,
                log=log,
            )
            parts.append(part)
            source_end = source_start
            part_index += 1

        if not parts:
            raise RenderError("Reverse timeline tidak menghasilkan bagian video.")

        if log and len(parts) > 1:
            log(
                f"Ping-Pong diproses dalam {len(parts)} chunk bounded-memory "
                f"(maks. sekitar {chunk_seconds:.2f}s source/chunk)."
            )
        self._concat_video_files(
            parts,
            out,
            part_dir / "reverse_concat.txt",
            log,
        )

    def _concat_video_files(
        self,
        files: list[Path],
        out: Path,
        list_file: Path,
        log=None,
    ) -> None:
        if not files:
            raise RenderError("Timeline tidak menghasilkan clip video.")

        if len(files) == 1:
            shutil.copyfile(files[0], out)
            return

        list_file.write_text(
            "\n".join(f"file '{_concat_path(path)}'" for path in files) + "\n",
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
            str(list_file),
            "-an",
            "-c:v",
            "copy",
            "-movflags",
            "+faststart",
            str(out),
        ]
        self._run(args, log)

    def _build_final(
        self,
        video: Path,
        audio: Path,
        dest: str,
        log=None,
    ) -> None:
        args = [
            self.ffmpeg,
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-t",
            f"{self.timeline.duration:.6f}",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            dest,
        ]
        if log:
            log("Mux final mengikuti durasi TimelinePlan.")
        self._run(args, log)

    @staticmethod
    def _stamp(seconds: float) -> str:
        total = int(round(seconds))
        h, rem = divmod(total, 3600)
        m, sec = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"

    def _write_chapters(self, path: Path) -> None:
        lines = [
            f"{self._stamp(clip.timeline_in)} {clip.name}"
            for clip in self.timeline.audio_clips
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_tracklist(self, path: Path) -> None:
        lines = [
            f"{index:02d}. {clip.name}  [{self._stamp(clip.timeline_duration)}]"
            for index, clip in enumerate(self.timeline.audio_clips, start=1)
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
