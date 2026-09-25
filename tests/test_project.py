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
