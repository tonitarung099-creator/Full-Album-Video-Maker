from __future__ import annotations

import json
import subprocess

import pytest

from full_album_maker.media import probe_duration
from full_album_maker.paths import ffmpeg_path, ffprobe_path
from full_album_maker.project import MediaItem, Project
from full_album_maker.renderer import FFmpegRenderer
from full_album_maker.timeline import (
    AudioTimelineClip,
    TimelineEngine,
    TimelinePlan,
    VideoTimelineClip,
    project_signature,
)


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


def _make_media(ffmpeg, tmp_path):
    video1 = tmp_path / "landscape.avi"
    video2 = tmp_path / "portrait.avi"
    audio1 = tmp_path / "01 Intro.wav"
    audio2 = tmp_path / "02 Lanjut.wav"

    _run([
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "color=c=blue:s=320x240:r=24:d=0.25",
        "-an", "-c:v", "mpeg4", str(video1),
    ])
    _run([
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "color=c=red:s=240x320:r=30:d=0.25",
        "-an", "-c:v", "mpeg4", str(video2),
    ])
    _run([
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "sine=frequency=440:sample_rate=48000:duration=1",
        "-c:a", "pcm_s16le", str(audio1),
    ])
    _run([
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "sine=frequency=660:sample_rate=48000:duration=1",
        "-c:a", "pcm_s16le", str(audio2),
    ])
    return video1, video2, audio1, audio2


@pytest.mark.parametrize(
    ("codec", "encoder"),
    [("h264", "libx264"), ("h265", "libx265")],
)
def test_real_ffmpeg_full_album_render_from_timeline(codec, encoder, tmp_path):
    ffmpeg = ffmpeg_path()
    ffprobe = ffprobe_path()
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg portable belum tersedia.")

    if encoder not in _encoder_output(ffmpeg):
        pytest.skip(f"FFmpeg lokal tidak punya {encoder}.")

    video1, video2, audio1, audio2 = _make_media(ffmpeg, tmp_path)
    output = tmp_path / f"FULL_ALBUM_{codec}.mp4"

    project = Project(
        videos=[
            MediaItem(str(video1), probe_duration(str(video1))),
            MediaItem(str(video2), probe_duration(str(video2))),
        ],
        audios=[
            MediaItem(str(audio1), probe_duration(str(audio1))),
            MediaItem(str(audio2), probe_duration(str(audio2))),
        ],
    )
    project.settings.width = 320
    project.settings.height = 240
    project.settings.fps = 24
    project.settings.codec = codec
    project.settings.video_bitrate = "500k"
    project.settings.audio_bitrate = "128k"
    project.settings.min_speed = 0.5
    project.settings.loop_mode = "auto"

    plan = TimelineEngine().build(project)
    result = FFmpegRenderer(project, plan).render(str(output))

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

    tracklist = tmp_path / "Tracklist.txt"
    assert tracklist.exists()
    track_lines = tracklist.read_text(encoding="utf-8").splitlines()
    assert track_lines[0].startswith("01. 01 Intro")
    assert track_lines[1].startswith("02. 02 Lanjut")

    final_timeline = tmp_path / "Timeline_Final.json"
    assert final_timeline.exists()
    rendered_plan = json.loads(final_timeline.read_text(encoding="utf-8"))
    assert rendered_plan == plan.to_dict()


def test_real_ffmpeg_short_pingpong_follows_timeline(tmp_path):
    ffmpeg = ffmpeg_path()
    if not ffmpeg or "libx264" not in _encoder_output(ffmpeg):
        pytest.skip("FFmpeg GPL dengan libx264 belum tersedia.")

    video = tmp_path / "short.avi"
    audio = tmp_path / "album.wav"
    output = tmp_path / "PINGPONG.mp4"

    _run([
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "color=c=green:s=160x120:r=12:d=0.25",
        "-an", "-c:v", "mpeg4", str(video),
    ])
    _run([
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "sine=frequency=330:sample_rate=48000:duration=1",
        "-c:a", "pcm_s16le", str(audio),
    ])

    project = Project(
        videos=[MediaItem(str(video), probe_duration(str(video)))],
        audios=[MediaItem(str(audio), probe_duration(str(audio)))],
    )
    project.settings.width = 160
    project.settings.height = 120
    project.settings.fps = 12
    project.settings.codec = "h264"
    project.settings.video_bitrate = "300k"
    project.settings.audio_bitrate = "96k"
    project.settings.min_speed = 1.0
    project.settings.loop_mode = "pingpong"

    plan = TimelineEngine().build(project)
    assert any(clip.direction == "reverse" for clip in plan.video_clips)

    FFmpegRenderer(project, plan).render(str(output))
    assert output.exists()
    assert 0.8 <= probe_duration(str(output)) <= 1.2


def test_real_render_obeys_timeline_source_in_not_raw_project_order(tmp_path):
    ffmpeg = ffmpeg_path()
    if not ffmpeg or "libx264" not in _encoder_output(ffmpeg):
        pytest.skip("FFmpeg GPL dengan libx264 belum tersedia.")

    video = tmp_path / "red_then_blue.avi"
    audio = tmp_path / "half_second.wav"
    output = tmp_path / "SOURCE_IN_TEST.mp4"

    _run([
        ffmpeg, "-y",
        "-f", "lavfi", "-i", "color=c=red:s=160x120:r=20:d=0.5",
        "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=20:d=0.5",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map", "[v]", "-an", "-c:v", "mpeg4", str(video),
    ])
    _run([
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "sine=frequency=440:sample_rate=48000:duration=0.5",
        "-c:a", "pcm_s16le", str(audio),
    ])

    video_duration = probe_duration(str(video))
    audio_duration = probe_duration(str(audio))
    project = Project(
        videos=[MediaItem(str(video), video_duration)],
        audios=[MediaItem(str(audio), audio_duration)],
    )
    project.settings.width = 160
    project.settings.height = 120
    project.settings.fps = 20
    project.settings.codec = "h264"
    project.settings.video_bitrate = "400k"
    project.settings.audio_bitrate = "96k"

    source_out = video_duration
    source_in = source_out - audio_duration
    plan = TimelinePlan(
        duration=audio_duration,
        planned_speed=1.0,
        source_video_duration=video_duration,
        adjusted_video_duration=video_duration,
        auto_cut_seconds=max(0.0, video_duration - audio_duration),
        loop_fill_seconds=0.0,
        loop_mode="none",
        project_signature=project_signature(project),
        video_clips=[
            VideoTimelineClip(
                source=str(video),
                source_index=0,
                name="blue-half",
                source_in=source_in,
                source_out=source_out,
                timeline_in=0.0,
                timeline_out=audio_duration,
                speed=1.0,
                direction="forward",
                kind="source",
                cycle=0,
            )
        ],
        audio_clips=[
            AudioTimelineClip(
                source=str(audio),
                source_index=0,
                name="half_second",
                source_in=0.0,
                source_out=audio_duration,
                timeline_in=0.0,
                timeline_out=audio_duration,
            )
        ],
    )
    assert plan.validate() == []

    FFmpegRenderer(project, plan).render(str(output))

    frame = subprocess.run(
        [
            ffmpeg, "-v", "error", "-ss", "0.10", "-i", str(output),
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    assert len(frame) >= 3
    red, green, blue = frame[0], frame[1], frame[2]
    assert blue > red + 80
    assert blue > green + 80
