from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl, QTimer, Qt
from PyQt6.QtWidgets import *
from app.settings_service import get_setting, set_setting


class ToggleButton(QPushButton):
    def __init__(self, label, checked=False):
        super().__init__()
        self.label = label
        self.setCheckable(True)
        self.setMinimumHeight(58)
        self.setChecked(bool(checked))
        self.toggled.connect(self.refresh_visual)
        self.refresh_visual(self.isChecked())

    def refresh_visual(self, checked):
        self.setText(f"{'✓' if checked else '○'}  {self.label}\n{'ACTIVADO' if checked else 'DESACTIVADO'}")
        bg = '#25b86b' if checked else '#eee7ea'
        fg = 'white' if checked else '#5d4b54'
        self.setStyleSheet(f'background:{bg};color:{fg};font-size:14px;font-weight:900;text-align:left;padding:8px 14px;border:2px solid {"#159552" if checked else "#d7cbd0"};')


class WebPanelPage(QWidget):
    def __init__(self, back_callback, manager):
        super().__init__()
        self.manager = manager
        self.back_callback = back_callback
        self.build_ui()
        self.manager.status_changed.connect(self.refresh_status)
        self.manager.output.connect(self.append_log)
        self.refresh_status(self.manager.is_running())
        # Entrar al módulo = intentar levantarlo. Sin pasos escondidos.
        if not self.manager.is_running():
            QTimer.singleShot(250, self.start_server)

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 28)
        root.setSpacing(14)
        h = QHBoxLayout()
        back = QPushButton('← Volver a Opciones')
        back.setStyleSheet('background:#eee5ea;color:#4a3740;')
        back.clicked.connect(self.back_callback)
        title = QLabel('🌐 Panel Web de Control')
        title.setStyleSheet('font-size:28px;font-weight:900;')
        h.addWidget(back)
        h.addSpacing(14)
        h.addWidget(title)
        h.addStretch()
        root.addLayout(h)

        info = QLabel('Este panel usa la MISMA base de datos que la caja. Al entrar acá el servidor se inicia automáticamente. Desde el celular vas a poder mirar ventas, detalle vendido, stock, pedidos, caja y puntos.')
        info.setWordWrap(True)
        info.setStyleSheet('color:#6f5c66;font-size:15px;')
        root.addWidget(info)

        self.status_card = QFrame()
        self.status_card.setStyleSheet('background:#f2f2f2;border:2px solid #ddd;border-radius:18px;')
        sc = QVBoxLayout(self.status_card)
        self.status = QLabel('COMPROBANDO SERVIDOR...')
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet('font-size:26px;font-weight:950;padding:10px;')
        sc.addWidget(self.status)
        self.url = QLineEdit()
        self.url.setReadOnly(True)
        self.url.setMinimumHeight(48)
        self.url.setStyleSheet('font-size:19px;font-weight:800;background:white;')
        sc.addWidget(self.url)
        help_text = QLabel('En el celular: conectate al mismo Wi‑Fi → abrí esta dirección → ingresá el PIN web.')
        help_text.setWordWrap(True)
        help_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        help_text.setStyleSheet('color:#67545e;font-size:14px;')
        sc.addWidget(help_text)
        root.addWidget(self.status_card)

        box = QFrame()
        box.setStyleSheet('background:white;border:1px solid #eadfe4;border-radius:16px;')
        form = QFormLayout(box)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(int(get_setting('web_port', '5050')))
        self.pin = QLineEdit(get_setting('web_pin', '2580'))
        self.pin.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin.setMinimumHeight(42)
        self.portal_base = QLineEdit(get_setting('portal_base_url', ''))
        self.portal_base.setPlaceholderText('Opcional · ej. https://miheladeria.com')
        self.portal_base.setMinimumHeight(42)
        self.auto = ToggleButton('Iniciar automáticamente junto con el sistema', get_setting('web_auto_start', '0') == '1')
        self.auto.toggled.connect(lambda checked: set_setting('web_auto_start', '1' if checked else '0'))
        form.addRow('Puerto web', self.port)
        form.addRow('PIN web', self.pin)
        form.addRow('URL pública portal', self.portal_base)
        form.addRow('', self.auto)
        root.addWidget(box)

        actions = QGridLayout()
        self.start = QPushButton('▶ INICIAR / APLICAR')
        self.start.setStyleSheet('background:#26b96e;color:white;')
        self.start.clicked.connect(self.start_server)
        self.open = QPushButton('🌐 ABRIR PANEL AHORA')
        self.open.setStyleSheet('background:#3d91e6;color:white;')
        self.open.clicked.connect(self.open_browser)
        copy = QPushButton('📋 COPIAR DIRECCIÓN')
        copy.setStyleSheet('background:#8059c8;color:white;')
        copy.clicked.connect(self.copy_url)
        portal = QPushButton('⭐ QR / PORTAL CLIENTE')
        portal.setStyleSheet('background:#e94f86;color:white;')
        portal.clicked.connect(self.open_portal_qr)
        restart = QPushButton('↻ REINICIAR WEB')
        restart.setStyleSheet('background:#f28b32;color:white;')
        restart.clicked.connect(self.restart_server)
        self.stop = QPushButton('■ DETENER')
        self.stop.setStyleSheet('background:#e86464;color:white;')
        self.stop.clicked.connect(self.manager.stop)
        for btn in (self.start, self.open, copy, portal, restart, self.stop):
            btn.setMinimumHeight(52)
        actions.addWidget(self.start, 0, 0)
        actions.addWidget(self.open, 0, 1)
        actions.addWidget(copy, 0, 2)
        actions.addWidget(portal, 1, 0)
        actions.addWidget(restart, 1, 1)
        actions.addWidget(self.stop, 1, 2)
        root.addLayout(actions)

        root.addWidget(QLabel('Registro del servidor (si no inicia, acá aparece el motivo):'))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(180)
        root.addWidget(self.log)
        root.addStretch()

    def save(self):
        old_port = get_setting('web_port', '5050')
        set_setting('web_port', self.port.value())
        set_setting('web_pin', self.pin.text().strip() or '2580')
        set_setting('web_auto_start', '1' if self.auto.isChecked() else '0')
        set_setting('portal_base_url', self.portal_base.text().strip())
        return str(old_port) != str(self.port.value())

    def start_server(self):
        changed_port = self.save()
        if changed_port and self.manager.owns_process():
            self.manager.restart()
        else:
            self.manager.start()
        QTimer.singleShot(1100, lambda: self.refresh_status(self.manager.is_running()))

    def restart_server(self):
        self.save()
        self.manager.restart()
        QTimer.singleShot(1100, lambda: self.refresh_status(self.manager.is_running()))

    def open_browser(self):
        self.save()
        if not self.manager.is_running():
            self.manager.start()
            QTimer.singleShot(900, lambda: QDesktopServices.openUrl(QUrl(self.manager.local_url())))
        else:
            QDesktopServices.openUrl(QUrl(self.manager.local_url()))

    def open_portal_qr(self):
        self.save()
        if not self.manager.is_running():
            self.manager.start()
            QTimer.singleShot(900, lambda: QDesktopServices.openUrl(QUrl(self.manager.local_url() + '/portal/qr')))
        else:
            QDesktopServices.openUrl(QUrl(self.manager.local_url() + '/portal/qr'))

    def copy_url(self):
        QApplication.clipboard().setText(self.manager.url())
        QMessageBox.information(self, 'Panel Web', 'Dirección copiada. Pegala en el navegador del celular.')

    def refresh_status(self, running):
        self.url.setText(self.manager.url())
        if running:
            self.status.setText('🟢 SERVIDOR WEB ACTIVO')
            self.status.setStyleSheet('font-size:26px;font-weight:950;color:#157a45;padding:10px;')
            self.status_card.setStyleSheet('background:#eaf9f0;border:2px solid #25b86b;border-radius:18px;')
        else:
            self.status.setText('🔴 SERVIDOR WEB APAGADO')
            self.status.setStyleSheet('font-size:26px;font-weight:950;color:#a93f55;padding:10px;')
            self.status_card.setStyleSheet('background:#fff0f2;border:2px solid #e86464;border-radius:18px;')
        self.stop.setEnabled(running)
        self.open.setEnabled(True)

    def append_log(self, text):
        if text.strip():
            self.log.appendPlainText(text.rstrip())
