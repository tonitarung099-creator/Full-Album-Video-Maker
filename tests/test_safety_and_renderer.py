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


def test_renderer_rejects_no_loop_when_video_too_short(monkeypatch, tmp_path):
    monkeypatch.setattr(renderer_module, "ffmpeg_path", lambda: "ffmpeg")
    project = Project(
        videos=[MediaItem(str(tmp_path / "v.mp4"), 5.0)],
        audios=[MediaItem(str(tmp_path / "a.wav"), 20.0)],
    )
    project.settings.min_speed = 0.5
    project.settings.loop_mode = "none"
    renderer = FFmpegRenderer(project)
    monkeypatch.setattr(renderer, "_ensure_encoder", lambda: None)

    with pytest.raises(RenderError, match="mode loop dimatikan"):
        renderer.render(str(tmp_path / "out.mp4"))


def test_renderer_rejects_output_over_source(monkeypatch, tmp_path):
    monkeypatch.setattr(renderer_module, "ffmpeg_path", lambda: "ffmpeg")
    source = tmp_path / "source.mp4"
    project = Project(
        videos=[MediaItem(str(source), 10.0)],
        audios=[MediaItem(str(tmp_path / "a.wav"), 5.0)],
    )
    renderer = FFmpegRenderer(project)
    monkeypatch.setattr(renderer, "_ensure_encoder", lambda: None)

    with pytest.raises(RenderError, match="tidak boleh sama"):
        renderer.render(str(source))


def test_pingpong_guard_prevents_huge_reverse_buffer(monkeypatch):
    monkeypatch.setattr(renderer_module, "ffmpeg_path", lambda: "ffmpeg")
    project = Project(
        videos=[MediaItem("v.mp4", 60.0)],
        audios=[MediaItem("a.wav", 300.0)],
    )
    project.settings.width = 3840
    project.settings.height = 2160
    project.settings.fps = 60
    project.settings.min_speed = 0.5
    renderer = FFmpegRenderer(project)

    assert renderer._pingpong_is_safe() is False


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
