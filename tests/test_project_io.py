from full_album_maker.project import MediaItem, Project
from full_album_maker.project_io import load_project, save_project


def test_save_load_project_json(tmp_path):
    project = Project(
        videos=[MediaItem("video.mp4", 20.0)],
        audios=[MediaItem("song.mp3", 30.0)],
    )
    project.settings.min_speed = 0.65

    path = save_project(str(tmp_path / "album-project"), project)
    assert path.endswith(".json")

    loaded = load_project(path)
    assert loaded.videos[0].path == "video.mp4"
    assert loaded.audios[0].path == "song.mp3"
    assert loaded.settings.min_speed == 0.65
