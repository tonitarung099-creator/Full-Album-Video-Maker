from __future__ import annotations

from pathlib import Path

from full_album_maker.engine_hardening import (
    install_engine_hardening,
    uninstall_engine_hardening,
)
from full_album_maker.playlist_feature import install_feature, uninstall_feature
from full_album_maker.playlist_hardening import (
    install_playlist_hardening,
    uninstall_playlist_hardening,
)
from full_album_maker.project import MediaItem, Project
from full_album_maker.source_integrity import (
    install_source_integrity,
    project_source_fingerprints,
    source_integrity_signature,
    uninstall_source_integrity,
)
from full_album_maker.timeline import timeline_matches_project
from full_album_maker.visual_feature import (
    VisualPlaylistTimelineEngine,
    install_visual_feature,
    uninstall_visual_feature,
    validate_visual_timeline,
)


def _install_stack():
    install_feature()
    install_playlist_hardening()
    install_visual_feature()
    install_engine_hardening()
    install_source_integrity()


def _uninstall_stack():
    uninstall_source_integrity()
    uninstall_engine_hardening()
    uninstall_visual_feature()
    uninstall_playlist_hardening()
    uninstall_feature()


def test_replacing_source_at_same_path_invalidates_existing_timeline(tmp_path):
    _install_stack()
    try:
        video = tmp_path / "footage.mp4"
        audio = tmp_path / "album.wav"
        video.write_bytes(b"video-version-one")
        audio.write_bytes(b"audio-version-one")

        project = Project(
            videos=[MediaItem(str(video), 10.0)],
            audios=[MediaItem(str(audio), 10.0)],
        )
        plan = VisualPlaylistTimelineEngine().build(project)

        assert timeline_matches_project(plan, project)
        assert validate_visual_timeline(plan, project) == []
        before = source_integrity_signature(project)

        video.write_bytes(b"video-version-two-is-different-size")

        after = source_integrity_signature(project)
        assert after != before
        assert not timeline_matches_project(plan, project)
        errors = validate_visual_timeline(plan, project)
        assert any("tidak cocok" in message.casefold() for message in errors)
    finally:
        _uninstall_stack()


def test_deleting_source_after_timeline_build_invalidates_plan(tmp_path):
    _install_stack()
    try:
        video = tmp_path / "footage.mp4"
        audio = tmp_path / "album.wav"
        video.write_bytes(b"video")
        audio.write_bytes(b"audio")

        project = Project(
            videos=[MediaItem(str(video), 5.0)],
            audios=[MediaItem(str(audio), 5.0)],
        )
        plan = VisualPlaylistTimelineEngine().build(project)
        audio.unlink()

        fingerprints = project_source_fingerprints(project)
        audio_fp = next(item for item in fingerprints if item["kind"] == "audio")
        assert audio_fp["fingerprint"]["exists"] is False
        assert not timeline_matches_project(plan, project)
        assert validate_visual_timeline(plan, project)
    finally:
        _uninstall_stack()


def test_touching_source_mtime_changes_signature_without_project_edit(tmp_path):
    _install_stack()
    try:
        video = tmp_path / "footage.mp4"
        audio = tmp_path / "album.wav"
        video.write_bytes(b"same-size")
        audio.write_bytes(b"audio")
        project = Project(
            videos=[MediaItem(str(video), 4.0)],
            audios=[MediaItem(str(audio), 4.0)],
        )

        before = source_integrity_signature(project)
        stat = video.stat()
        # Keep bytes and size unchanged; only filesystem modification time changes.
        new_ns = stat.st_mtime_ns + 10_000_000
        import os

        os.utime(video, ns=(stat.st_atime_ns, new_ns))
        after = source_integrity_signature(project)

        assert before != after
    finally:
        _uninstall_stack()
