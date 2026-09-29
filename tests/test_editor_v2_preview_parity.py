import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
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
from full_album_maker.preview_scene import PreviewCanvas


def _app():
    return QApplication.instance() or QApplication([])


def _doc():
    doc = ProjectDocument.new_empty("Preview parity")
    audio = MediaAsset(kind="audio", locator="song.wav", source_duration_tick=seconds_to_tick(4))
    doc.media.append(audio)
    doc.playlist.entries.append(SongInstance(asset_id=audio.asset_id, source_out_tick=audio.source_duration_tick))
    track = next(item for item in doc.tracks if item.kind == "visual")
    text = Layer(
        track_id=track.track_id,
        type="text",
        name="Teks",
        time_binding=TimeBinding(kind="absolute", duration_tick=seconds_to_tick(4)),
        transform=Transform(x=0.2, y=0.2, width=0.5, height=0.2),
        properties={"text": "Halo"},
    )
    doc.layers.append(text)
    doc.validate()
    return doc, text


def _mouse_press(pos: QPointF) -> QMouseEvent:
    return QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        pos,
        pos,
        pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_text_preview_drag_commits_position_without_rotation_or_resize():
    app = _app()
    doc, text = _doc()
    canvas = PreviewCanvas()
    canvas.resize(640, 360)
    canvas.set_document(doc)
    canvas.set_selected_layer(text.layer_id)
    canvas.show()
    app.processEvents()

    geometry = canvas._selected_geometry()
    assert geometry is not None
    _, _, rect, rotation_handle = geometry

    # Clicking the rotation handle on a text layer must not start an unsupported
    # rotation gesture. Move inside the rect remains supported.
    event = _mouse_press(rotation_handle)
    canvas.mousePressEvent(event)
    assert canvas._gesture is None

    inside = rect.center()
    event = _mouse_press(inside)
    canvas.mousePressEvent(event)
    assert canvas._gesture is not None
    assert canvas._gesture.mode == "move"
    canvas.releaseMouse()
    canvas._gesture = None
    canvas.close()
