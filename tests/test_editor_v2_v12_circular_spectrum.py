from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

from PIL import Image
from PySide6.QtWidgets import QApplication
import pytest

from full_album_maker.circular_spectrum import (
    MAX_INTERNAL_SIDE,
    circular_geometry,
    circular_internal_side,
    circular_spectrum_filter,
)
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
from full_album_maker.property_inspector import PropertyInspector
from full_album_maker.render_graph import FFmpegV2Compiler
from full_album_maker.render_service_v2 import (
    EditorRenderService,
    RenderCancelledV2,
)
from full_album_maker.spectrum_feature import (
    SPECTRUM_CAPABILITIES,
    SPECTRUM_PRESETS,
    apply_spectrum_preset,
    make_spectrum_layer,
    normalize_spectrum_properties,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _noise_audio(tmp_path: Path, duration: float = 0.60) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg tidak tersedia")
    path = tmp_path / "pink-noise.wav"
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
            f"anoisesrc=color=pink:duration={duration}:amplitude=0.65",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(path),
        ],
        check=True,
    )
    return path


def _circular_doc(tmp_path: Path, *, background: str = "#f5f5f5") -> ProjectDocument:
    audio = _noise_audio(tmp_path)
    doc = ProjectDocument.new_empty("Circular Spectrum v1.2")
    doc.canvas.width = 320
    doc.canvas.height = 240
    doc.canvas.background_color = background
    asset = MediaAsset(
        kind="audio",
        locator=str(audio),
        source_duration_tick=seconds_to_tick(0.60),
    )
    doc.media.append(asset)
    doc.playlist.entries.append(
        SongInstance(
            asset_id=asset.asset_id,
            source_out_tick=asset.source_duration_tick,
            display_title="Circular Test",
            display_artist="SOL",
        )
    )
    track = doc.tracks[0]
    doc.layers.append(
        Layer(
            track_id=track.track_id,
            type="background",
            name="Solid",
            order=0,
            time_binding=TimeBinding(kind="album"),
            properties={"mode": "solid", "color": background},
        )
    )
    spectrum = make_spectrum_layer(
        track.track_id,
        1,
        preset_id="circular_neon",
    )
    spectrum.transform = Transform(
        x=0.20,
        y=0.10,
        width=0.60,
        height=0.80,
        rotation=12.0,
    )
    spectrum.opacity = 0.92
    doc.layers.append(spectrum)
    doc.validate()
    return doc


def _filter_graph(compiled) -> str:
    args = list(compiled.args)
    return args[args.index("-filter_complex") + 1]


def test_circular_registry_preset_and_property_validation():
    capability = SPECTRUM_CAPABILITIES["circular_spectrum"]
    assert capability.ffmpeg_filter == "showfreqs+geq"
    assert capability.supports_frequency_scale is True
    assert capability.supports_amplitude_scale is True
    assert capability.supports_inner_ratio is True
    props = apply_spectrum_preset({}, "circular_neon")
    assert props["style"] == "circular_spectrum"
    assert props["preset"] == "circular_neon"
    assert props["inner_ratio"] == pytest.approx(0.58)
    assert SPECTRUM_PRESETS["circular_neon"]["label"] == "Circular Neon"

    with pytest.raises(ValueError, match="0.15..0.85"):
        normalize_spectrum_properties(
            {"style": "circular_spectrum", "inner_ratio": 0.90}
        )
    with pytest.raises(ValueError, match="0.15..0.85"):
        circular_geometry(320, 240, 0.10)


def test_circular_polar_work_is_bounded_before_final_scale():
    assert circular_internal_side(3840, 2160) == MAX_INTERNAL_SIDE == 512
    assert circular_internal_side(200, 120) == 120
    chain = circular_spectrum_filter(
        width=1920,
        height=1080,
        color="0x4de8ff",
        frequency_scale="log",
        amplitude_scale="sqrt",
        inner_ratio=0.58,
    )
    assert "showfreqs=s=512x512" in chain
    assert "colors=white" in chain
    assert "format=gray" in chain
    assert "atan2(" in chain
    assert "hypot(" in chain
    assert "geq=lum=" in chain
    assert "colorkey=0x000000" in chain
    assert "colorchannelmixer=rr=" in chain
    assert "scale=1920:1080:force_original_aspect_ratio=decrease" in chain
    assert "pad=1920:1080" in chain


def test_compiler_uses_polar_chain_without_touching_master_audio(tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    doc = _circular_doc(tmp_path)
    compiled = FFmpegV2Compiler(ffmpeg).compile_video(
        doc,
        tmp_path / "circular.mp4",
        tmp_path / "work",
    )
    graph = _filter_graph(compiled)
    assert "asplit=2[aout][specaudio0]" in graph
    assert "[specaudio0]volume=1.350000,showfreqs" in graph
    assert "colors=white,format=gray" in graph
    assert "geq=lum='if(between(" in graph
    assert "atan2(" in graph
    assert "hypot(" in graph
    assert "colorkey=0x000000" in graph
    assert "colorchannelmixer=rr=" in graph
    assert "color=black@0" in graph
    assert "rotate=12.00000000*PI/180" in graph
    assert "[aout]volume" not in graph


def test_property_inspector_shows_inner_radius_only_for_circular():
    _app()
    inspector = PropertyInspector()
    track_id = ProjectDocument.new_empty("Inspector").tracks[0].track_id
    circular = make_spectrum_layer(track_id, 0, preset_id="circular_neon")
    inspector.set_layer(circular)
    assert not inspector.spectrum_inner_ratio.isHidden()
    assert inspector.spectrum_inner_ratio.value() == pytest.approx(0.58)

    bars = make_spectrum_layer(track_id, 1, preset_id="minimal_bars")
    inspector.set_layer(bars)
    assert inspector.spectrum_inner_ratio.isHidden()


def test_real_ffmpeg_circular_render_and_accurate_preview_parity(tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg tidak tersedia")
    filters = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for required in ("showfreqs", "geq", "colorkey", "overlay"):
        if required not in filters:
            pytest.skip(f"FFmpeg tidak memiliki filter {required}")

    doc = _circular_doc(tmp_path, background="#f5f5f5")
    output = tmp_path / "circular-real.mp4"
    compiler = FFmpegV2Compiler(ffmpeg)
    compiled = compiler.compile_video(doc, output, tmp_path / "work-video")
    subprocess.run(compiled.args, check=True, capture_output=True, text=True)
    assert output.exists() and output.stat().st_size > 0

    preview = tmp_path / "circular-preview.png"
    AccuratePreviewService(ffmpeg).render_frame(
        doc,
        seconds_to_tick(0.30),
        preview,
    )
    assert preview.exists() and preview.stat().st_size > 0

    image = Image.open(preview).convert("RGB")
    center = image.getpixel((160, 120))
    assert all(channel >= 225 for channel in center)
    cyan_pixels = 0
    for red, green, blue in image.getdata():
        if blue - red > 30 and green - red > 20:
            cyan_pixels += 1
    assert cyan_pixels >= 30

    final_frame = tmp_path / "circular-final.png"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            "0.30",
            "-i",
            str(output),
            "-frames:v",
            "1",
            str(final_frame),
        ],
        check=True,
    )
    psnr = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(preview),
            "-i",
            str(final_frame),
            "-lavfi",
            "psnr",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    match = re.search(r"average:([0-9.]+)", psnr.stderr + psnr.stdout)
    assert match and float(match.group(1)) >= 38.0


def test_circular_render_cancel_still_preserves_existing_output(tmp_path: Path):
    class CancelRunner:
        def run(self, *args, **kwargs):
            raise RenderCancelledV2("cancel-circular")

    doc = _circular_doc(tmp_path)
    destination = tmp_path / "existing.mp4"
    destination.write_bytes(b"OLD-CIRCULAR-OUTPUT")
    with pytest.raises(RenderCancelledV2, match="cancel-circular"):
        EditorRenderService(
            shutil.which("ffmpeg") or "ffmpeg",
            runner=CancelRunner(),
        ).render(doc, str(destination))
    assert destination.read_bytes() == b"OLD-CIRCULAR-OUTPUT"
