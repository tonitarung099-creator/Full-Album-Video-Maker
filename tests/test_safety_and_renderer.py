from __future__ import annotations

import io
import time
import urllib.error

import pytest

import full_album_maker.renderer as renderer_module
from full_album_maker.controller import ProjectController
from full_album_maker.key_pool import GeminiKeyPool
from full_album_maker.project import MediaItem, Project
from full_album_maker.renderer import FFmpegRenderer, RenderError
from full_album_maker.timeline import TimelineEngine, save_timeline


def test_controller_rejects_odd_resolution():
    project = Project()
    controller = ProjectController(project)
    with pytest.raises(ValueError, match="genap"):
        controller.execute("set_resolution", {"width": 1921, "height": 1080})


def test_controller_rejects_out_of_range_resolution():
    project = Project()
    controller = ProjectController(project)
    with pytest.raises(ValueError, match="di luar batas"):
        controller.execute("set_resolution", {"width": 100, "height": 100})


def test_renderer_requires_timeline(monkeypatch):
    monkeypatch.setattr(renderer_module, "ffmpeg_path", lambda: "ffmpeg")
    project = Project(
        videos=[MediaItem("v.mp4", 5.0)],
        audios=[MediaItem("a.wav", 5.0)],
    )
    with pytest.raises(RenderError, match="AUTO SUSUN TIMELINE"):
        FFmpegRenderer(project)


def test_renderer_rejects_stale_timeline(monkeypatch):
    monkeypatch.setattr(renderer_module, "ffmpeg_path", lambda: "ffmpeg")
    project = Project(
        videos=[MediaItem("v.mp4", 10.0)],
        audios=[MediaItem("a.wav", 10.0)],
    )
    plan = TimelineEngine().build(project)
    project.settings.fps = 60

    with pytest.raises(RenderError, match="tidak valid untuk proyek"):
        FFmpegRenderer(project, plan)


def test_renderer_rejects_tampered_source_range(monkeypatch):
    monkeypatch.setattr(renderer_module, "ffmpeg_path", lambda: "ffmpeg")
    project = Project(
        videos=[MediaItem("v.mp4", 10.0)],
        audios=[MediaItem("a.wav", 5.0)],
    )
    plan = TimelineEngine().build(project)
    plan.video_clips[0].source_out = 20.0
    plan.video_clips[0].timeline_out = 20.0

    with pytest.raises(RenderError, match="Timeline tidak valid"):
        FFmpegRenderer(project, plan)


def test_renderer_rejects_output_over_timeline_source(monkeypatch, tmp_path):
    monkeypatch.setattr(renderer_module, "ffmpeg_path", lambda: "ffmpeg")
    source = tmp_path / "source.mp4"
    audio = tmp_path / "a.wav"
    source.touch()
    audio.touch()

    project = Project(
        videos=[MediaItem(str(source), 10.0)],
        audios=[MediaItem(str(audio), 5.0)],
    )
    plan = TimelineEngine().build(project)
    renderer = FFmpegRenderer(project, plan)
    monkeypatch.setattr(renderer, "_ensure_encoder", lambda: None)

    with pytest.raises(RenderError, match="tidak boleh sama"):
        renderer.render(str(source))


def test_reverse_chunk_size_is_bounded(monkeypatch):
    monkeypatch.setattr(renderer_module, "ffmpeg_path", lambda: "ffmpeg")
    project = Project(
        videos=[MediaItem("v.mp4", 60.0)],
        audios=[MediaItem("a.wav", 300.0)],
    )
    project.settings.width = 3840
    project.settings.height = 2160
    project.settings.fps = 60
    project.settings.min_speed = 0.5
    project.settings.loop_mode = "pingpong"
    plan = TimelineEngine().build(project)
    renderer = FFmpegRenderer(project, plan)

    chunk_seconds = renderer._reverse_chunk_seconds()
    assert 0.25 <= chunk_seconds <= 5.0


def test_key_pool_403_cooldown_then_uses_next_key(monkeypatch, tmp_path):
    pool = GeminiKeyPool(tmp_path / "keys.dat")
    pool.add_keys([
        "test-key-00001-abcdefghijklmnopqrstuvwxyz",
        "test-key-00002-abcdefghijklmnopqrstuvwxyz",
    ])

    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout=90):
        calls.append(request.headers.get("X-goog-api-key"))
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                403,
                "Forbidden",
                hdrs=None,
                fp=io.BytesIO(b'{"error":{"message":"permission denied"}}'),
            )
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = pool.request_json("https://example.invalid", {"x": 1})

    assert result == {"ok": True}
    assert len(calls) == 2
    assert pool.records[0].enabled is True
    assert pool.records[0].cooldown_until > time.time()
    assert pool.records[1].failures == 0


def test_key_pool_401_disables_only_bad_key(monkeypatch, tmp_path):
    pool = GeminiKeyPool(tmp_path / "keys.dat")
    pool.add_keys([
        "test-key-00001-abcdefghijklmnopqrstuvwxyz",
        "test-key-00002-abcdefghijklmnopqrstuvwxyz",
    ])

    count = {"n": 0}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout=90):
        count["n"] += 1
        if count["n"] == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                hdrs=None,
                fp=io.BytesIO(b'{"error":{"message":"bad key"}}'),
            )
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert pool.request_json("https://example.invalid", {}) == {"ok": True}
    assert pool.records[0].enabled is False
    assert pool.records[1].enabled is True


def test_controller_optimize_and_move_audio():
    project = Project(
        videos=[MediaItem("video.mp4", 60.0)],
        audios=[
            MediaItem("02 Song.mp3", 60.0),
            MediaItem("01 Song.mp3", 60.0),
        ],
    )
    controller = ProjectController(project)

    optimized = controller.execute("optimize_youtube", {"quality": "1080p"})
    assert optimized["summary"]["settings"]["codec"] == "h264"
    assert optimized["summary"]["settings"]["video_bitrate"] == "12M"

    controller.execute("move_audio", {"from_position": 2, "to_position": 1})
    assert project.audios[0].name == "01 Song.mp3"


def test_controller_quality_validation():
    project = Project()
    controller = ProjectController(project)
    with pytest.raises(ValueError, match="video_bitrate"):
        controller.execute(
            "set_quality",
            {"video_bitrate": "999M", "audio_bitrate": "320k"},
        )


def test_renderer_can_load_valid_timeline_json(monkeypatch, tmp_path):
    monkeypatch.setattr(renderer_module, "ffmpeg_path", lambda: "ffmpeg")
    project = Project(
        videos=[MediaItem("v.mp4", 10.0)],
        audios=[MediaItem("a.wav", 10.0)],
    )
    plan = TimelineEngine().build(project)
    path = save_timeline(str(tmp_path / "Timeline_Auto.json"), plan)

    renderer = FFmpegRenderer(project, path)
    assert renderer.timeline.to_dict() == plan.to_dict()
