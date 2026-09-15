from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox
from app.database import db


def authenticate_pin(pin):
    pin = str(pin or '').strip()
    if not pin:
        return None
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE pin=? AND active=1 ORDER BY CASE role WHEN 'ADMIN' THEN 0 ELSE 1 END,id LIMIT 1", (pin,)).fetchone()
    return dict(row) if row else None


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.user = None
        self.setWindowTitle('Ingreso al sistema')
        self.setModal(True)
        self.setFixedSize(470, 390)
        root = QVBoxLayout(self)
        root.setContentsMargins(38, 34, 38, 34)
        root.setSpacing(16)
        title = QLabel('🍦 HELADERÍA')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet('font-size:31px;font-weight:950;color:#4d2034;')
        sub = QLabel('INGRESO DE OPERADOR')
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet('font-size:16px;font-weight:900;color:#7a6670;')
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin.setInputMethodHints(Qt.InputMethodHint.ImhDigitsOnly)
        self.pin.setPlaceholderText('PIN')
        self.pin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pin.setMaxLength(12)
        self.pin.setStyleSheet('font-size:28px;padding:16px;border:2px solid #e3ccd7;border-radius:14px;background:white;')
        self.pin.returnPressed.connect(self.try_login)
        info = QLabel('Ingresá tu PIN personal. El sistema habilita únicamente las funciones permitidas para ese usuario.')
        info.setWordWrap(True)
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setStyleSheet('color:#7a6670;font-size:13px;')
        button = QPushButton('INGRESAR')
        button.setMinimumHeight(62)
        button.setStyleSheet('background:#e94f86;color:white;font-size:20px;font-weight:950;border-radius:14px;')
        button.clicked.connect(self.try_login)
        root.addWidget(title)
        root.addWidget(sub)
        root.addSpacing(6)
        root.addWidget(self.pin)
        root.addWidget(button)
        root.addWidget(info)
        root.addStretch()
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self.reject)
        self.pin.setFocus()

    def try_login(self):
        user = authenticate_pin(self.pin.text())
        if not user:
            QMessageBox.warning(self, 'Ingreso', 'PIN incorrecto o usuario deshabilitado.')
            self.pin.selectAll()
            self.pin.setFocus()
            return
        self.user = user
        self.accept()
