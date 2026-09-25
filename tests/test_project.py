from pathlib import Path

from full_album_maker.project import MediaItem, Project


def test_auto_speed_matches_album_when_possible():
    p = Project(videos=[MediaItem("v.mp4", 1800)], audios=[MediaItem("a.mp3", 3600)])
    p.settings.min_speed = 0.25
    assert p.planned_speed() == 0.5
    assert round(p.adjusted_video_duration()) == 3600
    assert p.needs_loop() is False


def test_auto_speed_respects_minimum_and_loops():
    p = Project(videos=[MediaItem("v.mp4", 300)], audios=[MediaItem("a.mp3", 7200)])
    p.settings.min_speed = 0.5
    assert p.planned_speed() == 0.5
    assert round(p.adjusted_video_duration()) == 600
    assert p.needs_loop() is True


def test_move_audio_uses_human_positions():
    p = Project(
        audios=[
            MediaItem("01.mp3", 10),
            MediaItem("02.mp3", 10),
            MediaItem("03.mp3", 10),
        ]
    )
    p.move_audio(3, 1)
    assert [x.name for x in p.audios] == ["03.mp3", "01.mp3", "02.mp3"]


def test_optimize_youtube_sets_safe_defaults():
    p = Project(videos=[MediaItem("v.mp4", 1800)], audios=[MediaItem("a.mp3", 3600)])
    result = p.optimize_youtube("1440p")
    assert (p.settings.width, p.settings.height) == (2560, 1440)
    assert p.settings.fps == 30
    assert p.settings.codec == "h264"
    assert p.settings.video_bitrate == "20M"
    assert p.settings.audio_bitrate == "320k"
    assert p.settings.auto_speed is True
    assert p.settings.min_speed == 0.5
    assert result["planned_speed"] == 0.5


def test_project_serialization_roundtrip():
    p = Project(
        videos=[MediaItem("video.mp4", 12.5)],
        audios=[MediaItem("01.mp3", 3.5), MediaItem("02.mp3", 4.5)],
    )
    p.settings.codec = "h265"
    restored = Project.from_dict(p.to_dict())
    assert restored.videos[0].path == "video.mp4"
    assert [x.name for x in restored.audios] == ["01.mp3", "02.mp3"]
    assert restored.settings.codec == "h265"
