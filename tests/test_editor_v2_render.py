from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest

from full_album_maker.editor_models import (
    Layer,
    MediaAsset,
    ProjectDocument,
    SongInstance,
    TimeBinding,
    Transform,
    seconds_to_tick,
)
from full_album_maker.preview_service import AccuratePreviewService
from full_album_maker.render_graph import FFmpegV2Compiler, RenderCompileError
from full_album_maker.render_plan import RENDER_PLAN_FORMAT, compile_render_plan
from full_album_maker.timeline_resolver import TimelineResolver


def _render_doc(tmp_path: Path) -> ProjectDocument:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg tidak tersedia")
    audio_paths: list[Path] = []
    for index, frequency in enumerate((440, 660), start=1):
        path = tmp_path / f"song-{index}.wav"
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:duration=0.6",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(path),
            ],
            check=True,
        )
        audio_paths.append(path)

    doc = ProjectDocument.new_empty("S02")
    for index, path in enumerate(audio_paths, start=1):
        asset = MediaAsset(kind="audio", locator=str(path), source_duration_tick=seconds_to_tick(0.6))
        doc.media.append(asset)
        doc.playlist.entries.append(
            SongInstance(
                asset_id=asset.asset_id,
                source_out_tick=asset.source_duration_tick,
                display_title=f"Song {index}",
            )
        )
    visual_track = doc.tracks[0]
    doc.layers.append(
        Layer(
            track_id=visual_track.track_id,
            type="background",
            name="Solid",
            order=0,
            time_binding=TimeBinding(kind="album"),
            properties={"mode": "solid", "color": "#223344"},
        )
    )
    doc.layers.append(
        Layer(
            track_id=visual_track.track_id,
            type="text",
            name="Timed Text",
            order=1,
            time_binding=TimeBinding(
                kind="absolute",
                start_tick=seconds_to_tick(0.2),
                duration_tick=seconds_to_tick(0.5),
            ),
            transform=Transform(x=0.15, y=0.2, width=0.7, height=0.2),
            properties={"text": "HELLO S02", "font_size": 80, "color": "#ffffff"},
        )
    )
    doc.validate()
    return doc


def test_render_plan_is_separate_immutable_snapshot(tmp_path: Path):
    doc = _render_doc(tmp_path)
    resolved = TimelineResolver().resolve(doc)
    plan = compile_render_plan(doc, resolved)
    assert plan.format == RENDER_PLAN_FORMAT
    assert plan.source_revision == doc.revision
    assert len(plan.audio_events) == 2
    assert plan.duration_tick == seconds_to_tick(1.2)
    original_signature = plan.content_signature
    doc.canvas.background_color = "#999999"
    assert plan.content_signature == original_signature


def test_compiler_fails_closed_for_unsupported_active_layer(tmp_path: Path):
    doc = _render_doc(tmp_path)
    doc.layers.append(
        Layer(
            track_id=doc.tracks[0].track_id,
            type="circular_spectrum",
            name="Belum S05",
            order=2,
            time_binding=TimeBinding(kind="album"),
        )
    )
    with pytest.raises(RenderCompileError, match="belum didukung"):
        FFmpegV2Compiler(shutil.which("ffmpeg") or "ffmpeg").compile_video(
            doc, tmp_path / "x.mp4", tmp_path / "work"
        )


def test_real_ffmpeg_two_song_background_text_and_accurate_preview(tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/ffprobe tidak tersedia")
    filters = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, check=True
    ).stdout
    if "drawtext" not in filters:
        pytest.skip("FFmpeg tidak punya drawtext")

    doc = _render_doc(tmp_path)
    out = tmp_path / "album.mp4"
    compiler = FFmpegV2Compiler(ffmpeg)
    compiled = compiler.compile_video(doc, out, tmp_path / "work")
    subprocess.run(compiled.args, check=True, capture_output=True, text=True)
    assert out.exists() and out.stat().st_size > 0

    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(out)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert '"codec_type": "video"' in probe
    assert '"codec_type": "audio"' in probe
    duration = float(re.search(r'"duration":\s*"([0-9.]+)"', probe).group(1))
    assert duration == pytest.approx(1.2, abs=0.08)

    accurate = tmp_path / "accurate.png"
    AccuratePreviewService(ffmpeg).render_frame(doc, seconds_to_tick(0.4), accurate)
    final_frame = tmp_path / "final.png"
    subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", "0.4", "-i", str(out), "-frames:v", "1", str(final_frame)],
        check=True,
    )
    psnr = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(accurate), "-i", str(final_frame), "-lavfi", "psnr", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    match = re.search(r"average:([0-9.]+)", psnr.stderr + psnr.stdout)
    assert match and float(match.group(1)) >= 40.0


def test_render_compile_failure_keeps_existing_output(tmp_path: Path):
    from full_album_maker.render_service_v2 import EditorRenderService, RenderErrorV2

    doc = _render_doc(tmp_path)
    doc.layers.append(
        Layer(
            track_id=doc.tracks[0].track_id,
            type="circular_spectrum",
            name="Unsupported",
            order=9,
            time_binding=TimeBinding(kind="album"),
        )
    )
    destination = tmp_path / "album.mp4"
    destination.write_bytes(b"OLD-OUTPUT")
    with pytest.raises(RenderErrorV2):
        EditorRenderService(shutil.which("ffmpeg") or "ffmpeg").render(doc, str(destination))
    assert destination.read_bytes() == b"OLD-OUTPUT"


def test_cancel_before_publish_keeps_existing_output(tmp_path: Path):
    from full_album_maker.render_service_v2 import (
        EditorRenderService,
        RenderCancelledV2,
    )

    class CancelRunner:
        def run(self, *args, **kwargs):
            raise RenderCancelledV2("cancel-test")

    doc = _render_doc(tmp_path)
    destination = tmp_path / "album.mp4"
    destination.write_bytes(b"OLD-OUTPUT")
    with pytest.raises(RenderCancelledV2, match="cancel-test"):
        EditorRenderService(shutil.which("ffmpeg") or "ffmpeg", runner=CancelRunner()).render(
            doc, str(destination)
        )
    assert destination.read_bytes() == b"OLD-OUTPUT"
