from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from full_album_maker import playlist_hardening as hardening
from full_album_maker.controller import ProjectController
from full_album_maker.playlist_feature import (
    active_audio_indices,
    get_active_audio_paths,
    install_feature,
    playlist_project_signature,
    set_active_audio_paths,
    uninstall_feature,
)
from full_album_maker.playlist_hardening import (
    install_playlist_hardening,
    uninstall_playlist_hardening,
)
from full_album_maker.project import MediaItem, Project


@pytest.fixture
def hardened_feature():
    install_feature()
    install_playlist_hardening()
    try:
        yield
    finally:
        uninstall_playlist_hardening()
        uninstall_feature()


def test_removing_selected_media_prunes_active_playlist(hardened_feature):
    project = Project(
        audios=[
            MediaItem("/media/01 - Alpha.mp3", 100.0),
            MediaItem("/media/02 - Beta.mp3", 110.0),
            MediaItem("/media/03 - Gamma.mp3", 120.0),
        ]
    )
    controller = ProjectController(project)
    controller.execute(
        "select_audio_by_titles",
        {"titles": ["Alpha", "Beta"]},
    )

    controller.execute("remove_audio", {"position": 1})

    assert [item.name for item in project.audios] == ["02 - Beta.mp3", "03 - Gamma.mp3"]
    assert active_audio_indices(project, strict=True) == [0]
    assert [Path(path).name for path in get_active_audio_paths(project)] == ["02 - Beta.mp3"]

    # A project saved after removal must remain loadable; no stale ghost path.
    restored = Project.from_dict(project.to_dict())
    assert active_audio_indices(restored, strict=True) == [0]


def test_missing_unused_library_song_does_not_block_active_playlist(hardened_feature, tmp_path):
    video = tmp_path / "footage.mp4"
    selected = tmp_path / "selected.mp3"
    video.write_bytes(b"video")
    selected.write_bytes(b"audio")
    missing_unused = tmp_path / "unused-missing.mp3"

    project = Project(
        videos=[MediaItem(str(video), 300.0)],
        audios=[
            MediaItem(str(selected), 120.0),
            MediaItem(str(missing_unused), 180.0),
        ],
    )
    set_active_audio_paths(project, [str(selected)])

    report = project.validation()

    assert report["errors"] == []


def test_missing_selected_song_still_blocks_render_validation(hardened_feature, tmp_path):
    video = tmp_path / "footage.mp4"
    video.write_bytes(b"video")
    missing_selected = tmp_path / "selected-missing.mp3"
    existing_unused = tmp_path / "unused.mp3"
    existing_unused.write_bytes(b"audio")

    project = Project(
        videos=[MediaItem(str(video), 300.0)],
        audios=[
            MediaItem(str(missing_selected), 120.0),
            MediaItem(str(existing_unused), 180.0),
        ],
    )
    set_active_audio_paths(project, [str(missing_selected)])

    report = project.validation()

    assert any("dipakai timeline" in error for error in report["errors"])


def test_agent_rollback_restores_timeline_with_atomic_writer(
    hardened_feature,
    tmp_path,
    monkeypatch,
):
    timeline_path = tmp_path / "Timeline_Auto.json"
    timeline_path.write_bytes(b"GOOD")

    project = Project(audios=[MediaItem("/media/song.mp3", 10.0)])
    calls: list[tuple[Path, bytes]] = []

    class Chat:
        def appendPlainText(self, _text):
            pass

    class Preview:
        def set_timeline(self, _plan):
            pass

    class ExplodingExecutor:
        def __init__(self, project, *, timeline_output_path):
            self.timeline_output_path = Path(timeline_output_path)

        def execute(self, _actions):
            self.timeline_output_path.write_bytes(b"BROKEN")
            raise RuntimeError("boom")

    def fake_atomic_write_bytes(path, data):
        path = Path(path)
        calls.append((path, data))
        path.write_bytes(data)
        return str(path)

    monkeypatch.setattr(hardening.ui_module, "output_dir", lambda: tmp_path)
    monkeypatch.setattr(hardening.agent_actions_module, "AppIntentExecutor", ExplodingExecutor)
    monkeypatch.setattr(hardening, "atomic_write_bytes", fake_atomic_write_bytes)

    self = SimpleNamespace(
        project=project,
        controller=ProjectController(project),
        agent=None,
        render_busy=False,
        timeline_plan=None,
        timeline_ready=False,
        timeline_file_path="",
        chat=Chat(),
        timeline_preview=Preview(),
        _sync_controls_from_project=lambda: None,
        refresh=lambda: None,
        _error=lambda _text: None,
        _agent_done=lambda: None,
        invalidate_timeline=lambda: None,
        apply_timeline_plan=lambda _plan: None,
        _start_agent_render_default=lambda: None,
    )
    decision = SimpleNamespace(
        message="ok",
        actions=[SimpleNamespace(name="select_audio_by_titles", args={"titles": ["song"]})],
    )

    hardening._hardened_handle_agent_decision(
        self,
        decision,
        playlist_project_signature(project),
    )

    assert calls == [(timeline_path, b"GOOD")]
    assert timeline_path.read_bytes() == b"GOOD"
