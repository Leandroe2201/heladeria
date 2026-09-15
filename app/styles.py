APP_STYLE = """
QMainWindow, QWidget { background: #fff9fb; color: #202124; font-family: 'Segoe UI'; }
QPushButton { border: none; border-radius: 14px; padding: 12px; font-size: 16px; font-weight: 700; }
QPushButton:hover { border: 2px solid rgba(70,45,55,0.20); }
QPushButton:pressed { padding-top: 14px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QTextEdit {
    background: white; border: 2px solid #e7dce1; border-radius: 9px; padding: 8px; font-size: 14px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 2px solid #e64f87; }
QTableWidget { background: white; alternate-background-color:#fbfcfe; border: 1px solid #e5e7eb; border-radius: 12px; gridline-color: #eef1f5; selection-background-color:#ede9fe; selection-color:#111827; }
QTableWidget::item { padding: 8px; border-bottom:1px solid #f1f5f9; }
QHeaderView::section { background: #f8fafc; color:#374151; padding: 11px 9px; border: none; border-bottom:1px solid #e5e7eb; font-weight: 900; }
QScrollBar:vertical { background:#f1f5f9; width:12px; margin:2px; border-radius:6px; }
QScrollBar::handle:vertical { background:#cbd5e1; min-height:34px; border-radius:6px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0px; }
QGroupBox { background:white; border:1px solid #e5e7eb; border-radius:12px; margin-top:10px; padding-top:10px; font-weight:800; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 4px; }
QTabWidget::pane { border:1px solid #eadfe4; border-radius:10px; background:white; }
QTabBar::tab { padding:10px 18px; background:#f3e9ee; margin-right:3px; border-top-left-radius:8px; border-top-right-radius:8px; }
QTabBar::tab:selected { background:#e64f87; color:white; }
"""

# Más saturados y distinguibles para una persona con poca experiencia en PC.
CARD_COLORS = ["#ff8fb7", "#8bdca9", "#ffd166", "#74b9ff", "#b39ddb", "#ffad7a", "#72d7cf", "#f5a3c7"]
PRODUCT_COLORS = ["#ff5f96", "#36c978", "#ffb21c", "#3f9df7", "#8d6bd1", "#ff7d45", "#22bdb2", "#e66aa2"]
