from __future__ import annotations

import math
from pathlib import Path
import shutil
import struct
import subprocess

import pytest
from PySide6.QtWidgets import QApplication

from full_album_maker.editor_controller import EditorController
from full_album_maker.editor_models import (
    MediaAsset,
    ProjectDocument,
    SongInstance,
    TIMEBASE,
    seconds_to_tick,
)
from full_album_maker.free_timeline import (
    SetPlaylistTimingMode,
    SetSongFreeTiming,
)
from full_album_maker.project_io import dumps_project_document, loads_project_document
from full_album_maker.s11_render_graph import S11FFmpegCompiler
from full_album_maker.s11_workspace import S11EditorWorkspace
from full_album_maker.timeline_resolver import TimelineResolver


def _ffmpeg() -> str:
    value = shutil.which("ffmpeg")
    if not value:
        pytest.skip("FFmpeg tidak tersedia")
    return value


def _ffprobe() -> str:
    value = shutil.which("ffprobe")
    if not value:
        pytest.skip("ffprobe tidak tersedia")
    return value


def _tone(path: Path, frequency: int, duration: float = 0.6) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            _ffmpeg(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:duration={duration}",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(path),
        ],
        check=True,
    )
    return path


def _document(tmp_path: Path, count: int = 2, duration: float = 0.6) -> ProjectDocument:
    tmp_path.mkdir(parents=True, exist_ok=True)
    doc = ProjectDocument.new_empty("S11")
    doc.canvas.width = 320
    doc.canvas.height = 240
    for index in range(count):
        path = _tone(tmp_path / f"tone-{index}.wav", 330 + index * 170, duration)
        asset = MediaAsset(
            kind="audio",
            locator=str(path),
            original_name=path.name,
            source_duration_tick=seconds_to_tick(duration),
        )
        doc.media.append(asset)
        doc.playlist.entries.append(
            SongInstance(
                asset_id=asset.asset_id,
                source_out_tick=asset.source_duration_tick,
                display_title=f"Lagu {index + 1}",
                display_artist="S11",
            )
        )
    doc.validate()
    return doc


def _audio_errors(doc: ProjectDocument) -> list[str]:
    return [
        item
        for item in TimelineResolver().resolve(doc).errors
        if item.startswith("Audio: ")
    ]


def _probe_duration(path: Path) -> float:
    raw = subprocess.run(
        [
            _ffprobe(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(raw)


def _interval_rms(path: Path, start: float, duration: float) -> float:
    completed = subprocess.run(
        [
            _ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.6f}",
            "-t",
            f"{duration:.6f}",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-f",
            "f32le",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    raw = completed.stdout
    if not raw:
        return 0.0
    sample_count = len(raw) // 4
    values = struct.unpack("<" + "f" * sample_count, raw[: sample_count * 4])
    return math.sqrt(sum(value * value for value in values) / max(1, sample_count))


def test_packed_resolver_remains_contiguous(tmp_path: Path):
    doc = _document(tmp_path)
    resolved = TimelineResolver().resolve(doc)
    assert resolved.errors == []
    assert resolved.songs[0].start_tick == 0
    assert resolved.songs[0].end_tick == resolved.songs[1].start_tick
    assert resolved.duration_tick == seconds_to_tick(1.2)


def test_packed_to_free_preserves_positions_and_undo_restores_exact_mode(tmp_path: Path):
    controller = EditorController(_document(tmp_path))
    before = controller.snapshot()
    controller.dispatch(SetPlaylistTimingMode("free"))
    free = controller.snapshot()
    assert free.playlist.mode == "free"
    assert [song.free_start_tick for song in free.playlist.entries] == [
        0,
        seconds_to_tick(0.6),
    ]
    assert all(song.crossfade_in_tick == 0 for song in free.playlist.entries)
    assert TimelineResolver().resolve(free).duration_tick == seconds_to_tick(1.2)

    controller.undo()
    restored = controller.snapshot()
    assert restored.playlist.mode == "packed"
    assert all(song.free_start_tick is None for song in restored.playlist.entries)
    assert restored.content_signature() == before.content_signature()


def test_free_to_packed_is_explicit_compaction_and_undo_restores_free_timing(tmp_path: Path):
    controller = EditorController(_document(tmp_path))
    controller.dispatch(SetPlaylistTimingMode("free"))
    second = controller.snapshot().playlist.entries[1]
    controller.dispatch(
        SetSongFreeTiming(second.song_id, seconds_to_tick(0.8), 0)
    )
    free_signature = controller.snapshot().content_signature()

    controller.dispatch(SetPlaylistTimingMode("packed"))
    packed = controller.snapshot()
    assert packed.playlist.mode == "packed"
    assert all(song.free_start_tick is None for song in packed.playlist.entries)
    assert all(song.crossfade_in_tick == 0 for song in packed.playlist.entries)
    assert TimelineResolver().resolve(packed).duration_tick == seconds_to_tick(1.2)

    controller.undo()
    assert controller.snapshot().content_signature() == free_signature


def test_free_gap_is_valid_and_extends_album_duration(tmp_path: Path):
    controller = EditorController(_document(tmp_path))
    controller.dispatch(SetPlaylistTimingMode("free"))
    second = controller.snapshot().playlist.entries[1]
    controller.dispatch(
        SetSongFreeTiming(second.song_id, seconds_to_tick(0.9), 0)
    )
    doc = controller.snapshot()
    resolved = TimelineResolver().resolve(doc)
    assert resolved.errors == []
    assert resolved.songs[1].start_tick == seconds_to_tick(0.9)
    assert resolved.duration_tick == seconds_to_tick(1.5)


def test_overlap_without_crossfade_is_rejected(tmp_path: Path):
    controller = EditorController(_document(tmp_path))
    controller.dispatch(SetPlaylistTimingMode("free"))
    second = controller.snapshot().playlist.entries[1]
    with pytest.raises(ValueError, match="belum memiliki crossfade"):
        controller.dispatch(
            SetSongFreeTiming(second.song_id, seconds_to_tick(0.4), 0)
        )


def test_crossfade_must_exactly_match_overlap(tmp_path: Path):
    controller = EditorController(_document(tmp_path))
    controller.dispatch(SetPlaylistTimingMode("free"))
    second = controller.snapshot().playlist.entries[1]
    with pytest.raises(ValueError, match="tetapi crossfade_in_tick"):
        controller.dispatch(
            SetSongFreeTiming(
                second.song_id,
                seconds_to_tick(0.4),
                seconds_to_tick(0.1),
            )
        )


def test_valid_crossfade_resolves_and_is_persisted(tmp_path: Path):
    controller = EditorController(_document(tmp_path))
    controller.dispatch(SetPlaylistTimingMode("free"))
    second = controller.snapshot().playlist.entries[1]
    controller.dispatch(
        SetSongFreeTiming(
            second.song_id,
            seconds_to_tick(0.4),
            seconds_to_tick(0.2),
        )
    )
    doc = controller.snapshot()
    assert _audio_errors(doc) == []
    resolved = TimelineResolver().resolve(doc)
    assert resolved.duration_tick == seconds_to_tick(1.0)

    loaded = loads_project_document(dumps_project_document(doc))
    loaded_second = loaded.song_map()[second.song_id]
    assert loaded.playlist.mode == "free"
    assert loaded_second.free_start_tick == seconds_to_tick(0.4)
    assert loaded_second.crossfade_in_tick == seconds_to_tick(0.2)


def test_triple_overlap_is_rejected(tmp_path: Path):
    doc = _document(tmp_path, count=3, duration=0.8)
    controller = EditorController(doc)
    controller.dispatch(SetPlaylistTimingMode("free"))
    songs = controller.snapshot().playlist.entries
    controller.dispatch(
        SetSongFreeTiming(
            songs[1].song_id,
            seconds_to_tick(0.5),
            seconds_to_tick(0.3),
        )
    )
    with pytest.raises(ValueError, match="ambigu/triple"):
        controller.dispatch(
            SetSongFreeTiming(
                songs[2].song_id,
                seconds_to_tick(0.7),
                seconds_to_tick(0.6),
            )
        )


def test_real_ffmpeg_free_gap_contains_actual_silence(tmp_path: Path):
    ffmpeg = _ffmpeg()
    controller = EditorController(_document(tmp_path / "gap", duration=0.5))
    controller.dispatch(SetPlaylistTimingMode("free"))
    second = controller.snapshot().playlist.entries[1]
    controller.dispatch(
        SetSongFreeTiming(second.song_id, seconds_to_tick(0.9), 0)
    )
    doc = controller.snapshot()
    output = tmp_path / "gap.mp4"
    compiled = S11FFmpegCompiler(ffmpeg).compile_video(
        doc,
        output,
        tmp_path / "gap-work",
    )
    graph = compiled.args[compiled.args.index("-filter_complex") + 1]
    assert "anullsrc" in graph
    assert "amix=" in graph
    subprocess.run(compiled.args, check=True, capture_output=True, text=True)
    assert output.exists() and output.stat().st_size > 0
    assert _probe_duration(output) == pytest.approx(1.4, abs=0.08)
    assert _interval_rms(output, 0.62, 0.15) < 0.002


def test_real_ffmpeg_explicit_crossfade_renders_to_max_end_not_sum(tmp_path: Path):
    ffmpeg = _ffmpeg()
    controller = EditorController(_document(tmp_path / "fade", duration=0.6))
    controller.dispatch(SetPlaylistTimingMode("free"))
    second = controller.snapshot().playlist.entries[1]
    controller.dispatch(
        SetSongFreeTiming(
            second.song_id,
            seconds_to_tick(0.4),
            seconds_to_tick(0.2),
        )
    )
    doc = controller.snapshot()
    output = tmp_path / "fade.mp4"
    compiled = S11FFmpegCompiler(ffmpeg).compile_video(
        doc,
        output,
        tmp_path / "fade-work",
    )
    graph = compiled.args[compiled.args.index("-filter_complex") + 1]
    assert "afade=t=in" in graph
    assert "afade=t=out" in graph
    subprocess.run(compiled.args, check=True, capture_output=True, text=True)
    assert _probe_duration(output) == pytest.approx(1.0, abs=0.08)
    assert _interval_rms(output, 0.45, 0.10) > 0.01


def test_s11_workspace_keeps_packed_default_and_applies_free_timing(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    workspace = S11EditorWorkspace(
        _document(tmp_path / "ui"),
        template_preview_enabled=False,
    )
    try:
        assert workspace.document().playlist.mode == "packed"
        assert workspace.song_timing_apply_s11.isEnabled() is False

        free_index = workspace.timeline_mode_combo_s11.findData("free")
        workspace.timeline_mode_combo_s11.setCurrentIndex(free_index)
        workspace._apply_mode_s11()
        app.processEvents()
        assert workspace.document().playlist.mode == "free"
        assert workspace.song_timing_apply_s11.isEnabled()

        workspace.song_start_s11.setValue(0.0)
        workspace.song_crossfade_s11.setValue(0.0)
        workspace._apply_song_timing_s11()
        app.processEvents()
        assert "Free aktif" in workspace.free_timeline_status_s11.text()
        assert workspace.session.can_undo
    finally:
        workspace.close()
        workspace.deleteLater()
        app.processEvents()


def test_packed_compiler_graph_remains_legacy_concat(tmp_path: Path):
    doc = _document(tmp_path / "packed")
    output = tmp_path / "packed.mp4"
    compiled = S11FFmpegCompiler(_ffmpeg()).compile_video(
        doc,
        output,
        tmp_path / "packed-work",
    )
    graph = compiled.args[compiled.args.index("-filter_complex") + 1]
    assert "concat=n=2:v=0:a=1[album_audio]" in graph
    assert "anullsrc" not in graph
