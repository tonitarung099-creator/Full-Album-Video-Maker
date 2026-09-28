from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import time

import pytest

from full_album_maker.editor_models import (
    MediaAsset,
    ProjectDocument,
    SongInstance,
    seconds_to_tick,
)
from full_album_maker.s11_render_graph import (
    S11FFmpegCompiler,
    WINDOWS_COMMAND_SAFE_LIMIT,
    windows_command_line_length,
)
from full_album_maker.timeline_resolver import TimelineResolver


SONG_COUNT = 200
SONG_SECONDS = 54.0
THREE_HOURS_TICK = seconds_to_tick(3 * 60 * 60)


def _long_document(*, mode: str = "packed") -> ProjectDocument:
    doc = ProjectDocument.new_empty("S12 200 Lagu")
    doc.canvas.width = 320
    doc.canvas.height = 240
    doc.playlist.mode = mode
    duration_tick = seconds_to_tick(SONG_SECONDS)
    for index in range(SONG_COUNT):
        locator = f"C:/Album Uji S12/Lagu {index + 1:03d} – Panjang.wav"
        asset = MediaAsset(
            kind="audio",
            locator=locator,
            original_name=Path(locator).name,
            source_duration_tick=duration_tick,
        )
        doc.media.append(asset)
        doc.playlist.entries.append(
            SongInstance(
                asset_id=asset.asset_id,
                display_title=f"Lagu {index + 1:03d}",
                display_artist="S12",
                source_out_tick=duration_tick,
                free_start_tick=(index * duration_tick if mode == "free" else None),
            )
        )
    doc.validate()
    return doc


def _compile(doc: ProjectDocument, tmp_path: Path):
    return S11FFmpegCompiler("ffmpeg.exe").compile_video(
        doc,
        tmp_path / "album.mp4",
        tmp_path / "work",
    )


def _script_from(compiled) -> Path:
    option = "-/filter_complex"
    assert option in compiled.args
    assert "-filter_complex" not in compiled.args
    return Path(compiled.args[compiled.args.index(option) + 1])


def test_packed_200_song_three_hour_project_resolves_and_externalizes_graph(tmp_path: Path):
    doc = _long_document(mode="packed")
    started = time.perf_counter()
    resolved = TimelineResolver().resolve(doc)
    elapsed = time.perf_counter() - started

    assert resolved.errors == []
    assert len(resolved.songs) == SONG_COUNT
    assert resolved.duration_tick == THREE_HOURS_TICK
    # A deliberately generous regression ceiling: this is a model/resolver gate,
    # not a micro-benchmark tied to a particular CI runner.
    assert elapsed < 2.0

    compiled = _compile(doc, tmp_path)
    graph = _script_from(compiled).read_text(encoding="utf-8")
    assert "concat=n=200:v=0:a=1[album_audio]" in graph
    assert windows_command_line_length(compiled.args) < WINDOWS_COMMAND_SAFE_LIMIT


def test_free_200_song_three_hour_project_resolves_and_uses_bounded_command(tmp_path: Path):
    doc = _long_document(mode="free")
    started = time.perf_counter()
    resolved = TimelineResolver().resolve(doc)
    elapsed = time.perf_counter() - started

    assert resolved.errors == []
    assert len(resolved.songs) == SONG_COUNT
    assert resolved.duration_tick == THREE_HOURS_TICK
    assert elapsed < 2.0

    compiled = _compile(doc, tmp_path)
    graph = _script_from(compiled).read_text(encoding="utf-8")
    assert "amix=inputs=201:duration=longest" in graph
    assert "anullsrc=r=48000:cl=stereo:d=10800.000000[asilence]" in graph
    assert windows_command_line_length(compiled.args) < WINDOWS_COMMAND_SAFE_LIMIT


def _ffmpeg() -> str:
    value = shutil.which("ffmpeg")
    if not value:
        pytest.skip("FFmpeg tidak tersedia")
    return value


def _tone(path: Path, duration: float = 0.12) -> Path:
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
            f"sine=frequency=440:duration={duration}",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(path),
        ],
        check=True,
    )
    return path


def test_real_ffmpeg_accepts_external_filter_script(tmp_path: Path, monkeypatch):
    import full_album_maker.s11_render_graph as s11_graph

    tone = _tone(tmp_path / "tone.wav")
    doc = ProjectDocument.new_empty("S12 script smoke")
    doc.canvas.width = 320
    doc.canvas.height = 240
    duration_tick = seconds_to_tick(0.12)
    asset = MediaAsset(
        kind="audio",
        locator=str(tone),
        original_name=tone.name,
        source_duration_tick=duration_tick,
    )
    doc.media.append(asset)
    doc.playlist.entries.append(
        SongInstance(asset_id=asset.asset_id, source_out_tick=duration_tick)
    )
    doc.validate()

    # Force even this tiny graph through the S12 file-indirection path so CI
    # proves the pinned Windows FFmpeg build supports `-/filter_complex`.
    monkeypatch.setattr(s11_graph, "FILTER_GRAPH_SCRIPT_THRESHOLD", 1)
    output = tmp_path / "external-script.mp4"
    compiled = S11FFmpegCompiler(_ffmpeg()).compile_video(
        doc,
        output,
        tmp_path / "work-real",
    )
    _script_from(compiled)
    subprocess.run(compiled.args, check=True, capture_output=True)
    assert output.exists()
    assert output.stat().st_size > 0
