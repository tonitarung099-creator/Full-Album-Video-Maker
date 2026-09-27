from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from PIL import Image
import pytest

from full_album_maker.album_visuals import (
    format_duration_tick,
    make_playlist_visual_layer,
    make_progress_layer,
    make_song_cover_layer,
    make_song_time_layer,
    make_vinyl_layer,
    normalize_visual_properties,
)
from full_album_maker.editor_models import MediaAsset, ProjectDocument, SongInstance, seconds_to_tick
from full_album_maker.editor_session import EditorSession
from full_album_maker.preview_service import AccuratePreviewService
from full_album_maker.render_graph import FFmpegV2Compiler


def _make_audio(tmp_path: Path, name: str, frequency: int) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg tidak tersedia")
    path = tmp_path / name
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
            f"sine=frequency={frequency}:duration=0.55",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(path),
        ],
        check=True,
    )
    return path


def _make_cover(tmp_path: Path, name: str, color: str) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg tidak tersedia")
    path = tmp_path / name
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
            f"color=c={color}:s=128x128:d=0.1",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
    )
    return path


def _doc(tmp_path: Path) -> ProjectDocument:
    doc = ProjectDocument.new_empty("S06")
    doc.canvas.width = 320
    doc.canvas.height = 240
    doc.canvas.background_color = "#11151b"
    track = doc.tracks[0]

    for index, (frequency, cover_color) in enumerate(((330, "#ff355e"), (550, "#36d399")), start=1):
        audio_path = _make_audio(tmp_path, f"song-{index}.wav", frequency)
        cover_path = _make_cover(tmp_path, f"cover-{index}.png", cover_color)
        audio = MediaAsset(kind="audio", locator=str(audio_path), source_duration_tick=seconds_to_tick(0.55))
        cover = MediaAsset(kind="image", locator=str(cover_path), original_name=cover_path.name)
        doc.media.extend([audio, cover])
        doc.playlist.entries.append(
            SongInstance(
                asset_id=audio.asset_id,
                source_out_tick=audio.source_duration_tick,
                display_title=f"Lagu {index}",
                display_artist=f"Artis {index}",
                cover_asset_id=cover.asset_id,
            )
        )

    cover_layer = make_song_cover_layer(track.track_id, 0)
    vinyl_layer = make_vinyl_layer(track.track_id, 1)
    playlist_layer = make_playlist_visual_layer(track.track_id, 2)
    progress_layer = make_progress_layer(track.track_id, 3)
    time_layer = make_song_time_layer(track.track_id, 4)
    playlist_layer.properties["font_size"] = 18
    playlist_layer.properties["max_items"] = 2
    time_layer.properties["font_size"] = 18
    doc.layers.extend([cover_layer, vinyl_layer, playlist_layer, progress_layer, time_layer])
    doc.validate()
    return doc


def test_visual_factories_validate_release_properties():
    assert format_duration_tick(seconds_to_tick(65)) == "1:05"
    assert normalize_visual_properties("song_cover", {})["fit"] == "fill"
    assert normalize_visual_properties("vinyl", {})["spin_seconds"] == pytest.approx(8.0)
    assert normalize_visual_properties("playlist_visual", {})["max_items"] == 8
    assert normalize_visual_properties("progress", {})["mode"] == "song"
    assert normalize_visual_properties("song_time", {})["mode"] == "song"
    with pytest.raises(ValueError, match="1..60"):
        normalize_visual_properties("vinyl", {"spin_seconds": 0.2})
    with pytest.raises(ValueError, match="1..30"):
        normalize_visual_properties("playlist_visual", {"max_items": 99})


def test_session_adds_s06_layers_and_progress_is_one_undo_transaction():
    doc = ProjectDocument.new_empty("S06 session")
    session = EditorSession(doc)
    session.add_song_cover_layer()
    assert session.selected_layer().type == "song_cover"
    session.add_vinyl_layer()
    assert session.selected_layer().type == "vinyl"
    session.add_playlist_visual_layer()
    assert session.selected_layer().type == "playlist_visual"
    before = len(session.snapshot().layers)
    session.add_progress_visuals()
    assert len(session.snapshot().layers) == before + 2
    assert {layer.type for layer in session.snapshot().layers} >= {"progress", "song_time"}
    session.undo()
    assert len(session.snapshot().layers) == before


def test_compiler_contains_dynamic_cover_playlist_vinyl_progress_and_time(tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    doc = _doc(tmp_path)
    compiled = FFmpegV2Compiler(ffmpeg).compile_video(doc, tmp_path / "album.mp4", tmp_path / "work")
    args = list(compiled.args)
    graph = args[args.index("-filter_complex") + 1]
    assert "cover" in graph
    assert "geq=r=" in graph
    assert "playlist" in graph
    assert "progress" in graph
    assert "songtime" in graph
    assert "drawtext=" in graph
    playlist_files = [path for path in compiled.text_files if path.name.startswith("playlist-")]
    assert [path.read_text(encoding="utf-8") for path in playlist_files] == ["01. Lagu 1", "02. Lagu 2"]


def test_real_ffmpeg_s06_visual_album_and_accurate_preview(tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/ffprobe tidak tersedia")
    filters = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, check=True
    ).stdout
    if "drawtext" not in filters or "geq" not in filters or "overlay" not in filters:
        pytest.skip("FFmpeg filter S06 tidak lengkap")

    doc = _doc(tmp_path)
    output = tmp_path / "s06.mp4"
    compiler = FFmpegV2Compiler(ffmpeg)
    compiled = compiler.compile_video(doc, output, tmp_path / "work-video")
    subprocess.run(compiled.args, check=True, capture_output=True, text=True)
    assert output.exists() and output.stat().st_size > 0

    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "json",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert '"codec_type": "video"' in probe
    assert '"codec_type": "audio"' in probe

    first_preview = tmp_path / "s06-preview-first.png"
    second_preview = tmp_path / "s06-preview-second.png"
    AccuratePreviewService(ffmpeg).render_frame(doc, seconds_to_tick(0.25), first_preview)
    AccuratePreviewService(ffmpeg).render_frame(doc, seconds_to_tick(0.75), second_preview)
    assert first_preview.exists() and second_preview.exists()

    # Pixel ini berada di area aman cover (jauh dari vinyl/playlist). Ia harus
    # berubah dari dominan merah pada lagu pertama menjadi dominan hijau pada
    # lagu kedua. Ini membuktikan pemilihan cover mengikuti song_id aktif.
    first_rgb = Image.open(first_preview).convert("RGB").getpixel((60, 80))
    second_rgb = Image.open(second_preview).convert("RGB").getpixel((60, 80))
    assert first_rgb[0] > first_rgb[1]
    assert second_rgb[1] > second_rgb[0]


def test_album_mode_progress_and_time_render(tmp_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg tidak tersedia")
    doc = _doc(tmp_path)
    for layer in doc.layers:
        if layer.type in {"progress", "song_time"}:
            layer.properties["mode"] = "album"
    output = tmp_path / "album-mode.mp4"
    compiled = FFmpegV2Compiler(ffmpeg).compile_video(doc, output, tmp_path / "work-album")
    subprocess.run(compiled.args, check=True, capture_output=True, text=True)
    assert output.exists() and output.stat().st_size > 0
