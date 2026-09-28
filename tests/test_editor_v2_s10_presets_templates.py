from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageStat
import pytest
from PySide6.QtWidgets import QApplication

from full_album_maker.custom_template_builder import (
    build_custom_template_layers,
    capture_custom_template,
)
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
from full_album_maker.overlay_effects import (
    CIRCULAR_SPECTRUM_STATUS,
    EFFECT_PRESETS,
    make_effect_properties,
    normalize_effect_properties,
)
from full_album_maker.render_graph import FFmpegV2Compiler
from full_album_maker.s10_workspace import S10EditorWorkspace
from full_album_maker.spectrum_feature import SPECTRUM_PRESETS
from full_album_maker.template_system import (
    TEMPLATES,
    apply_template_command,
    build_template_layers,
)
from full_album_maker.template_thumbnail import render_template_thumbnail


REQUIRED_SPECTRUM_PRESETS = {
    "mirror",
    "neon_bars",
    "minimal_bars",
    "bass_bars",
    "thin_line",
}


def _ffmpeg() -> str:
    value = shutil.which("ffmpeg")
    if not value:
        pytest.skip("FFmpeg tidak tersedia")
    return value


def _audio(tmp_path: Path) -> Path:
    path = tmp_path / "s10.wav"
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
            "sine=frequency=420:duration=0.55",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(path),
        ],
        check=True,
    )
    return path


def _cover(tmp_path: Path) -> Path:
    path = tmp_path / "s10-cover.png"
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
            "color=c=#8057a8:s=160x160:d=0.1",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
    )
    return path


def _document(tmp_path: Path, *, white: bool = False) -> ProjectDocument:
    tmp_path.mkdir(parents=True, exist_ok=True)
    doc = ProjectDocument.new_empty("S10")
    doc.canvas.width = 320
    doc.canvas.height = 240
    doc.canvas.background_color = "#ffffff" if white else "#10131a"
    audio_path = _audio(tmp_path)
    cover_path = _cover(tmp_path)
    audio = MediaAsset(
        kind="audio",
        locator=str(audio_path),
        source_duration_tick=seconds_to_tick(0.55),
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
            display_title="S10 Test",
            display_artist="Full Album Maker",
            cover_asset_id=cover.asset_id,
        )
    )
    doc.validate()
    return doc


def test_s10_has_exactly_ten_public_templates_and_required_spectrum_presets(
    tmp_path: Path,
):
    doc = _document(tmp_path)
    assert len(TEMPLATES) == 10
    assert REQUIRED_SPECTRUM_PRESETS.issubset(SPECTRUM_PRESETS)
    for template_id in TEMPLATES:
        layers = build_template_layers(doc, template_id)
        doc_copy = doc.clone()
        doc_copy.layers = layers
        doc_copy.validate()
        assert any(layer.type == "spectrum" for layer in layers)
        assert any(layer.type == "background" for layer in layers)


def test_overlay_presets_are_bounded_and_reject_unknown_or_unbounded_values():
    assert {
        "vignette",
        "bokeh",
        "light_leak",
        "particles",
        "film_grain",
        "vhs_noise",
        "glow",
    }.issubset(EFFECT_PRESETS)
    for preset in EFFECT_PRESETS:
        props = make_effect_properties(preset, seed=123)
        assert props["effect_preset"] == preset
        assert 1 <= props["count"] <= 12
        assert 0 <= props["intensity"] <= 1
        assert 0 <= props["speed"] <= 4

    with pytest.raises(ValueError, match="belum didukung"):
        normalize_effect_properties({"effect_preset": "circular_fake"})
    with pytest.raises(ValueError, match="1..12"):
        normalize_effect_properties(
            {"effect_preset": "particles", "count": 5000}
        )
    with pytest.raises(ValueError, match="0..4"):
        normalize_effect_properties(
            {"effect_preset": "particles", "speed": 999}
        )


def test_circular_spectrum_is_explicitly_deferred_not_faked():
    assert CIRCULAR_SPECTRUM_STATUS["available"] is False
    assert "spike" in CIRCULAR_SPECTRUM_STATUS["reason"].casefold()
    assert "circular" not in SPECTRUM_PRESETS


@pytest.mark.parametrize("preset", ["glow", "light_leak", "particles"])
def test_effect_alpha_does_not_turn_bright_canvas_into_black_box(
    tmp_path: Path,
    preset: str,
):
    ffmpeg = _ffmpeg()
    case = tmp_path / preset
    doc = _document(case, white=True)
    track = next(item for item in doc.tracks if item.kind == "visual")
    props = make_effect_properties(
        preset,
        color="#ff7dc8" if preset != "particles" else "#79dfff",
        intensity=0.28,
        speed=0.5,
        count=6 if preset == "particles" else 2,
        seed=77,
    )
    props["mode"] = "effect"
    doc.layers.append(
        Layer(
            track_id=track.track_id,
            type="background",
            name=f"FX {preset}",
            order=0,
            time_binding=TimeBinding(kind="album"),
            transform=Transform(x=0, y=0, width=1, height=1),
            properties=props,
            origin="manual",
        )
    )
    output = case / f"{preset}.png"
    compiled = FFmpegV2Compiler(ffmpeg).compile_frame(
        doc,
        seconds_to_tick(0.25),
        output,
        case / f"work-{preset}",
    )
    completed = subprocess.run(
        compiled.args,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert output.exists() and output.stat().st_size > 0
    with Image.open(output).convert("RGB") as image:
        mean = ImageStat.Stat(image).mean
        assert sum(mean) / 3 > 120
        extrema = image.getextrema()
        assert any(high - low > 3 for low, high in extrema)


@pytest.mark.parametrize("template_id", list(TEMPLATES))
def test_every_template_thumbnail_is_real_compiler_render_and_source_is_unchanged(
    tmp_path: Path,
    template_id: str,
):
    ffmpeg = _ffmpeg()
    case = tmp_path / template_id
    doc = _document(case)
    before = doc.content_signature()
    output = case / f"{template_id}-thumbnail.png"
    result = render_template_thumbnail(
        doc,
        template_id,
        output,
        ffmpeg=ffmpeg,
    )
    assert Path(result) == output.resolve()
    assert output.exists() and output.stat().st_size > 0
    assert doc.content_signature() == before
    with Image.open(output) as image:
        assert image.size == (doc.canvas.width, doc.canvas.height)
        assert image.format == "PNG"


def test_effect_layer_properties_remain_serializable_and_editable(
    tmp_path: Path,
):
    doc = _document(tmp_path)
    layers = build_template_layers(doc, "neon_spectrum")
    particles = next(
        layer
        for layer in layers
        if layer.properties.get("effect_preset") == "particles"
    )
    clone = deepcopy(particles)
    clone.opacity = 0.17
    clone.transform.x = -0.05
    clone.transform.width = 1.1
    clone.validate()
    assert clone.properties["seed"] == particles.properties["seed"]
    assert clone.opacity != particles.opacity


def test_procedural_effect_survives_custom_template_roundtrip(
    tmp_path: Path,
):
    source = _document(tmp_path / "custom-source")
    controller = EditorController(source)
    controller.dispatch(
        apply_template_command(controller.snapshot(), "neon_spectrum")
    )
    built = controller.snapshot()
    template = capture_custom_template(
        built,
        "Neon Portable",
        "Effect procedural tanpa asset eksternal",
    )
    effect_specs = [
        spec
        for spec in template.layers
        if spec.get("properties", {}).get("mode") == "effect"
    ]
    assert effect_specs
    assert {
        spec["properties"]["effect_preset"] for spec in effect_specs
    } >= {"glow", "particles"}
    assert all("asset_id" not in spec["properties"] for spec in effect_specs)

    target = _document(tmp_path / "custom-target")
    rebuilt = build_custom_template_layers(target, template)
    rebuilt_effects = [
        layer
        for layer in rebuilt
        if layer.properties.get("mode") == "effect"
    ]
    assert len(rebuilt_effects) == len(effect_specs)
    for layer in rebuilt_effects:
        props = normalize_effect_properties(layer.properties)
        assert props["seed"] == layer.properties["seed"]
        assert layer.asset_refs == []


def test_s10_workspace_exposes_actual_render_preview_card_without_blocking_tests(
    tmp_path: Path,
):
    app = QApplication.instance() or QApplication([])
    workspace = S10EditorWorkspace(
        _document(tmp_path / "ui-card"),
        template_preview_enabled=False,
    )
    try:
        assert workspace.template_preview_card_s10 is not None
        assert workspace.template_preview_image_s10.size().width() == 160
        assert workspace.template_preview_image_s10.size().height() == 90
        assert workspace.template_combo.count() == 10
        first_id = str(workspace.template_combo.currentData() or "")
        assert first_id == "spotify_clean"
        assert workspace.template_preview_title_s10.text() == "Spotify Clean"
        assert (
            "dinonaktifkan"
            in workspace.template_preview_status_s10.text().casefold()
        )

        neon_index = workspace.template_combo.findData("neon_spectrum")
        assert neon_index >= 0
        workspace.template_combo.setCurrentIndex(neon_index)
        app.processEvents()
        assert workspace.template_preview_title_s10.text() == "Neon Spectrum"
        assert (
            "glow"
            in workspace.template_preview_description_s10.text().casefold()
        )
    finally:
        workspace.close()
        workspace.deleteLater()
        app.processEvents()
