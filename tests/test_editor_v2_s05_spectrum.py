from __future__ import annotations

from pathlib import Path
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
from full_album_maker.editor_session import EditorSession
from full_album_maker.preview_service import AccuratePreviewService
from full_album_maker.render_graph import FFmpegV2Compiler, RenderCompileError
from full_album_maker.spectrum_feature import (
    SPECTRUM_CAPABILITIES,
    SPECTRUM_PRESETS,
    apply_spectrum_preset,
    make_dynamic_title_layer,
    make_spectrum_layer,
    normalize_spectrum_properties,
)


def _audio(tmp_path: Path, *, name: str = "tone.wav", frequency: int | None = 440, duration: float = 0.55) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg tidak tersedia")
    path = tmp_path / name
    source = "anullsrc=r=48000:cl=stereo" if frequency is None else f"sine=frequency={frequency}:duration={duration}"
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", source]
    if frequency is None:
        command += ["-t", str(duration)]
    command += ["-ar", "48000", "-ac", "2", str(path)]
    subprocess.run(command, check=True)
    return path


def _doc(tmp_path: Path, *, style: str = "bars", background: str = "#f5f5f5", frequency: int | None = 440) -> ProjectDocument:
    audio = _audio(tmp_path, name=f"{style}-{frequency}.wav", frequency=frequency)
    doc = ProjectDocument.new_empty("S05")
    doc.canvas.width = 320
    doc.canvas.height = 240
    doc.canvas.background_color = background
    asset = MediaAsset(kind="audio", locator=str(audio), source_duration_tick=seconds_to_tick(0.55))
    doc.media.append(asset)
    doc.playlist.entries.append(
        SongInstance(
            asset_id=asset.asset_id,
            source_out_tick=asset.source_duration_tick,
            display_title="Lagu Uji",
            display_artist="Artis Uji",
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
    spectrum = make_spectrum_layer(track.track_id, 1, preset_id="minimal_bars")
    spectrum.properties.update(
        normalize_spectrum_properties(
            {
                **spectrum.properties,
                "style": style,
                "color": "#17bfe6",
                "gain": 1.7,
                "mirror": style == "waveform",
            }
        )
    )
    spectrum.transform = Transform(x=0.05, y=0.58, width=0.90, height=0.34)
    doc.layers.append(spectrum)
    doc.validate()
    return doc


def _filters(compiled) -> str:
    args = list(compiled.args)
    return args[args.index("-filter_complex") + 1]


def test_registry_exposes_proven_spectrum_styles_and_presets():
    assert tuple(SPECTRUM_CAPABILITIES) == (
        "bars",
        "spectrum_line",
        "waveform",
        "stereo_waveform",
        "circular_spectrum",
    )
    assert SPECTRUM_CAPABILITIES["circular_spectrum"].supports_inner_ratio is True
    assert {
        "minimal_bars",
        "neon_bars",
        "bass_bars",
        "thin_line",
        "mirror",
        "circular_neon",
    } <= set(SPECTRUM_PRESETS)
    with pytest.raises(ValueError, match="belum didukung"):
        normalize_spectrum_properties({"style": "future_3d_spectrum"})


def test_spectrum_preset_normalizes_and_keeps_visual_gain_only():
    props = apply_spectrum_preset({}, "neon_bars")
    assert props["style"] == "bars"
    assert props["gain"] > 1.0
    assert props["mirror"] is True


def test_session_adds_album_bound_spectrum_and_dynamic_title_with_undo():
    doc = ProjectDocument.new_empty("S05 session")
    session = EditorSession(doc)
    session.add_spectrum_layer()
    spectrum = session.selected_layer()
    assert spectrum is not None and spectrum.type == "spectrum"
    assert spectrum.time_binding.kind == "album"
    session.add_dynamic_title_layer()
    title = session.selected_layer()
    assert title is not None and title.type == "song_title"
    assert title.properties["template"] == "{title}\n{artist}"
    session.undo()
    assert all(layer.type != "song_title" for layer in session.snapshot().layers)


def test_compiler_uses_audio_split_visual_gain_colorkey_and_master_audio(tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    doc = _doc(tmp_path, style="bars")
    compiled = FFmpegV2Compiler(ffmpeg).compile_video(doc, tmp_path / "out.mp4", tmp_path / "work")
    graph = _filters(compiled)
    assert "asplit=2[aout][specaudio0]" in graph
    assert "[specaudio0]volume=1.700000,showfreqs" in graph
    assert "colorkey=0x000000" in graph
    assert "[aout]volume" not in graph
    assert "[aout]" in compiled.args


def test_dynamic_title_writes_song_metadata_per_song_id(tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    doc = _doc(tmp_path, style="bars")
    title = make_dynamic_title_layer(doc.tracks[0].track_id, 2)
    title.properties["font_size"] = 24
    doc.layers.append(title)
    compiled = FFmpegV2Compiler(ffmpeg).compile_video(doc, tmp_path / "out.mp4", tmp_path / "work")
    title_files = [path for path in compiled.text_files if path.name.startswith("song-title-")]
    assert len(title_files) == 1
    assert title_files[0].read_text(encoding="utf-8") == "Lagu Uji\nArtis Uji"
    assert "drawtext=" in _filters(compiled)


@pytest.mark.parametrize(
    "style,background,frequency",
    [
        ("bars", "#f5f5f5", 90),
        ("spectrum_line", "#101114", 440),
        ("waveform", "#f5f5f5", 1200),
        ("stereo_waveform", "#101114", 660),
    ],
)
def test_real_ffmpeg_all_release_spectrum_styles(style: str, background: str, frequency: int, tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg tidak tersedia")
    filters = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, check=True).stdout
    if "showfreqs" not in filters or "showwaves" not in filters or "colorkey" not in filters:
        pytest.skip("FFmpeg visualizer filter tidak lengkap")
    doc = _doc(tmp_path, style=style, background=background, frequency=frequency)
    output = tmp_path / f"{style}.mp4"
    compiled = FFmpegV2Compiler(ffmpeg).compile_video(doc, output, tmp_path / f"work-{style}")
    subprocess.run(compiled.args, check=True, capture_output=True, text=True)
    assert output.exists() and output.stat().st_size > 0


def test_real_silence_spectrum_and_accurate_preview_use_same_compiler(tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg tidak tersedia")
    doc = _doc(tmp_path, style="bars", background="#eeeeee", frequency=None)
    output = tmp_path / "silence.mp4"
    compiler = FFmpegV2Compiler(ffmpeg)
    subprocess.run(compiler.compile_video(doc, output, tmp_path / "work-video").args, check=True, capture_output=True, text=True)
    preview = tmp_path / "preview.png"
    AccuratePreviewService(ffmpeg).render_frame(doc, seconds_to_tick(0.2), preview)
    assert output.exists() and preview.exists()


def test_background_s05_motion_and_freeze_are_compiled(tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    doc = _doc(tmp_path, style="bars")
    background = doc.layers[0]
    background.properties["motion"] = "zoom_in"
    background.properties["playback"] = "freeze"
    # Solid backgrounds do not need playback media, but motion/playback properties
    # remain persisted and harmless. Unsupported values must still fail on asset backgrounds.
    compiled = FFmpegV2Compiler(ffmpeg).compile_video(doc, tmp_path / "out.mp4", tmp_path / "work")
    assert compiled.render_plan.duration_tick == seconds_to_tick(0.55)


def test_invalid_spectrum_style_fails_closed_before_render(tmp_path: Path):
    doc = _doc(tmp_path, style="bars")
    spectrum = next(layer for layer in doc.layers if layer.type == "spectrum")
    spectrum.properties["style"] = "future_3d_spectrum"
    with pytest.raises(RenderCompileError, match="belum didukung"):
        FFmpegV2Compiler(shutil.which("ffmpeg") or "ffmpeg").compile_video(
            doc, tmp_path / "x.mp4", tmp_path / "work"
        )
