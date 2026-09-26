from __future__ import annotations

import json
from pathlib import Path

import pytest

from full_album_maker import atomic_bundle as bundle_module
from full_album_maker.atomic_bundle import (
    JOURNAL_PREFIX,
    JOURNAL_SUFFIX,
    _bundle_render,
    _write_journal,
    publish_bundle_transactional,
    recover_interrupted_bundles,
)
from full_album_maker.project import MediaItem, Project
from full_album_maker.renderer import FFmpegRenderer, RenderError
from full_album_maker.timeline import (
    AudioTimelineClip,
    TimelinePlan,
    VideoTimelineClip,
)


def _make_bundle_files(tmp_path: Path):
    targets = [
        tmp_path / "album.mp4",
        tmp_path / "album_YouTube_Chapter.txt",
        tmp_path / "album_Tracklist.txt",
        tmp_path / "album_Timeline_Final.json",
    ]
    stages = [tmp_path / f"stage-{index}.tmp" for index in range(4)]
    for index, target in enumerate(targets):
        target.write_bytes(f"old-{index}".encode())
    for index, stage in enumerate(stages):
        stage.write_bytes(f"new-{index}".encode())
    return stages, targets


def _transaction_debris(tmp_path: Path) -> list[Path]:
    return [
        *tmp_path.glob(f"{JOURNAL_PREFIX}*{JOURNAL_SUFFIX}"),
        *tmp_path.glob(".*.fam-backup-*"),
    ]


def test_transactional_publish_replaces_complete_bundle(tmp_path):
    stages, targets = _make_bundle_files(tmp_path)

    publish_bundle_transactional(zip(stages, targets))

    for index, target in enumerate(targets):
        assert target.read_bytes() == f"new-{index}".encode()
    assert all(not stage.exists() for stage in stages)
    assert _transaction_debris(tmp_path) == []


def test_publish_failure_restores_every_previous_file(tmp_path, monkeypatch):
    stages, targets = _make_bundle_files(tmp_path)
    original_replace = bundle_module._replace_file
    failed = False

    def fail_second_stage_once(source: Path, target: Path):
        nonlocal failed
        if Path(source) == stages[1] and not failed:
            failed = True
            raise OSError("simulated second-file replace failure")
        return original_replace(Path(source), Path(target))

    monkeypatch.setattr(bundle_module, "_replace_file", fail_second_stage_once)

    with pytest.raises(RenderError, match="output lama dipulihkan"):
        publish_bundle_transactional(zip(stages, targets))

    assert failed is True
    for index, target in enumerate(targets):
        assert target.read_bytes() == f"old-{index}".encode()
    assert _transaction_debris(tmp_path) == []


def test_recovery_rolls_back_interrupted_publish(tmp_path):
    old_target = tmp_path / "album.mp4"
    new_only_target = tmp_path / "album_Tracklist.txt"
    backup = tmp_path / ".album.mp4.fam-backup-test"
    old_target.write_bytes(b"new-partial-video")
    new_only_target.write_bytes(b"new-partial-sidecar")
    backup.write_bytes(b"old-good-video")

    journal = tmp_path / f"{JOURNAL_PREFIX}test{JOURNAL_SUFFIX}"
    entries = [
        {
            "stage": str(tmp_path / "missing-stage-video"),
            "target": str(old_target),
            "backup": str(backup),
            "had_original": True,
        },
        {
            "stage": str(tmp_path / "missing-stage-sidecar"),
            "target": str(new_only_target),
            "backup": "",
            "had_original": False,
        },
    ]
    _write_journal(journal, "publishing", entries)

    recover_interrupted_bundles(tmp_path)

    assert old_target.read_bytes() == b"old-good-video"
    assert not new_only_target.exists()
    assert not backup.exists()
    assert not journal.exists()


def test_committed_recovery_keeps_new_targets_and_only_cleans_debris(tmp_path):
    target = tmp_path / "album.mp4"
    target.write_bytes(b"new-good-video")
    backup = tmp_path / ".album.mp4.fam-backup-test"
    backup.write_bytes(b"old-video")
    journal = tmp_path / f"{JOURNAL_PREFIX}committed{JOURNAL_SUFFIX}"
    entries = [
        {
            "stage": str(tmp_path / "gone-stage"),
            "target": str(target),
            "backup": str(backup),
            "had_original": True,
        }
    ]
    _write_journal(journal, "committed", entries)

    recover_interrupted_bundles(tmp_path)

    assert target.read_bytes() == b"new-good-video"
    assert not backup.exists()
    assert not journal.exists()


def _simple_renderer(tmp_path: Path) -> tuple[FFmpegRenderer, Path, list[Path]]:
    video_source = tmp_path / "source.mp4"
    audio_source = tmp_path / "source.wav"
    video_source.write_bytes(b"source-video")
    audio_source.write_bytes(b"source-audio")

    project = Project(
        videos=[MediaItem(str(video_source), 1.0)],
        audios=[MediaItem(str(audio_source), 1.0)],
    )
    plan = TimelinePlan(
        duration=1.0,
        project_signature="test-signature",
        video_clips=[
            VideoTimelineClip(
                source=str(video_source),
                source_index=0,
                name="source",
                source_in=0.0,
                source_out=1.0,
                timeline_in=0.0,
                timeline_out=1.0,
                speed=1.0,
            )
        ],
        audio_clips=[
            AudioTimelineClip(
                source=str(audio_source),
                source_index=0,
                name="song",
                source_in=0.0,
                source_out=1.0,
                timeline_in=0.0,
                timeline_out=1.0,
            )
        ],
    )
    renderer = object.__new__(FFmpegRenderer)
    renderer.project = project
    renderer.timeline = plan
    renderer.ffmpeg = "ffmpeg"

    destination = tmp_path / "final.mp4"
    targets = [
        destination,
        tmp_path / "final_YouTube_Chapter.txt",
        tmp_path / "final_Tracklist.txt",
        tmp_path / "final_Timeline_Final.json",
    ]
    for index, target in enumerate(targets):
        target.write_bytes(f"old-final-{index}".encode())
    return renderer, destination, targets


def test_sidecar_staging_failure_does_not_publish_new_video(tmp_path, monkeypatch):
    renderer, destination, targets = _simple_renderer(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    monkeypatch.setattr(bundle_module, "temp_dir", lambda: scratch)
    monkeypatch.setattr(
        bundle_module.visual_feature_module,
        "validate_visual_timeline",
        lambda plan, project: [],
    )
    renderer._ensure_encoder = lambda: None
    renderer._build_audio_from_timeline = (
        lambda out, log=None: Path(out).write_bytes(b"audio")
    )
    renderer._build_video_from_timeline = (
        lambda out, work, log=None: Path(out).write_bytes(b"video")
    )
    renderer._build_final = (
        lambda video, audio, dest, log=None: Path(dest).write_bytes(b"new-final-video")
    )

    def fail_chapters(path):
        raise RenderError("simulated chapter failure")

    renderer._write_chapters = fail_chapters
    renderer._write_tracklist = lambda path: Path(path).write_text("tracklist", encoding="utf-8")

    with pytest.raises(RenderError, match="simulated chapter failure"):
        _bundle_render(renderer, str(destination))

    for index, target in enumerate(targets):
        assert target.read_bytes() == f"old-final-{index}".encode()
    assert _transaction_debris(tmp_path) == []
    assert not list(tmp_path.glob(".*rendering*"))
