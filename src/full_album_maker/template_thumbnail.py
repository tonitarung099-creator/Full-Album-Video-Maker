from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

from .editor_controller import EditorController
from .editor_models import ProjectDocument
from .paths import ffmpeg_path
from .template_system import apply_template_command, template_definition
from .timeline_resolver import TimelineResolver
from .v13_render_graph import V13FFmpegCompiler


class TemplateThumbnailError(RuntimeError):
    pass


def template_thumbnail_tick(document: ProjectDocument) -> int:
    """Pick a stable frame inside the first active song."""
    resolved = TimelineResolver().resolve(document)
    if resolved.errors or not resolved.songs:
        raise TemplateThumbnailError("Thumbnail template membutuhkan minimal satu lagu aktif.")
    first = resolved.songs[0]
    duration = max(1, first.end_tick - first.start_tick)
    return first.start_tick + max(1, duration // 2)


def document_with_template(document: ProjectDocument, template_id: str) -> ProjectDocument:
    template_definition(template_id)
    controller = EditorController(document.clone())
    controller.dispatch(apply_template_command(controller.snapshot(), template_id))
    return controller.snapshot()


def render_template_thumbnail(
    document: ProjectDocument,
    template_id: str,
    destination: str | Path,
    *,
    ffmpeg: str | None = None,
) -> str:
    executable = ffmpeg or ffmpeg_path()
    if not executable:
        raise TemplateThumbnailError("FFmpeg tidak ditemukan untuk thumbnail template.")

    snapshot = document_with_template(document, template_id)
    tick = template_thumbnail_tick(snapshot)
    dest = Path(destination).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, stage_name = tempfile.mkstemp(
        prefix=f".{dest.stem}.",
        suffix=".template-preview.png",
        dir=dest.parent,
    )
    os.close(fd)
    stage = Path(stage_name)
    stage.unlink(missing_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix=f".{dest.stem}.template-work-",
            dir=dest.parent,
        ) as work:
            compiled = V13FFmpegCompiler(executable).compile_frame(
                snapshot,
                tick,
                stage,
                work,
            )
            completed = subprocess.run(
                compiled.args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if completed.returncode != 0:
                tail = "\n".join(
                    (completed.stderr or completed.stdout or "").splitlines()[-8:]
                )
                raise TemplateThumbnailError(
                    "Render thumbnail template gagal."
                    + (f"\n{tail}" if tail else "")
                )
            if not stage.exists() or stage.stat().st_size <= 0:
                raise TemplateThumbnailError("FFmpeg tidak menghasilkan thumbnail template.")
            os.replace(stage, dest)
    finally:
        stage.unlink(missing_ok=True)
    return str(dest)
