from __future__ import annotations

from pathlib import Path
import tempfile

from .editor_models import ProjectDocument
from .paths import ffmpeg_path, temp_dir
from .render_service_v2 import FFmpegProcessRunner, RenderErrorV2
from .s11_render_graph import S11FFmpegCompiler


class AccuratePreviewService:
    def __init__(self, ffmpeg: str | None = None, runner: FFmpegProcessRunner | None = None) -> None:
        self.ffmpeg = ffmpeg or ffmpeg_path()
        if not self.ffmpeg:
            raise RenderErrorV2("FFmpeg tidak ditemukan.")
        self.runner = runner or FFmpegProcessRunner()

    def render_frame(self, document: ProjectDocument, time_tick: int, destination: str | Path) -> str:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="fam_preview_", dir=temp_dir()) as folder:
            compiled = S11FFmpegCompiler(self.ffmpeg).compile_frame(
                document.clone(),
                time_tick,
                target,
                folder,
            )
            self.runner.run(compiled.args)
        if not target.exists() or target.stat().st_size == 0:
            raise RenderErrorV2("Preview frame tidak berhasil dibuat.")
        return str(target)