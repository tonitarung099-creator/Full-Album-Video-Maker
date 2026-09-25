import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from full_album_maker.paths import asset_path
from full_album_maker.style import APP_STYLE
from full_album_maker.ui import MainWindow


def test_mockup_layout_has_no_overlap():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLE)

    window = MainWindow()
    window.resize(1180, 820)
    window.show()
    app.processEvents()

    assert asset_path("logo.svg").exists()
    assert window.splitter.count() == 3

    left, center, right = [window.splitter.widget(i) for i in range(3)]
    assert left.width() >= 280
    assert center.width() >= 500
    assert right.width() >= 295

    assert left.geometry().right() < center.geometry().left()
    assert center.geometry().right() < right.geometry().left()

    assert window.auto_timeline_btn.height() >= 54
    assert window.timeline_preview.height() >= 240
    assert window.render_btn.height() >= 34

    window.resize(1600, 900)
    app.processEvents()
    assert window.auto_timeline_btn.height() >= 68
    assert window.timeline_preview.height() >= 250
    assert window.render_btn.height() >= 42

    assert window.video_list.width() > 220
    assert window.audio_list.width() > 220
    assert window.chat.width() > 240

    assert len(window.bottom_labels) == 6
    for label in window.bottom_labels.values():
        assert label.height() >= 34

    assert window.timeline_status.text()
    assert window.video_total.text()
    assert window.audio_total.text()

    window.close()


def test_step1_timeline_button_is_visual_only_without_media():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLE)

    window = MainWindow()
    assert window.timeline_ready is False
    assert window.project.videos == []
    assert window.project.audios == []
    window.close()
