from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest
from PySide6.QtWidgets import QApplication

from full_album_maker.editor_controller import EditorController
from full_album_maker.editor_models import (
    Layer,
    MediaAsset,
    ProjectDocument,
    SongInstance,
    TimeBinding,
    Transform,
    seconds_to_tick,
)
from full_album_maker.render_graph import FFmpegV2Compiler
from full_album_maker.responsive_workspace import ResponsiveEditorWorkspace
from full_album_maker.template_system import (
    TEMPLATES,
    apply_template_command,
    build_template_layers,
    current_template_id,
    template_choices,
)


FINAL_TEMPLATE_IDS = [
    "spotify_clean",
    "cafe_acoustic",
    "viral_full_album",
    "vinyl_nostalgia",
    "neon_spectrum",
    "romantic_bokeh",
    "dark_cinematic",
    "photo_album",
    "cassette_retro",
    "music_channel_pro",
]


def _make_audio(tmp_path: Path, name: str, frequency: int) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg tidak tersedia")
    path = tmp_path / name
    subprocess.run(
        [
            ffmpeg,
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


def _make_cover(tmp_path: Path, name: str, color: str) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg tidak tersedia")
    path = tmp_path / name
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=128x128:d=0.1",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
    )
    return path


def _document(tmp_path: Path) -> ProjectDocument:
    doc = ProjectDocument.new_empty("S07 Template")
    doc.canvas.width = 320
    doc.canvas.height = 240
    doc.canvas.background_color = "#10151d"

    for index, (frequency, color) in enumerate(
        ((330, "#d34b55"), (550, "#4cae8a")),
        start=1,
    ):
        audio_path = _make_audio(tmp_path, f"song-{index}.wav", frequency)
        cover_path = _make_cover(tmp_path, f"cover-{index}.png", color)
        audio = MediaAsset(
            kind="audio",
            locator=str(audio_path),
            source_duration_tick=seconds_to_tick(0.45),
        )
        cover = MediaAsset(
            kind="image",
            locator=str(cover_path),
            original_name=cover_path.name,
        )
        doc.media.extend([audio, cover])
        doc.playlist.entries.append(
            SongInstance(
                asset_id=audio.asset_id,
                source_out_tick=audio.source_duration_tick,
                display_title=f"Lagu {index}",
                display_artist=f"Artis {index}",
                cover_asset_id=cover.asset_id,
            )
        )

    visual_track = next(track for track in doc.tracks if track.kind == "visual")
    doc.layers.append(
        Layer(
            track_id=visual_track.track_id,
            type="text",
            name="Watermark Manual",
            order=50,
            time_binding=TimeBinding(kind="album"),
            transform=Transform(
                x=0.80,
                y=0.03,
                width=0.16,
                height=0.05,
            ),
            properties={
                "text": "MANUAL",
                "font_size": 14,
                "color": "#ffffff",
            },
            origin="manual",
        )
    )
    doc.validate()
    return doc


def test_template_catalog_is_stable_and_each_template_builds_editable_layers(
    tmp_path: Path,
):
    doc = _document(tmp_path)
    assert [item.template_id for item in template_choices()] == FINAL_TEMPLATE_IDS
    assert list(TEMPLATES) == FINAL_TEMPLATE_IDS
    assert len(TEMPLATES) == 10
    required_types = {
        "background",
        "song_cover",
        "vinyl",
        "playlist_visual",
        "spectrum",
        "song_title",
        "progress",
        "song_time",
    }
    for template_id in TEMPLATES:
        layers = build_template_layers(doc, template_id)
        assert required_types.issubset({layer.type for layer in layers})
        assert len({layer.layer_id for layer in layers}) == len(layers)
        assert all(layer.origin == "template" for layer in layers)
        assert all(
            layer.properties.get("template_id") == template_id
            for layer in layers
        )
        assert all(
            layer.transform.width >= 0.02
            and layer.transform.height >= 0.02
            for layer in layers
        )


def test_legacy_minimal_spectrum_remains_loadable_but_is_not_public_catalog(
    tmp_path: Path,
):
    doc = _document(tmp_path)
    assert "minimal_spectrum" not in TEMPLATES
    assert all(
        item.template_id != "minimal_spectrum"
        for item in template_choices()
    )
    layers = build_template_layers(doc, "minimal_spectrum")
    assert layers
    assert all(
        layer.properties.get("template_id") == "minimal_spectrum"
        for layer in layers
    )


def test_apply_template_preserves_manual_layers_replaces_previous_template_and_undoes_once(
    tmp_path: Path,
):
    doc = _document(tmp_path)
    manual_id = doc.layers[0].layer_id
    controller = EditorController(doc)

    spotify_expected = len(build_template_layers(doc, "spotify_clean"))
    controller.dispatch(
        apply_template_command(controller.snapshot(), "spotify_clean")
    )
    spotify = controller.snapshot()
    assert current_template_id(spotify) == "spotify_clean"
    assert manual_id in spotify.layer_map()
    assert (
        len([layer for layer in spotify.layers if layer.origin == "template"])
        == spotify_expected
    )

    nostalgia_expected = len(
        build_template_layers(controller.snapshot(), "vinyl_nostalgia")
    )
    controller.dispatch(
        apply_template_command(controller.snapshot(), "vinyl_nostalgia")
    )
    nostalgia = controller.snapshot()
    assert current_template_id(nostalgia) == "vinyl_nostalgia"
    assert manual_id in nostalgia.layer_map()
    assert (
        len([layer for layer in nostalgia.layers if layer.origin == "template"])
        == nostalgia_expected
    )
    assert all(
        layer.properties.get("template_id") == "vinyl_nostalgia"
        for layer in nostalgia.layers
        if layer.origin == "template"
    )

    controller.undo()
    restored = controller.snapshot()
    assert current_template_id(restored) == "spotify_clean"
    assert manual_id in restored.layer_map()
    assert (
        len([layer for layer in restored.layers if layer.origin == "template"])
        == spotify_expected
    )

    controller.undo()
    original = controller.snapshot()
    assert current_template_id(original) == ""
    assert [layer.layer_id for layer in original.layers] == [manual_id]


def test_responsive_workspace_exposes_and_applies_final_template_selector(
    tmp_path: Path,
):
    app = QApplication.instance() or QApplication([])
    workspace = ResponsiveEditorWorkspace(_document(tmp_path))
    try:
        assert workspace.template_combo.count() == 10
        assert workspace.template_combo.findData("minimal_spectrum") < 0
        index = workspace.template_combo.findData("neon_spectrum")
        assert index >= 0
        workspace.template_combo.setCurrentIndex(index)
        workspace._apply_template_s07()
        doc = workspace.document()
        assert current_template_id(doc) == "neon_spectrum"
        assert any(
            layer.origin == "template"
            and layer.properties.get("effect_preset") == "particles"
            for layer in doc.layers
        )
        assert any(
            layer.origin == "manual"
            and layer.name == "Watermark Manual"
            for layer in doc.layers
        )
        assert workspace.session.can_undo
    finally:
        workspace.close()
        workspace.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("template_id", list(TEMPLATES))
def test_each_builtin_template_real_ffmpeg_render(
    tmp_path: Path,
    template_id: str,
):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/ffprobe tidak tersedia")

    doc = _document(tmp_path)
    controller = EditorController(doc)
    controller.dispatch(
        apply_template_command(controller.snapshot(), template_id)
    )
    rendered_doc = controller.snapshot()

    output = tmp_path / f"{template_id}.mp4"
    compiled = FFmpegV2Compiler(ffmpeg).compile_video(
        rendered_doc,
        output,
        tmp_path / f"work-{template_id}",
    )
    subprocess.run(
        compiled.args,
        check=True,
        capture_output=True,
        text=True,
    )
    assert output.exists() and output.stat().st_size > 0

    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "video" in probe
    assert "audio" in probe
