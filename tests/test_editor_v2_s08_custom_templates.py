from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest
from PySide6.QtWidgets import QApplication

from full_album_maker.custom_template_builder import (
    CUSTOM_TEMPLATE_FORMAT,
    CUSTOM_TEMPLATE_SUFFIX,
    CustomTemplateError,
    CustomTemplateStore,
    SetCustomTemplateMarker,
    apply_builtin_template_commands,
    apply_custom_template_commands,
    build_custom_template_layers,
    capture_custom_template,
    current_custom_template_id,
    current_template_reference,
    is_custom_template_id,
)
from full_album_maker.editor_commands import AddLayer
from full_album_maker.editor_controller import EditorController
from full_album_maker.editor_models import (
    Layer,
    MediaAsset,
    ProjectDocument,
    SongInstance,
    TimeBinding,
    Transform,
    new_id,
    seconds_to_tick,
)
from full_album_maker.render_graph import FFmpegV2Compiler
from full_album_maker.responsive_workspace import ResponsiveEditorWorkspace
from full_album_maker.template_system import (
    TEMPLATES,
    apply_template_command,
    build_template_layers,
    current_template_id,
)


def _make_audio(tmp_path: Path, name: str, frequency: int = 440) -> Path:
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


def _make_cover(tmp_path: Path, name: str, color: str = "#d34b55") -> Path:
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


def _document(tmp_path: Path, name: str = "S08") -> ProjectDocument:
    doc = ProjectDocument.new_empty(name)
    doc.canvas.width = 320
    doc.canvas.height = 240
    doc.canvas.background_color = "#121820"
    for index, (frequency, color) in enumerate(
        ((330, "#d34b55"), (550, "#4cae8a")),
        start=1,
    ):
        audio_path = _make_audio(tmp_path, f"{name}-song-{index}.wav", frequency)
        cover_path = _make_cover(tmp_path, f"{name}-cover-{index}.png", color)
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
            order=80,
            time_binding=TimeBinding(kind="album"),
            transform=Transform(
                x=0.77,
                y=0.03,
                width=0.19,
                height=0.05,
            ),
            properties={
                "text": "CUSTOM",
                "font_size": 14,
                "color": "#ffffff",
                "font_path": "C:/not-portable.ttf",
            },
            origin="manual",
        )
    )
    doc.validate()
    return doc


def _layout_document(tmp_path: Path) -> ProjectDocument:
    controller = EditorController(_document(tmp_path, "source"))
    controller.dispatch(
        apply_template_command(controller.snapshot(), "spotify_clean")
    )
    doc = controller.snapshot()
    spectrum = next(layer for layer in doc.layers if layer.type == "spectrum")
    spectrum.transform = Transform(x=0.11, y=0.70, width=0.48, height=0.13)
    spectrum.properties["color"] = "#55ffaa"
    doc.canvas.background_color = "#20242a"
    doc.validate()
    return doc


def test_capture_custom_template_is_portable_and_strips_project_only_fields(
    tmp_path: Path,
):
    doc = _layout_document(tmp_path)
    template = capture_custom_template(doc, "Layout Saya", "hasil edit canvas")
    assert template.format == CUSTOM_TEMPLATE_FORMAT
    assert is_custom_template_id(template.template_id)
    assert template.label == "Layout Saya"
    assert template.source_project_id == doc.project_id
    expected_template_layers = len(build_template_layers(doc, "spotify_clean"))
    assert len(template.layers) == expected_template_layers + 1  # + watermark manual
    assert len(template.source_layer_ids) == expected_template_layers + 1
    watermark = next(
        spec for spec in template.layers if spec["name"] == "Watermark Manual"
    )
    assert "font_path" not in watermark["properties"]
    assert all(
        "template_id" not in spec["properties"] for spec in template.layers
    )
    assert all("asset_refs" not in spec for spec in template.layers)


def test_custom_template_builds_fresh_ids_and_relinks_cover_fallback(
    tmp_path: Path,
):
    source = _layout_document(tmp_path)
    template = capture_custom_template(source, "Portabel")
    target = _document(tmp_path, "target")
    target.project_id = new_id()
    layers = build_custom_template_layers(target, template)
    source_ids = set(template.source_layer_ids)
    assert not source_ids.intersection({layer.layer_id for layer in layers})
    assert all(layer.origin == "template" for layer in layers)
    assert all(layer.time_binding.kind == "album" for layer in layers)
    cover = next(layer for layer in layers if layer.type == "song_cover")
    first_image = next(
        asset.asset_id for asset in target.media if asset.kind == "image"
    )
    assert cover.properties["fallback_asset_id"] == first_image
    assert all(
        layer.properties["template_id"] == template.template_id
        for layer in layers
    )


def test_apply_custom_same_project_removes_captured_manual_source_without_duplicates_and_undoes_once(
    tmp_path: Path,
):
    doc = _layout_document(tmp_path)
    template = capture_custom_template(doc, "Same Project")
    manual_id = next(
        layer.layer_id for layer in doc.layers if layer.name == "Watermark Manual"
    )
    controller = EditorController(doc)
    controller.dispatch(
        apply_custom_template_commands(controller.snapshot(), template)
    )
    applied = controller.snapshot()
    assert current_template_reference(applied) == template.template_id
    assert current_template_id(applied) == ""
    assert current_custom_template_id(applied) == template.template_id
    assert manual_id not in applied.layer_map()
    assert (
        len(
            [
                layer
                for layer in applied.layers
                if layer.name == "Watermark Manual"
            ]
        )
        == 1
    )
    assert all(layer.origin == "template" for layer in applied.layers)

    controller.undo()
    restored = controller.snapshot()
    assert manual_id in restored.layer_map()
    assert current_template_id(restored) == "spotify_clean"
    assert current_custom_template_id(restored) == ""


def test_apply_custom_to_other_project_preserves_unrelated_manual_layer(
    tmp_path: Path,
):
    source = _layout_document(tmp_path)
    template = capture_custom_template(source, "Other Project")
    target = _document(tmp_path, "other")
    target.project_id = new_id()
    manual_id = target.layers[0].layer_id
    controller = EditorController(target)
    controller.dispatch(
        apply_custom_template_commands(controller.snapshot(), template)
    )
    applied = controller.snapshot()
    assert manual_id in applied.layer_map()
    assert applied.layer_map()[manual_id].origin == "manual"
    assert current_custom_template_id(applied) == template.template_id


def test_builtin_apply_clears_custom_marker_in_same_undo_transaction(
    tmp_path: Path,
):
    doc = _document(tmp_path, "marker")
    controller = EditorController(doc)
    fake_custom = capture_custom_template(
        _layout_document(tmp_path),
        "Marker",
    )
    controller.dispatch(SetCustomTemplateMarker(fake_custom.template_id))
    before = controller.snapshot()
    assert current_custom_template_id(before) == fake_custom.template_id

    built = apply_template_command(before, "minimal_spectrum")
    controller.dispatch(apply_builtin_template_commands(before, built))
    applied = controller.snapshot()
    assert current_template_id(applied) == "minimal_spectrum"
    assert current_custom_template_id(applied) == ""

    controller.undo()
    restored = controller.snapshot()
    assert current_custom_template_id(restored) == fake_custom.template_id


def test_store_roundtrip_export_import_collision_and_corrupt_scan(tmp_path: Path):
    source = _layout_document(tmp_path)
    store = CustomTemplateStore(tmp_path / "store-a")
    template = store.create_from_document(source, "Template Lokal", "uji")
    loaded = store.load(template.template_id)
    assert loaded.to_dict() == template.to_dict()

    exported = store.export_template(
        template.template_id,
        tmp_path / "share-template",
    )
    assert exported.name.endswith(CUSTOM_TEMPLATE_SUFFIX)
    assert exported.exists()

    other = CustomTemplateStore(tmp_path / "store-b")
    imported = other.import_template(exported)
    assert imported.template_id == template.template_id
    imported_again = other.import_template(exported)
    assert imported_again.template_id != template.template_id
    assert imported_again.label == template.label

    (other.root / f"broken{CUSTOM_TEMPLATE_SUFFIX}").write_text(
        "{broken",
        encoding="utf-8",
    )
    valid, errors = other.scan()
    assert len(valid) == 2
    assert len(errors) == 1
    assert "broken" in errors[0]


def test_capture_rejects_asset_backed_background_instead_of_saving_stale_path(
    tmp_path: Path,
):
    doc = _document(tmp_path, "asset-bg")
    visual_track = next(track for track in doc.tracks if track.kind == "visual")
    image = next(asset for asset in doc.media if asset.kind == "image")
    doc.layers.append(
        Layer(
            track_id=visual_track.track_id,
            type="background",
            name="Background External",
            order=2,
            time_binding=TimeBinding(kind="album"),
            properties={
                "mode": "asset",
                "fit": "fill",
                "playback": "loop",
                "motion": "static",
            },
            asset_refs=[image.asset_id],
            origin="manual",
        )
    )
    with pytest.raises(
        CustomTemplateError,
        match="bergantung asset|background image/video",
    ):
        capture_custom_template(doc, "Harus Gagal")


def test_workspace_loads_custom_catalog_and_applies_it(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    doc = _layout_document(tmp_path)
    store = CustomTemplateStore(tmp_path / "ui-store")
    template = store.create_from_document(doc, "UI Custom", "template UI")
    workspace = ResponsiveEditorWorkspace(
        _document(tmp_path, "ui-target"),
        custom_template_root=store.root,
    )
    try:
        # public built-ins + separator + one custom template
        assert workspace.template_combo.count() == len(TEMPLATES) + 2
        index = workspace.template_combo.findData(template.template_id)
        assert index >= 0
        workspace.template_combo.setCurrentIndex(index)
        assert workspace.export_custom_template_btn.isEnabled()
        assert workspace.delete_custom_template_btn.isEnabled()
        workspace._apply_template_s07()
        applied = workspace.document()
        assert current_custom_template_id(applied) == template.template_id
        assert (
            len(
                [
                    layer
                    for layer in applied.layers
                    if layer.origin == "template"
                ]
            )
            == len(template.layers)
        )
        assert workspace.session.can_undo
    finally:
        workspace.close()
        workspace.deleteLater()
        app.processEvents()


def test_custom_template_real_ffmpeg_render_after_cross_project_apply(
    tmp_path: Path,
):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/ffprobe tidak tersedia")

    source = _layout_document(tmp_path)
    template = capture_custom_template(source, "Render Custom")
    target = _document(tmp_path, "render-target")
    target.project_id = new_id()
    controller = EditorController(target)
    controller.dispatch(
        apply_custom_template_commands(controller.snapshot(), template)
    )
    rendered_doc = controller.snapshot()

    output = tmp_path / "custom-template.mp4"
    compiled = FFmpegV2Compiler(ffmpeg).compile_video(
        rendered_doc,
        output,
        tmp_path / "work-custom-template",
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
