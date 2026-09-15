from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLineEdit, QPushButton, QLabel, QFrame, QMessageBox, QHBoxLayout, QScrollArea, QDoubleSpinBox, QInputDialog
from app.settings_service import get_setting, set_setting
from app.database import reset_business_data_preserve_config


class ConfiguracionPage(QWidget):
    def __init__(self, back_callback):
        super().__init__()
        self.back_callback = back_callback
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 22)
        root.setSpacing(12)

        top = QHBoxLayout()
        back = QPushButton('← Volver a Opciones')
        back.setStyleSheet('background:#eee5ea;color:#4a3740;')
        back.clicked.connect(back_callback)
        title = QLabel('⚙ Configuración general')
        title.setStyleSheet('font-size:28px;font-weight:900;')
        save_top = QPushButton('💾 GUARDAR CAMBIOS  ·  F10')
        save_top.setMinimumHeight(52)
        save_top.setStyleSheet('background:#25b86b;color:white;font-size:16px;font-weight:900;padding:10px 18px;')
        save_top.clicked.connect(self.save)
        top.addWidget(back); top.addSpacing(12); top.addWidget(title); top.addStretch(); top.addWidget(save_top)
        root.addLayout(top)

        self.status = QLabel('Modificá los datos y presioná GUARDAR CAMBIOS. Estos datos actualizan Ventas, tickets y Panel Web.')
        self.status.setWordWrap(True)
        self.status.setStyleSheet('background:#fff3d8;color:#6d5314;border-radius:10px;padding:10px;font-size:14px;font-weight:700;')
        root.addWidget(self.status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(4, 4, 4, 4)

        box = QFrame()
        box.setStyleSheet('background:white;border:1px solid #eadfe4;border-radius:14px;')
        form = QFormLayout(box)
        form.setContentsMargins(20, 20, 20, 20)
        form.setVerticalSpacing(14)
        self.store = QLineEdit(get_setting('store_name', 'Dulces Momentos'))
        self.address = QLineEdit(get_setting('store_address', ''))
        self.phone = QLineEdit(get_setting('store_phone', ''))
        self.admin_pin = QLineEdit(get_setting('admin_pin', '2580'))
        self.delivery_fee = QDoubleSpinBox()
        self.delivery_fee.setRange(0, 9999999)
        self.delivery_fee.setDecimals(0)
        self.delivery_fee.setPrefix('$ ')
        self.delivery_fee.setValue(float(get_setting('delivery_fee', '2500') or 2500))
        self.pickup_fee = QDoubleSpinBox()
        self.pickup_fee.setRange(0, 9999999)
        self.pickup_fee.setDecimals(2)
        self.pickup_fee.setSingleStep(0.01)
        self.pickup_fee.setPrefix('$ ')
        self.pickup_fee.setValue(0.0)
        self.pickup_fee.setEnabled(False)
        self.admin_pin.setEchoMode(QLineEdit.EchoMode.Password)
        self.admin_pin.setMaxLength(10)
        for widget in (self.store, self.address, self.phone, self.admin_pin, self.delivery_fee, self.pickup_fee):
            widget.setMinimumHeight(42)
        form.addRow('Nombre de la heladería *', self.store)
        form.addRow('Dirección', self.address)
        form.addRow('Teléfono', self.phone)
        form.addRow('PIN de administración *', self.admin_pin)
        form.addRow('Costo de envío delivery', self.delivery_fee)
        form.addRow('Retiro en local · SIN CARGO', self.pickup_fee)
        cl.addWidget(box)

        note = QLabel('El cambio de nombre se guarda en la base. Al volver a Ventas se actualiza el encabezado; el Panel Web toma el nuevo nombre en la siguiente carga.')
        note.setWordWrap(True)
        note.setStyleSheet('color:#715d67;font-size:14px;padding:6px;')
        cl.addWidget(note)

        save_bottom = QPushButton('💾 GUARDAR CONFIGURACIÓN AHORA')
        save_bottom.setMinimumHeight(58)
        save_bottom.setStyleSheet('background:#25b86b;color:white;font-size:18px;font-weight:900;')
        save_bottom.clicked.connect(self.save)
        cl.addWidget(save_bottom)

        danger = QFrame()
        danger.setStyleSheet('background:#fff1f2;border:2px solid #fecdd3;border-radius:14px;')
        dl = QVBoxLayout(danger)
        dl.setContentsMargins(18,16,18,18)
        danger_title = QLabel('🧹 Reiniciar / limpiar datos del negocio')
        danger_title.setStyleSheet('font-size:18px;font-weight:950;color:#9f1239;')
        danger_text = QLabel(
            'Borra clientes, tarjetas y puntos, productos, sabores, stock, pedidos, ventas, caja, '
            'proveedores, compras, gastos, ofertas, reclamos e historial operativo.\n\n'
            'SE CONSERVAN: usuarios/PIN, configuración del sistema y todas las credenciales de Mercado Pago '
            '(Access Token, Public Key, External POS ID y modo QR). Antes de borrar se crea una copia de seguridad automática.'
        )
        danger_text.setWordWrap(True)
        danger_text.setStyleSheet('color:#881337;font-size:13px;')
        wipe_btn = QPushButton('🗑 LIMPIAR BASE DE DATOS')
        wipe_btn.setMinimumHeight(54)
        wipe_btn.setStyleSheet('background:#be123c;color:white;font-size:16px;font-weight:950;')
        wipe_btn.clicked.connect(self.clean_database)
        dl.addWidget(danger_title); dl.addWidget(danger_text); dl.addWidget(wipe_btn)
        cl.addWidget(danger)
        cl.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll)

        self.f10 = QShortcut(QKeySequence(Qt.Key.Key_F10), self)
        self.f10.activated.connect(self.save)
        self.ctrl_s = QShortcut(QKeySequence('Ctrl+S'), self)
        self.ctrl_s.activated.connect(self.save)

    def save(self):
        name = self.store.text().strip()
        pin = self.admin_pin.text().strip()
        if not name:
            QMessageBox.warning(self, 'Configuración', 'Ingresá el nombre de la heladería.')
            self.store.setFocus()
            return
        if not pin:
            QMessageBox.warning(self, 'Configuración', 'El PIN de administración no puede quedar vacío.')
            self.admin_pin.setFocus()
            return
        set_setting('store_name', name)
        set_setting('store_address', self.address.text().strip())
        set_setting('store_phone', self.phone.text().strip())
        set_setting('admin_pin', pin)
        set_setting('delivery_fee', str(int(self.delivery_fee.value())))
        set_setting('pickup_fee', '0.00')
        # Verificación inmediata contra la misma base.
        saved_name = get_setting('store_name', '')
        if saved_name != name:
            QMessageBox.critical(self, 'Configuración', 'No se pudo verificar el guardado. Intentá nuevamente.')
            return
        self.status.setText(f'✓ GUARDADO CORRECTAMENTE · Nombre actual: {saved_name}')
        self.status.setStyleSheet('background:#dcf7e8;color:#17613b;border-radius:10px;padding:10px;font-size:14px;font-weight:900;')
        QMessageBox.information(self, 'Configuración', f'Configuración guardada correctamente.\n\nNombre: {saved_name}')

    def clean_database(self):
        first = QMessageBox.warning(
            self, 'LIMPIAR BASE DE DATOS',
            'Esta acción elimina TODOS los datos operativos del negocio.\n\n'
            'Se conservarán usuarios/PIN, configuración y Mercado Pago.\n'
            'Se hará un backup automático antes de borrar.\n\n¿Querés continuar?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if first != QMessageBox.StandardButton.Yes:
            return
        typed, ok = QInputDialog.getText(self, 'Confirmación obligatoria', 'Para confirmar escribí exactamente: LIMPIAR')
        if not ok or typed.strip().upper() != 'LIMPIAR':
            QMessageBox.information(self, 'Cancelado', 'No se realizó ningún cambio.')
            return
        second = QMessageBox.question(
            self, 'Última confirmación',
            '¿Confirmás el borrado definitivo de clientes, productos, pedidos, ventas y demás datos operativos?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if second != QMessageBox.StandardButton.Yes:
            return
        try:
            result = reset_business_data_preserve_config()
            mp = result.get('mercadopago_preserved') or {}
            token_ok = bool(mp.get('mercadopago_access_token'))
            public_ok = bool(mp.get('mercadopago_public_key'))
            msg = (
                'Base operativa limpiada correctamente.\n\n'
                f'Backup: {result.get("backup_path")}\n\n'
                f'Mercado Pago Access Token: {"CONSERVADO" if token_ok else "sin valor previo"}\n'
                f'Mercado Pago Public Key: {"CONSERVADA" if public_ok else "sin valor previo"}\n\n'
                'Cerrá y volvé a abrir los módulos para verlos vacíos.'
            )
            self.status.setText('✓ BASE OPERATIVA LIMPIADA · Mercado Pago y configuración conservados')
            self.status.setStyleSheet('background:#dcf7e8;color:#17613b;border-radius:10px;padding:10px;font-size:14px;font-weight:900;')
            QMessageBox.information(self, 'Limpieza finalizada', msg)
        except Exception as exc:
            QMessageBox.critical(self, 'No se pudo limpiar la base', str(exc))

