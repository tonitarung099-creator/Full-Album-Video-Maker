from __future__ import annotations

import os

import pytest

import full_album_maker.atomic_io as atomic_io
import full_album_maker.key_pool as key_pool_module
import full_album_maker.project_io as project_io_module
import full_album_maker.timeline as timeline_module
from full_album_maker.atomic_io import atomic_write_bytes, atomic_write_text
from full_album_maker.key_pool import GeminiKeyPool
from full_album_maker.project import MediaItem, Project
from full_album_maker.project_io import load_project, save_project
from full_album_maker.timeline import TimelineEngine, load_timeline, save_timeline


def test_atomic_write_failure_preserves_old_file_and_cleans_temp(monkeypatch, tmp_path):
    target = tmp_path / "important.json"
    target.write_bytes(b"old-good-data")

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(atomic_io.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_write_bytes(target, b"new-partial-data")

    assert target.read_bytes() == b"old-good-data"
    assert not list(tmp_path.glob(".important.json.*.tmp"))


def test_atomic_write_text_replaces_complete_file(tmp_path):
    target = tmp_path / "data.txt"
    target.write_text("old", encoding="utf-8")

    result = atomic_write_text(target, "new-complete", encoding="utf-8")

    assert result == str(target)
    assert target.read_text(encoding="utf-8") == "new-complete"
    assert not list(tmp_path.glob(".data.txt.*.tmp"))


def test_project_save_roundtrip_uses_atomic_writer(monkeypatch, tmp_path):
    calls = []
    real = project_io_module.atomic_write_text

    def recording_writer(path, text, *, encoding="utf-8"):
        calls.append(path)
        return real(path, text, encoding=encoding)

    monkeypatch.setattr(project_io_module, "atomic_write_text", recording_writer)

    project = Project(
        videos=[MediaItem("video.mp4", 12.0)],
        audios=[MediaItem("song.wav", 12.0)],
    )
    path = save_project(str(tmp_path / "project.json"), project)

    assert calls
    restored = load_project(path)
    assert restored.to_dict() == project.to_dict()


def test_timeline_save_roundtrip_uses_atomic_writer(monkeypatch, tmp_path):
    calls = []
    real = timeline_module.atomic_write_text

    def recording_writer(path, text, *, encoding="utf-8"):
        calls.append(path)
        return real(path, text, encoding=encoding)

    monkeypatch.setattr(timeline_module, "atomic_write_text", recording_writer)

    project = Project(
        videos=[MediaItem("video.mp4", 10.0)],
        audios=[MediaItem("song.wav", 10.0)],
    )
    plan = TimelineEngine().build(project)
    path = save_timeline(str(tmp_path / "timeline.json"), plan)

    assert calls
    restored = load_timeline(path)
    assert restored.to_dict() == plan.to_dict()


def test_key_vault_save_uses_atomic_writer(monkeypatch, tmp_path):
    calls = []
    real = key_pool_module.atomic_write_bytes

    def recording_writer(path, data):
        calls.append(path)
        return real(path, data)

    monkeypatch.setattr(key_pool_module, "atomic_write_bytes", recording_writer)

    vault = tmp_path / "keys.dat"
    pool = GeminiKeyPool(vault)
    accepted, rejected = pool.add_keys(
        ["test-key-00001-abcdefghijklmnopqrstuvwxyz"]
    )

    assert accepted == 1
    assert rejected == 0
    assert calls
    assert vault.exists()

    restored = GeminiKeyPool(vault)
    assert len(restored.records) == 1
    assert restored.records[0].key == "test-key-00001-abcdefghijklmnopqrstuvwxyz"
