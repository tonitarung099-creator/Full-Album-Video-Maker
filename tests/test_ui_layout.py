import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from full_album_maker.paths import asset_path
from full_album_maker.ui import MainWindow


def test_modern_dashboard_layout_has_no_overlap():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1120, 690)
    window.show()
    app.processEvents()

    assert asset_path("logo.svg").exists()
    assert window.splitter.count() == 3

    panels = [window.splitter.widget(i) for i in range(3)]
    for panel in panels:
        assert panel.width() >= 300
        assert panel.height() > 480

    for left, right in zip(panels, panels[1:]):
        assert left.geometry().right() < right.geometry().left()

    assert window.media_tabs.count() == 2
    assert window.agent_tabs.count() == 4
    assert window.render_btn.height() >= 36

    for label in window.status_labels.values():
        assert label.width() > 70
        assert label.height() >= 22

    assert window.video_list.width() > 200
    assert window.audio_list.width() > 200
    assert window.chat.width() > 220

    window.close()
