import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from full_album_maker.editor_models import (
    Layer,
    MediaAsset,
    ProjectDocument,
    SongInstance,
    TimeBinding,
    Transform,
    seconds_to_tick,
)
from full_album_maker.editor_window import EditorMainWindow
from full_album_maker.editor_workspace import EditorWorkspace
from full_album_maker.property_inspector import PropertyInspector
from full_album_maker.style import APP_STYLE


def _doc() -> tuple[ProjectDocument, Layer, Layer]:
    doc = ProjectDocument.new_empty("UI S04")
    audio = MediaAsset(kind="audio", locator="song.wav", source_duration_tick=seconds_to_tick(5))
    doc.media.append(audio)
    doc.playlist.entries.append(SongInstance(asset_id=audio.asset_id, source_out_tick=audio.source_duration_tick))
    track = next(item for item in doc.tracks if item.kind == "visual")
    background = Layer(
        track_id=track.track_id,
        type="background",
        name="BG",
        order=0,
        time_binding=TimeBinding(kind="absolute", duration_tick=seconds_to_tick(5)),
        transform=Transform(x=0.1, y=0.1, width=0.7, height=0.7),
        properties={"mode": "solid", "color": "#223344"},
    )
    text = Layer(
        track_id=track.track_id,
        type="text",
        name="Teks",
        order=1,
        time_binding=TimeBinding(kind="absolute", duration_tick=seconds_to_tick(3)),
        transform=Transform(x=0.2, y=0.2, width=0.5, height=0.2),
        properties={"text": "Halo", "color": "#ffffff"},
    )
    doc.layers.extend([background, text])
    doc.validate()
    return doc, background, text


def _app():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLE)
    return app


def test_workspace_exposes_editor_surfaces_and_syncs_selection():
    app = _app()
    doc, background, _ = _doc()
    workspace = EditorWorkspace(doc)
    workspace.resize(860, 650)
    workspace.show()
    app.processEvents()

    assert workspace.preview.isVisible()
    assert workspace.timeline_scroll.isVisible()
    assert workspace.inspector.isVisible()
    assert workspace.playlist is not None

    workspace._select_layer(background.layer_id)
    app.processEvents()
    assert workspace.session.selected_layer_ids == [background.layer_id]
    assert workspace.inspector._layer_id == background.layer_id
    assert workspace.preview._selected_layer_id == background.layer_id

    workspace.close()


def test_property_inspector_hides_unrenderable_text_resize_rotation_controls():
    app = _app()
    doc, background, text = _doc()
    inspector = PropertyInspector()
    inspector.show()

    inspector.set_layer(text)
    app.processEvents()
    assert inspector.x.isEnabled()
    assert inspector.y.isEnabled()
    assert not inspector.w.isEnabled()
    assert not inspector.h.isEnabled()
    assert not inspector.rotation.isEnabled()
    assert inspector.text_value.isEnabled()

    inspector.set_layer(background)
    app.processEvents()
    assert inspector.w.isEnabled()
    assert inspector.h.isEnabled()
    assert inspector.rotation.isEnabled()
    assert not inspector.text_value.isEnabled()
    inspector.close()


def test_editor_main_window_fits_1366x768_and_keeps_ai_panel():
    app = _app()
    window = EditorMainWindow()
    window.resize(1366, 768)
    window.show()
    app.processEvents()

    assert window.width() <= 1366
    assert window.height() <= 768
    assert window.editor_workspace.isVisible()
    assert window.chat.isVisible()
    assert window.splitter.widget(0).isVisible()
    assert window.splitter.widget(window.splitter.count() - 1).isVisible()
    assert window.editor_workspace.geometry().right() < window.splitter.widget(window.splitter.count() - 1).geometry().left()

    window.close()


def test_zoom_changes_canvas_scale_without_mutating_project_time():
    app = _app()
    doc, background, _ = _doc()
    workspace = EditorWorkspace(doc)
    before = workspace.document().to_dict()
    workspace.zoom_slider.setValue(220)
    app.processEvents()
    after = workspace.document().to_dict()
    assert workspace.timeline.pixels_per_second == 220
    assert after == before
    assert workspace.session.global_layer_start(background.layer_id) == 0
    workspace.close()
