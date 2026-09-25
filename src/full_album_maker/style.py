APP_STYLE = """
* {
    font-family: "Segoe UI";
    font-size: 10px;
    color: #e8edf4;
}
QMainWindow, QDialog, QWidget {
    background: #0a0e14;
}
QWidget#root {
    background: #0a0e14;
}
QFrame#headerBar {
    background: #0d131b;
    border: 1px solid #1b2633;
    border-radius: 10px;
}
QFrame#panel, QFrame#card, QFrame#welcomeCard, QFrame#renderCard {
    background: #101722;
    border: 1px solid #243143;
    border-radius: 10px;
}
QFrame#card {
    background: #0d141e;
}
QFrame#welcomeCard {
    background: #111a27;
    border-color: #293a52;
}
QFrame#renderCard {
    background: #0d1622;
    border-color: #29384c;
}
QLabel {
    background: transparent;
}
QLabel#brandTitle {
    font-size: 22px;
    font-weight: 700;
    color: #f7f9fc;
}
QLabel#brandAccent {
    font-size: 22px;
    font-weight: 700;
    color: #48c9ff;
}
QLabel#brandSubtitle {
    font-size: 8px;
    font-weight: 600;
    color: #8190a3;
    letter-spacing: 2px;
}
QLabel#panelTitle {
    font-size: 12px;
    font-weight: 700;
    color: #f3f6fa;
}
QLabel#sectionTitle {
    font-size: 10px;
    font-weight: 700;
    color: #cbd5e1;
}
QLabel#muted {
    font-size: 9px;
    color: #7f8da1;
}
QLabel#statusChip {
    background: #121c29;
    border: 1px solid #29394e;
    border-radius: 7px;
    padding: 4px 7px;
    color: #cbd5e1;
    font-size: 9px;
}
QLabel#readyTitle {
    font-size: 11px;
    font-weight: 700;
    color: #f4f7fb;
}
QPushButton, QToolButton {
    background: #172231;
    border: 1px solid #2a3a4e;
    border-radius: 7px;
    padding: 5px 9px;
    min-height: 20px;
    color: #dbe4ef;
    font-size: 9px;
    font-weight: 600;
}
QPushButton:hover, QToolButton:hover {
    background: #1d2b3c;
    border-color: #415775;
}
QPushButton:pressed, QToolButton:pressed {
    background: #111a25;
}
QPushButton:disabled, QToolButton:disabled {
    color: #596779;
    background: #111821;
    border-color: #202a36;
}
QPushButton#primaryButton {
    background: #5d45e8;
    border: 1px solid #755cff;
    color: white;
    font-size: 10px;
    font-weight: 700;
    min-height: 28px;
}
QPushButton#primaryButton:hover {
    background: #6c54ef;
}
QPushButton#renderButton {
    background: #5144df;
    border: 1px solid #5cdbff;
    color: white;
    font-size: 12px;
    font-weight: 700;
    min-height: 36px;
    border-radius: 9px;
}
QPushButton#renderButton:hover {
    background: #6255e8;
}
QPushButton#quickAction {
    text-align: left;
    background: #121c2a;
    border-color: #293a52;
    padding: 7px 10px;
    min-height: 24px;
    font-weight: 500;
}
QPushButton#quickAction:hover {
    background: #172439;
    border-color: #6557e8;
}
QLineEdit, QPlainTextEdit, QListWidget, QComboBox, QDoubleSpinBox {
    background: #090f17;
    border: 1px solid #253448;
    border-radius: 7px;
    padding: 5px 7px;
    selection-background-color: #5144c9;
    color: #e7edf5;
    font-size: 9px;
}
QLineEdit, QComboBox, QDoubleSpinBox {
    min-height: 20px;
}
QPlainTextEdit {
    padding: 7px;
}
QListWidget {
    padding: 4px;
    outline: none;
}
QListWidget::item {
    min-height: 29px;
    border-radius: 6px;
    padding: 3px 6px;
    border-bottom: 1px solid #151f2c;
}
QListWidget::item:selected {
    background: #1e2b43;
    border: 1px solid #5a4ce0;
}
QListWidget::item:hover {
    background: #141f2d;
}
QComboBox::drop-down {
    width: 20px;
    border: none;
}
QComboBox QAbstractItemView {
    background: #101722;
    border: 1px solid #2b3b50;
    selection-background-color: #2a3760;
    padding: 3px;
}
QTabWidget::pane {
    border: 1px solid #243143;
    background: #0d141e;
    border-radius: 8px;
    top: -1px;
}
QTabBar::tab {
    background: #111927;
    color: #97a5b7;
    border: 1px solid #243143;
    padding: 6px 12px;
    min-width: 74px;
    font-size: 9px;
    font-weight: 600;
}
QTabBar::tab:first {
    border-top-left-radius: 7px;
    border-bottom-left-radius: 7px;
}
QTabBar::tab:last {
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
}
QTabBar::tab:selected {
    background: #202451;
    color: #ffffff;
    border-color: #6c56f0;
}
QCheckBox {
    spacing: 7px;
    color: #cbd5e1;
    font-size: 9px;
}
QCheckBox::indicator {
    width: 30px;
    height: 16px;
    border-radius: 8px;
    background: #263241;
    border: 1px solid #35465c;
}
QCheckBox::indicator:checked {
    background: #5e49e8;
    border-color: #7a68ff;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #34455a;
    min-height: 26px;
    border-radius: 4px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QSplitter::handle {
    background: #080c12;
    width: 5px;
}
QSplitter::handle:hover {
    background: #314159;
}
QToolTip {
    background: #182231;
    color: #f0f4f8;
    border: 1px solid #40536d;
    padding: 4px;
    font-size: 9px;
}
"""
