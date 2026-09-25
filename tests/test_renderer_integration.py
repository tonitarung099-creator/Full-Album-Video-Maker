from __future__ import annotations

import subprocess

import pytest

from full_album_maker.media import probe_duration
from full_album_maker.paths import ffmpeg_path, ffprobe_path
from full_album_maker.project import MediaItem, Project
from full_album_maker.renderer import FFmpegRenderer


def _run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_real_ffmpeg_full_album_render(tmp_path):
    ffmpeg = ffmpeg_path()
    ffprobe = ffprobe_path()
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg portable belum tersedia.")

    encoders = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    encoders = (encoders.stdout or "") + "\n" + (encoders.stderr or "")
    if "libx264" not in encoders:
        pytest.skip("FFmpeg lokal tidak punya libx264.")

    video = tmp_path / "source.avi"
    audio1 = tmp_path / "01 Intro.wav"
    audio2 = tmp_path / "02 Lanjut.wav"
    output = tmp_path / "FULL_ALBUM_FINAL.mp4"

    _run([
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", "color=c=blue:s=320x240:r=24:d=0.5",
        "-an", "-c:v", "mpeg4",
        str(video),
    ])
    _run([
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", "sine=frequency=440:sample_rate=48000:duration=1",
        "-c:a", "pcm_s16le",
        str(audio1),
    ])
    _run([
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", "sine=frequency=660:sample_rate=48000:duration=1",
        "-c:a", "pcm_s16le",
        str(audio2),
    ])

    project = Project(
        videos=[MediaItem(str(video), probe_duration(str(video)))],
        audios=[
            MediaItem(str(audio1), probe_duration(str(audio1))),
            MediaItem(str(audio2), probe_duration(str(audio2))),
        ],
    )
    project.settings.width = 320
    project.settings.height = 240
    project.settings.fps = 24
    project.settings.codec = "h264"
    project.settings.video_bitrate = "500k"
    project.settings.audio_bitrate = "128k"
    project.settings.min_speed = 0.5
    project.settings.loop_mode = "auto"

    result = FFmpegRenderer(project).render(str(output))

    assert result == str(output)
    assert output.exists()
    assert output.stat().st_size > 10_000

    duration = probe_duration(str(output))
    assert 1.8 <= duration <= 2.2

    chapters = tmp_path / "YouTube_Chapter.txt"
    assert chapters.exists()
    lines = chapters.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("00:00 01 Intro")
    assert lines[1].startswith("00:01 02 Lanjut")
