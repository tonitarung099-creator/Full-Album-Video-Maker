from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from typing import Callable

from .atomic_io import atomic_write_text
from .editor_models import ProjectDocument
from .paths import ffmpeg_path, output_dir
from .render_graph import FFmpegV2Compiler, RenderCompileError
from .render_plan import RenderPlan


class RenderErrorV2(RuntimeError):
    pass


class RenderCancelledV2(RenderErrorV2):
    pass


class FFmpegProcessRunner:
    def run(
        self,
        args: tuple[str, ...] | list[str],
        *,
        cancel_event: threading.Event | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        proc = subprocess.Popen(
            list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        tail: list[str] = []
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3)
                    raise RenderCancelledV2("Render dibatalkan oleh pengguna.")
                line = proc.stdout.readline()
                if line:
                    line = line.rstrip()
                    tail.append(line)
                    tail = tail[-20:]
                    if log:
                        log(line)
                if proc.poll() is not None:
                    break
            if proc.returncode != 0:
                raise RenderErrorV2(
                    f"FFmpeg keluar dengan kode {proc.returncode}."
                    + ("\n" + "\n".join(tail[-8:]) if tail else "")
                )
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def _write_tracklist(path: Path, document: ProjectDocument, plan: RenderPlan) -> None:
    assets = document.asset_map()
    songs = document.song_map()
    lines: list[str] = []
    for index, event in enumerate(plan.audio_events, start=1):
        song = songs[event.song_id]
        asset = assets[event.asset_id]
        title = song.display_title.strip() or Path(asset.locator).stem
        artist = song.display_artist.strip()
        lines.append(f"{index:02d}. {title}" + (f" — {artist}" if artist else ""))
    atomic_write_text(path, "\n".join(lines) + "\n", encoding="utf-8")


def _write_chapters(path: Path, document: ProjectDocument, plan: RenderPlan) -> None:
    assets = document.asset_map()
    songs = document.song_map()
    lines: list[str] = []
    for event in plan.audio_events:
        seconds = event.start_tick / document.timebase
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        stamp = f"{hours:02d}:{minutes:02d}:{secs:02d}"
        song = songs[event.song_id]
        title = song.display_title.strip() or Path(assets[event.asset_id].locator).stem
        lines.append(f"{stamp} {title}")
    atomic_write_text(path, "\n".join(lines) + "\n", encoding="utf-8")


class EditorRenderService:
    def __init__(self, ffmpeg: str | None = None, runner: FFmpegProcessRunner | None = None) -> None:
        self.ffmpeg = ffmpeg or ffmpeg_path()
        if not self.ffmpeg:
            raise RenderErrorV2("FFmpeg tidak ditemukan.")
        self.runner = runner or FFmpegProcessRunner()

    def render(
        self,
        document: ProjectDocument,
        destination: str | None = None,
        *,
        cancel_event: threading.Event | None = None,
        log: Callable[[str], None] | None = None,
    ) -> str:
        snapshot = document.clone()
        snapshot.validate()
        destination = destination or str(output_dir() / "FULL_ALBUM_FINAL.mp4")
        dest = Path(destination).resolve()
        active_sources = {
            Path(asset.locator).resolve()
            for asset in snapshot.media
            if asset.locator
        }
        if dest in active_sources:
            raise RenderErrorV2("Lokasi output tidak boleh menimpa media proyek.")

        active_asset_ids = {
            song.asset_id for song in snapshot.playlist.entries if song.enabled
        }
        active_asset_ids.update(
            ref
            for layer in snapshot.layers
            if layer.enabled
            for ref in layer.asset_refs
        )
        assets = snapshot.asset_map()
        missing = [
            str(Path(assets[asset_id].locator))
            for asset_id in active_asset_ids
            if asset_id in assets and not Path(assets[asset_id].locator).exists()
        ]
        if missing:
            raise RenderErrorV2(
                "Media aktif tidak ditemukan: " + ", ".join(missing[:8])
            )

        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, staged_name = tempfile.mkstemp(
            prefix=f".{dest.stem}.",
            suffix=".v2-rendering.mp4",
            dir=dest.parent,
        )
        os.close(fd)
        staged = Path(staged_name)
        staged.unlink(missing_ok=True)
        chapter = dest.with_name(f"{dest.stem}_YouTube_Chapter.txt")
        tracklist = dest.with_name(f"{dest.stem}_Tracklist.txt")
        timeline = dest.with_name(f"{dest.stem}_Timeline_Final.json")
        stages: list[Path] = [staged]
        try:
            # Keep all transaction staging on the destination filesystem. Windows
            # os.replace cannot atomically move a sidecar from e.g. portable app D:
            # to an output folder on C:. A hidden work directory beside the output
            # preserves same-filesystem atomic publication and is removed afterward.
            with tempfile.TemporaryDirectory(
                prefix=f".{dest.stem}.fam-v2-",
                dir=dest.parent,
            ) as folder:
                work = Path(folder)
                compiled = FFmpegV2Compiler(self.ffmpeg).compile_video(
                    snapshot,
                    staged,
                    work,
                )
                if log:
                    log(
                        f"Render v2 revision {snapshot.revision}; durasi "
                        f"{compiled.render_plan.duration_tick / snapshot.timebase:.3f} detik."
                    )
                self.runner.run(
                    compiled.args,
                    cancel_event=cancel_event,
                    log=log,
                )
                if cancel_event is not None and cancel_event.is_set():
                    raise RenderCancelledV2("Render dibatalkan oleh pengguna.")

                staged_chapter = work / chapter.name
                staged_tracklist = work / tracklist.name
                staged_timeline = work / timeline.name
                _write_chapters(staged_chapter, snapshot, compiled.render_plan)
                _write_tracklist(staged_tracklist, snapshot, compiled.render_plan)
                atomic_write_text(
                    staged_timeline,
                    json.dumps(
                        compiled.render_plan.to_dict(),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                )
                stages.extend(
                    [staged_chapter, staged_tracklist, staged_timeline]
                )

                from .atomic_bundle import publish_bundle_transactional

                publish_bundle_transactional(
                    zip(stages, [dest, chapter, tracklist, timeline])
                )
        except (RenderCompileError, OSError, subprocess.SubprocessError) as exc:
            raise RenderErrorV2(str(exc)) from exc
        finally:
            for path in stages:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        return str(dest)
