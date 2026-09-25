from __future__ import annotations

import os
import subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import full_album_maker.renderer as renderer_module
import full_album_maker.ui as ui_module
from full_album_maker.controller import ProjectController
from full_album_maker.media import probe_duration
from full_album_maker.paths import ffmpeg_path, ffprobe_path
from full_album_maker.project import MediaItem, Project
from full_album_maker.renderer import FFmpegRenderer, RenderError
from full_album_maker.timeline import TimelineEngine
from full_album_maker.ui import MainWindow


def _run(cmd):
    subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _encoder_output(ffmpeg: str) -> str:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return (result.stdout or "") + "\n" + (result.stderr or "")


def test_renderer_rejects_output_over_unused_project_source(monkeypatch, tmp_path):
    monkeypatch.setattr(renderer_module, "ffmpeg_path", lambda: "ffmpeg")
    used_video = tmp_path / "used.mp4"
    unused_video = tmp_path / "unused.mp4"
    audio = tmp_path / "song.wav"
    for item in (used_video, unused_video, audio):
        item.touch()

    project = Project(
        videos=[
            MediaItem(str(used_video), 10.0),
            MediaItem(str(unused_video), 10.0),
        ],
        audios=[MediaItem(str(audio), 1.0)],
    )
    project.settings.auto_speed = False
    project.settings.manual_speed = 1.0
    plan = TimelineEngine().build(project)
    assert all(clip.source != str(unused_video) for clip in plan.video_clips)

    renderer = FFmpegRenderer(project, plan)
    monkeypatch.setattr(renderer, "_ensure_encoder", lambda: None)

    with pytest.raises(RenderError, match="file sumber proyek"):
        renderer.render(str(unused_video))


def test_corrupt_project_is_rejected_before_replacing_active_state(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    bad = tmp_path / "broken.json"
    bad.write_text(
        '{"version":1,"videos":[{"path":"broken.mp4","duration":"oops"}],"audios":[]}',
        encoding="utf-8",
    )

    window = MainWindow()
    original = Project(
        videos=[MediaItem("keep.mp4", 10.0)],
        audios=[MediaItem("keep.wav", 10.0)],
    )
    window.project = original
    window.controller = ProjectController(original)

    monkeypatch.setattr(
        ui_module.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(bad), "Full Album Project (*.json)"),
    )
    errors = []
    window._error = errors.append

    window.load_project_file()

    assert errors
    assert window.project is original
    assert window.controller.project is original
    window.close()
    app.processEvents()


def test_locked_speed_above_one_survives_loop_change():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.project.settings.auto_speed = False
    window.project.settings.manual_speed = 1.5
    window.project.settings.loop_mode = "loop"
    window._sync_controls_from_project()

    assert window.min_speed.value() == pytest.approx(1.5)

    target = window.loop_mode.findData("pingpong")
    window.loop_mode.setCurrentIndex(target)
    app.processEvents()

    assert window.project.settings.auto_speed is False
    assert window.project.settings.manual_speed == pytest.approx(1.5)
    assert window.project.settings.loop_mode == "pingpong"
    window.close()


def test_render_busy_guard_blocks_second_start_and_refresh(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])

    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    video.touch()
    audio.touch()

    window = MainWindow()
    project = Project(
        videos=[MediaItem(str(video), 10.0)],
        audios=[MediaItem(str(audio), 10.0)],
    )
    window.project = project
    window.controller = ProjectController(project)
    window.apply_timeline_plan(TimelineEngine().build(project))

    monkeypatch.setattr(
        ui_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(tmp_path / "out.mp4"), "MP4 (*.mp4)"),
    )

    starts = {"count": 0}

    class FakeThread:
        def __init__(self, target, daemon=False):
            self.target = target
            self.daemon = daemon

        def start(self):
            starts["count"] += 1

    monkeypatch.setattr(ui_module.threading, "Thread", FakeThread)

    window.render()
    assert window.render_busy is True
    assert starts["count"] == 1

    window.refresh()
    assert window.render_btn.isEnabled() is False

    window.render()
    assert starts["count"] == 1
    window.close()
    app.processEvents()


def test_mp3_probe_uses_decoded_gapless_duration(tmp_path):
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        pytest.skip("FFmpeg belum tersedia.")

    audio = tmp_path / "one_second.mp3"
    _run([
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "sine=frequency=440:sample_rate=44100:duration=1",
        "-c:a", "libmp3lame", "-q:a", "2", str(audio),
    ])

    duration = probe_duration(str(audio), "audio")
    assert 0.995 <= duration <= 1.005


def test_video_probe_ignores_longer_embedded_audio(tmp_path):
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        pytest.skip("FFmpeg belum tersedia.")

    media = tmp_path / "video_1s_audio_3s.mp4"
    _run([
        ffmpeg, "-y",
        "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=25:d=1",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "mpeg4", "-c:a", "aac",
        str(media),
    ])

    duration = probe_duration(str(media), "video")
    assert 0.95 <= duration <= 1.05


def test_slowmo_render_video_stays_aligned_with_audio(tmp_path):
    ffmpeg = ffmpeg_path()
    ffprobe = ffprobe_path()
    if not ffmpeg or not ffprobe or "libx264" not in _encoder_output(ffmpeg):
        pytest.skip("FFmpeg/FFprobe GPL dengan libx264 belum tersedia.")

    video = tmp_path / "source.avi"
    audio = tmp_path / "master.wav"
    output = tmp_path / "aligned.mp4"

    _run([
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "testsrc=size=160x120:rate=30:duration=0.7",
        "-an", "-c:v", "mpeg4", str(video),
    ])
    _run([
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "sine=frequency=330:sample_rate=48000:duration=1",
        "-c:a", "pcm_s16le", str(audio),
    ])

    project = Project(
        videos=[MediaItem(str(video), probe_duration(str(video), "video"))],
        audios=[MediaItem(str(audio), probe_duration(str(audio), "audio"))],
    )
    project.settings.auto_speed = False
    project.settings.manual_speed = 0.7
    project.settings.loop_mode = "none"
    project.settings.width = 160
    project.settings.height = 120
    project.settings.fps = 30
    project.settings.codec = "h264"
    project.settings.video_bitrate = "300k"
    project.settings.audio_bitrate = "96k"

    plan = TimelineEngine().build(project)
    assert plan.duration == pytest.approx(1.0, abs=0.01)

    FFmpegRenderer(project, plan).render(str(output))

    probe = subprocess.run(
        [
            ffprobe, "-v", "error", "-show_entries", "stream=codec_type,duration",
            "-of", "json", str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    import json
    streams = json.loads(probe.stdout)["streams"]
    durations = {
        stream["codec_type"]: float(stream["duration"])
        for stream in streams
        if stream.get("duration") not in {None, "N/A"}
    }
    assert abs(durations["video"] - durations["audio"]) <= 0.05
    assert 0.95 <= durations["video"] <= 1.05
