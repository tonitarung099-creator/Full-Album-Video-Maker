APP_STYLE = """
QWidget {
    background: #101318;
    color: #dfe5ec;
    font-family: "Segoe UI";
    font-size: 11px;
}
QMainWindow, QDialog {
    background: #101318;
}
QWidget#panel {
    background: #151a21;
    border: 1px solid #242b35;
    border-radius: 10px;
}
QLabel#title {
    font-size: 18px;
    font-weight: 700;
    color: #f5f7fa;
    background: transparent;
}
QLabel#subtitle {
    font-size: 10px;
    color: #8e99a8;
    background: transparent;
}
QLabel#sectionTitle {
    font-size: 11px;
    font-weight: 600;
    color: #eef2f6;
    background: transparent;
}
QLabel#statusChip {
    background: #171d25;
    border: 1px solid #28313d;
    border-radius: 7px;
    padding: 5px 8px;
    color: #c8d1dc;
    font-size: 10px;
}
QGroupBox {
    background: #151a21;
    border: 1px solid #242b35;
    border-radius: 9px;
    margin-top: 15px;
    padding: 10px 8px 8px 8px;
    font-size: 10px;
    font-weight: 600;
    color: #aeb9c7;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
}
QPushButton {
    background: #202732;
    border: 1px solid #313b49;
    border-radius: 7px;
    padding: 6px 10px;
    min-height: 18px;
    font-size: 10px;
    font-weight: 500;
}
QPushButton:hover {
    background: #283241;
    border-color: #46556a;
}
QPushButton:pressed {
    background: #1b222c;
}
QPushButton:disabled {
    color: #67717f;
    background: #181d24;
    border-color: #222932;
}
QPushButton#primaryButton {
    background: #4b67d1;
    border-color: #5d78df;
    color: white;
    font-weight: 700;
    min-height: 27px;
}
QPushButton#primaryButton:hover {
    background: #5874dc;
}
QLineEdit, QPlainTextEdit, QListWidget, QComboBox, QDoubleSpinBox {
    background: #0e1217;
    border: 1px solid #28313c;
    border-radius: 7px;
    padding: 5px 7px;
    selection-background-color: #435ab0;
    font-size: 10px;
}
QLineEdit, QComboBox, QDoubleSpinBox {
    min-height: 20px;
}
QPlainTextEdit {
    padding: 7px;
}
QListWidget {
    padding: 3px;
    outline: none;
}
QListWidget::item {
    min-height: 23px;
    border-radius: 5px;
    padding: 2px 5px;
}
QListWidget::item:selected {
    background: #263247;
}
QListWidget::item:hover {
    background: #1a212b;
}
QComboBox::drop-down {
    width: 22px;
    border: none;
}
QComboBox QAbstractItemView {
    background: #151a21;
    border: 1px solid #303947;
    selection-background-color: #263247;
}
QScrollBar:vertical {
    background: transparent;
    width: 9px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #35404f;
    min-height: 28px;
    border-radius: 4px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QSplitter::handle {
    background: #0d1015;
    width: 5px;
}
QSplitter::handle:hover {
    background: #323c4a;
}
QToolTip {
    background: #202630;
    color: #eef2f6;
    border: 1px solid #3a4657;
    padding: 4px;
    font-size: 10px;
}
"""
