import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from full_album_maker.ui import MainWindow


def test_compact_layout_has_no_panel_overlap():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1060, 680)
    window.show()
    app.processEvents()

    assert window.splitter.count() == 3
    panels = [window.splitter.widget(i) for i in range(3)]

    for panel in panels:
        assert panel.width() >= 290
        assert panel.height() > 300

    for left, right in zip(panels, panels[1:]):
        left_rect = left.geometry()
        right_rect = right.geometry()
        assert left_rect.right() < right_rect.left()

    for label in window.status_labels.values():
        assert label.width() > 100
        assert label.height() > 20

    assert window.render_btn.height() >= 36
    window.close()
