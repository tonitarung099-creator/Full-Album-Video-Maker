from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageStat
from PySide6.QtWidgets import QApplication
import pytest

from full_album_maker.editor_controller import EditorController
from full_album_maker.editor_models import (
    MediaAsset,
    ProjectDocument,
    SongInstance,
    seconds_to_tick,
)
from full_album_maker.preview_service import AccuratePreviewService
from full_album_maker.song_visuals import (
    SongVisualAssignmentService,
    make_song_visual_layer,
    normalize_song_visual_properties,
)
from full_album_maker.v13_render_graph import V13FFmpegCompiler
from full_album_maker.v13_workspace import V13EditorWorkspace


def _ffmpeg() -> str:
    value = shutil.which("ffmpeg")
    if not value:
        pytest.skip("FFmpeg tidak tersedia")
    return value


def _audio(path: Path, frequency: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            _ffmpeg(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:duration=0.70",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(path),
        ],
        check=True,
    )
    return path


def _image(path: Path, color: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            _ffmpeg(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x240:d=0.1",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
    )
    return path


def _video(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            _ffmpeg(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=#3050ff:s=320x240:r=30:d=0.30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


def _doc(tmp_path: Path, *, include_video: bool = False) -> tuple[ProjectDocument, list[SongInstance], list[MediaAsset]]:
    doc = ProjectDocument.new_empty("v1.3 Song Visual")
    doc.canvas.width = 320
    doc.canvas.height = 240
    duration = seconds_to_tick(0.70)

    visuals: list[MediaAsset] = []
    for index, (frequency, color) in enumerate(((330, "#ff2020"), (550, "#20ee30")), start=1):
        audio_path = _audio(tmp_path / f"song-{index}.wav", frequency)
        image_path = _image(tmp_path / f"Song {index}.png", color)
        audio = MediaAsset(
            kind="audio",
            locator=str(audio_path),
            original_name=f"Song {index}.wav",
            source_duration_tick=duration,
        )
        image = MediaAsset(
            kind="image",
            locator=str(image_path),
            original_name=f"Song {index}.png",
        )
        doc.media.extend([audio, image])
        visuals.append(image)
        doc.playlist.entries.append(
            SongInstance(
                asset_id=audio.asset_id,
                source_out_tick=duration,
                display_title=f"Song {index}",
                display_artist=f"Artist {index}",
                visual_asset_id=image.asset_id,
            )
        )

    if include_video:
        video_path = _video(tmp_path / "Song 2.mp4")
        video = MediaAsset(
            kind="video",
            locator=str(video_path),
            original_name="Song 2.mp4",
            source_duration_tick=seconds_to_tick(0.30),
        )
        doc.media.append(video)
        visuals.append(video)

    visual_track = next(track for track in doc.tracks if track.kind == "visual")
    layer = make_song_visual_layer(visual_track.track_id, 5)
    layer.properties = normalize_song_visual_properties(
        {
            "fit": "fill",
            "image_motion": "static",
            "video_playback": "loop",
            "transition": "fade",
            "transition_seconds": 0.20,
        }
    )
    doc.layers.append(layer)
    doc.validate()
    return doc, list(doc.playlist.entries), visuals


def _mean_rgb(path: Path) -> tuple[float, float, float]:
    with Image.open(path).convert("RGB") as image:
        values = ImageStat.Stat(image).mean
    return float(values[0]), float(values[1]), float(values[2])


def _extract_frame(video: Path, time_seconds: float, output: Path) -> None:
    subprocess.run(
        [
            _ffmpeg(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{time_seconds:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            str(output),
        ],
        check=True,
    )


def test_song_visual_properties_are_bounded_and_cut_disables_duration():
    props = normalize_song_visual_properties(
        {
            "fit": "fit",
            "image_motion": "pan_left",
            "video_playback": "freeze",
            "transition": "cut",
            "transition_seconds": 4.0,
        }
    )
    assert props["transition"] == "cut"
    assert props["transition_seconds"] == 0.0
    with pytest.raises(ValueError, match="0..5"):
        normalize_song_visual_properties({"transition_seconds": 99})
    with pytest.raises(ValueError, match="Transisi"):
        normalize_song_visual_properties({"transition": "random_magic"})


def test_bulk_song_visual_assignment_is_one_revision_and_one_undo(tmp_path: Path):
    doc, songs, visuals = _doc(tmp_path)
    for song in doc.playlist.entries:
        song.visual_asset_id = None
    controller = EditorController(doc)
    start = controller.revision
    commands = SongVisualAssignmentService.bulk_commands(
        controller.snapshot(),
        [songs[0].song_id, songs[1].song_id, songs[0].song_id],
        visuals[0].asset_id,
    )
    assert len(commands) == 2
    controller.dispatch(commands)
    assert controller.revision == start + 1
    changed = controller.snapshot().song_map()
    assert changed[songs[0].song_id].visual_asset_id == visuals[0].asset_id
    assert changed[songs[1].song_id].visual_asset_id == visuals[0].asset_id
    controller.undo()
    reverted = controller.snapshot().song_map()
    assert reverted[songs[0].song_id].visual_asset_id is None
    assert reverted[songs[1].song_id].visual_asset_id is None


def test_song_visual_auto_match_is_exact_and_fail_closed_on_duplicate(tmp_path: Path):
    doc, songs, _ = _doc(tmp_path)
    for song in doc.playlist.entries:
        song.visual_asset_id = None
    duplicate_path = _image(tmp_path / "Song 1.jpg", "#aaaaaa")
    doc.media.append(
        MediaAsset(kind="image", locator=str(duplicate_path), original_name="Song 1.jpg")
    )
    report = SongVisualAssignmentService.auto_match(doc)
    assert songs[0].song_id in report.ambiguous_song_ids
    assert songs[0].song_id not in report.matches
    assert songs[1].song_id in report.matches


def test_v13_compiler_keeps_existing_graph_and_adds_transition_filters(tmp_path: Path):
    doc, _, _ = _doc(tmp_path)
    layer = next(item for item in doc.layers if item.type == "song_visual")
    layer.properties = normalize_song_visual_properties(
        {**layer.properties, "transition": "slide_left", "transition_seconds": 0.2}
    )
    compiled = V13FFmpegCompiler(_ffmpeg()).compile_video(
        doc,
        tmp_path / "compiled.mp4",
        tmp_path / "work-compiled",
    )
    args = list(compiled.args)
    assert args.count("-i") >= 5  # canvas + 2 audio + 2 per-song visuals
    graph = ""
    if "-filter_complex" in args:
        graph = args[args.index("-filter_complex") + 1]
    else:
        script = Path(args[args.index("-/filter_complex") + 1])
        graph = script.read_text(encoding="utf-8")
    assert "svsrc" in graph
    assert "overlay=x='if(lt(t," in graph
    assert "[v0]" in graph
    assert "[aout]" in graph


def test_real_ffmpeg_song_images_switch_and_accurate_preview_matches(tmp_path: Path):
    doc, _, _ = _doc(tmp_path)
    output = tmp_path / "song-visual-final.mp4"
    compiled = V13FFmpegCompiler(_ffmpeg()).compile_video(
        doc,
        output,
        tmp_path / "work-final",
    )
    completed = subprocess.run(compiled.args, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert output.exists() and output.stat().st_size > 0

    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _extract_frame(output, 0.25, first)
    _extract_frame(output, 1.05, second)
    r1, g1, b1 = _mean_rgb(first)
    r2, g2, b2 = _mean_rgb(second)
    assert r1 > g1 * 1.8 and r1 > b1 * 1.8
    assert g2 > r2 * 1.5 and g2 > b2 * 1.5

    preview = tmp_path / "preview-second.png"
    AccuratePreviewService(ffmpeg=_ffmpeg()).render_frame(
        doc,
        seconds_to_tick(1.05),
        preview,
    )
    pr, pg, pb = _mean_rgb(preview)
    assert pg > pr * 1.5 and pg > pb * 1.5


def test_real_ffmpeg_video_visual_loop_and_freeze_compile(tmp_path: Path):
    doc, songs, visuals = _doc(tmp_path, include_video=True)
    video = next(asset for asset in visuals if asset.kind == "video")
    songs[1].visual_asset_id = video.asset_id
    layer = next(item for item in doc.layers if item.type == "song_visual")
    layer.properties = normalize_song_visual_properties(
        {**layer.properties, "video_playback": "loop", "transition": "cut"}
    )
    output = tmp_path / "video-loop.mp4"
    compiled = V13FFmpegCompiler(_ffmpeg()).compile_video(
        doc,
        output,
        tmp_path / "work-video",
    )
    assert "-stream_loop" in compiled.args
    completed = subprocess.run(compiled.args, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert output.exists() and output.stat().st_size > 0

    layer.properties = normalize_song_visual_properties(
        {**layer.properties, "video_playback": "freeze"}
    )
    frozen = V13FFmpegCompiler(_ffmpeg()).compile_video(
        doc,
        tmp_path / "video-freeze.mp4",
        tmp_path / "work-freeze",
    )
    graph = ""
    args = list(frozen.args)
    if "-filter_complex" in args:
        graph = args[args.index("-filter_complex") + 1]
    else:
        graph = Path(args[args.index("-/filter_complex") + 1]).read_text(encoding="utf-8")
    assert "trim=end_frame=1" in graph


def test_v13_workspace_exposes_visual_lagu_tab(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    doc, _, _ = _doc(tmp_path / "ui")
    workspace = V13EditorWorkspace(
        doc,
        custom_template_root=tmp_path / "templates",
        template_preview_enabled=False,
    )
    try:
        names = [workspace.tabs.tabText(index) for index in range(workspace.tabs.count())]
        assert "Cover" in names
        assert "Visual Lagu" in names
        assert workspace.song_visual_manager_v13.visual_combo.count() >= 2
    finally:
        workspace.close()
        workspace.deleteLater()
        app.processEvents()
