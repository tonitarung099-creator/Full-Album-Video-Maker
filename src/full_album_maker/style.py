APP_STYLE = """
* {
    font-family: "Segoe UI";
    font-size: 9px;
    color: #e7edf7;
}
QMainWindow, QDialog, QWidget {
    background: #07101c;
}
QWidget#root {
    background: #07101c;
}
QFrame#headerBar {
    background: #0a1423;
    border: 1px solid #173354;
    border-radius: 12px;
}
QFrame#panel {
    background: #091524;
    border: 1px solid #263b61;
    border-radius: 12px;
}
QFrame#mediaCard, QFrame#settingCard, QFrame#calcCard {
    background: #0d1b2d;
    border: 1px solid #21395c;
    border-radius: 9px;
}
QFrame#settingCard {
    background: #101d31;
}
QFrame#calcCard {
    background: #0d1929;
}
QFrame#bottomBar {
    background: #0b1526;
    border: 1px solid #223a60;
    border-radius: 10px;
}
QLabel {
    background: transparent;
}
QLabel#brandTitle {
    font-size: 23px;
    font-weight: 800;
    color: #f7f9ff;
}
QLabel#brandSubtitle {
    font-size: 10px;
    font-weight: 500;
    color: #c4cee0;
}
QLabel#panelTitle {
    font-size: 13px;
    font-weight: 800;
    color: #f5f8ff;
}
QLabel#sectionTitle {
    font-size: 10px;
    font-weight: 700;
    color: #eef3fb;
}
QLabel#muted {
    font-size: 8px;
    color: #94a2b7;
}
QLabel#legend {
    font-size: 8px;
    color: #adbbce;
}
QLabel#mediaSummary {
    background: #10243a;
    border: 1px solid #214d71;
    border-radius: 7px;
    padding: 6px 8px;
    color: #dce7f6;
    font-weight: 600;
}
QLabel#timelineStatusReady {
    background: #082d24;
    border: 1px solid #17dd84;
    border-radius: 8px;
    padding: 6px 10px;
    color: #42f59a;
    font-weight: 800;
}
QLabel#timelineStatusPending {
    background: #2b2010;
    border: 1px solid #c4902d;
    border-radius: 8px;
    padding: 6px 10px;
    color: #ffc968;
    font-weight: 700;
}
QLabel#calcPurple {
    font-size: 15px;
    font-weight: 800;
    color: #e35dff;
}
QLabel#calcCyan {
    font-size: 15px;
    font-weight: 800;
    color: #25d9ff;
}
QLabel#calcPink {
    font-size: 15px;
    font-weight: 800;
    color: #ff527c;
}
QLabel#statusChip {
    background: #101d31;
    border: 1px solid #2b4064;
    border-radius: 7px;
    padding: 4px 7px;
    color: #c9d4e5;
    font-size: 8px;
}
QLabel#bottomMetric {
    background: transparent;
    border-right: 1px solid #203657;
    padding: 2px 9px;
    font-size: 9px;
    color: #dbe5f2;
}
QPushButton, QToolButton {
    background: #10213a;
    border: 1px solid #29486f;
    border-radius: 7px;
    padding: 5px 8px;
    min-height: 20px;
    color: #e2e9f5;
    font-size: 9px;
    font-weight: 600;
}
QPushButton:hover, QToolButton:hover {
    background: #172c49;
    border-color: #4a6f9d;
}
QPushButton:pressed, QToolButton:pressed {
    background: #0b1829;
}
QPushButton:disabled, QToolButton:disabled {
    color: #5f7087;
    background: #0d1724;
    border-color: #1b2a40;
}
QToolButton#headerButton {
    min-width: 96px;
    min-height: 30px;
    background: #0d1a2d;
    border-color: #304a70;
    font-size: 9px;
}
QPushButton#accentButton {
    background: #5d2ad7;
    border: 1px solid #31ddff;
    color: white;
    min-height: 26px;
    font-weight: 800;
}
QPushButton#accentButton:hover {
    background: #7135ed;
}
QPushButton#autoTimelineButton {
    min-height: 68px;
    max-height: 68px;
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #7628e8,
        stop:0.48 #6f39ff,
        stop:1 #09cbe8
    );
    border: 1px solid #a14dff;
    border-radius: 13px;
    color: #ffffff;
    font-size: 16px;
    font-weight: 900;
    padding: 10px 18px;
}
QPushButton#autoTimelineButton:hover {
    border-color: #63edff;
}
QPushButton#renderButton {
    min-height: 42px;
    max-height: 42px;
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #bd31ed,
        stop:0.45 #7743ff,
        stop:1 #13d8ed
    );
    border: 1px solid #68eaff;
    color: #ffffff;
    font-size: 12px;
    font-weight: 900;
    border-radius: 9px;
    padding: 7px 12px;
}
QPushButton#quickAction {
    text-align: left;
    background: #0d1b2f;
    border: 1px solid #2b466d;
    min-height: 25px;
    font-size: 8px;
}
QPushButton#quickAction:hover {
    border-color: #7660f0;
    background: #152744;
}
QPushButton#sendButton {
    background: #172c49;
    border: 1px solid #3b5f8b;
    font-size: 15px;
    font-weight: 800;
}
QLineEdit, QPlainTextEdit, QListWidget, QComboBox, QDoubleSpinBox {
    background: #08111d;
    border: 1px solid #284466;
    border-radius: 7px;
    padding: 5px 7px;
    selection-background-color: #593bd4;
    color: #e9f0fa;
    font-size: 9px;
}
QComboBox, QDoubleSpinBox {
    min-height: 21px;
}
QPlainTextEdit {
    padding: 7px;
}
QPlainTextEdit#chatArea {
    background: #0a1525;
    border-color: #213a5d;
    line-height: 1.3;
}
QListWidget {
    padding: 3px;
    outline: none;
    background: #08121f;
}
QListWidget::item {
    min-height: 27px;
    border-radius: 5px;
    padding: 3px 5px;
    border-bottom: 1px solid #14243a;
}
QListWidget::item:selected {
    background: #1e2f53;
    border: 1px solid #7154ef;
}
QListWidget::item:hover {
    background: #112139;
}
QComboBox::drop-down {
    width: 20px;
    border: none;
}
QComboBox QAbstractItemView {
    background: #0c1829;
    border: 1px solid #2b466b;
    selection-background-color: #2e3d73;
    padding: 3px;
}
QWidget#timelinePreview {
    background: #08111d;
    border: 1px solid #28415f;
    border-radius: 9px;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #334d70;
    min-height: 26px;
    border-radius: 4px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QSplitter#mainSplitter::handle {
    background: #050a12;
    width: 5px;
}
QSplitter#mainSplitter::handle:hover {
    background: #2f4668;
}
QToolTip {
    background: #17243a;
    color: #f3f6fb;
    border: 1px solid #42638c;
    padding: 4px;
    font-size: 8px;
}
"""
