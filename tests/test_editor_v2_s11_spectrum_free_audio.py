from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from full_album_maker.editor_controller import EditorController
from full_album_maker.editor_models import (
    MediaAsset,
    ProjectDocument,
    SongInstance,
    seconds_to_tick,
)
from full_album_maker.free_timeline import SetPlaylistTimingMode, SetSongFreeTiming
from full_album_maker.s11_render_graph import S11FFmpegCompiler
from full_album_maker.spectrum_feature import make_spectrum_layer


def _ffmpeg() -> str:
    value = shutil.which("ffmpeg")
    if not value:
        pytest.skip("FFmpeg tidak tersedia")
    return value


def _make_audio(path: Path, frequency: int) -> Path:
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
            f"sine=frequency={frequency}:duration=0.45",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(path),
        ],
        check=True,
    )
    return path


def test_free_timeline_spectrum_uses_same_mixed_album_audio(tmp_path: Path):
    ffmpeg = _ffmpeg()
    doc = ProjectDocument.new_empty("S11 Spectrum Free")
    doc.canvas.width = 320
    doc.canvas.height = 240

    for index, frequency in enumerate((330, 660)):
        path = _make_audio(tmp_path / f"audio-{index}.wav", frequency)
        asset = MediaAsset(
            kind="audio",
            locator=str(path),
            source_duration_tick=seconds_to_tick(0.45),
        )
        doc.media.append(asset)
        doc.playlist.entries.append(
            SongInstance(
                asset_id=asset.asset_id,
                source_out_tick=asset.source_duration_tick,
                display_title=f"Track {index + 1}",
            )
        )

    visual_track = next(track for track in doc.tracks if track.kind == "visual")
    doc.layers.append(
        make_spectrum_layer(
            visual_track.track_id,
            0,
            preset_id="minimal_bars",
        )
    )
    doc.validate()

    controller = EditorController(doc)
    controller.dispatch(SetPlaylistTimingMode("free"))
    second = controller.snapshot().playlist.entries[1]
    controller.dispatch(
        SetSongFreeTiming(second.song_id, seconds_to_tick(0.8), 0)
    )
    free_doc = controller.snapshot()

    output = tmp_path / "free-spectrum.mp4"
    compiled = S11FFmpegCompiler(ffmpeg).compile_video(
        free_doc,
        output,
        tmp_path / "work",
    )
    graph = compiled.args[compiled.args.index("-filter_complex") + 1]
    assert "anullsrc" in graph
    assert "amix=" in graph
    assert "[album_audio]asplit=2[aout][specaudio0]" in graph
    assert "showfreqs" in graph or "showwaves" in graph

    completed = subprocess.run(
        compiled.args,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert output.exists() and output.stat().st_size > 0