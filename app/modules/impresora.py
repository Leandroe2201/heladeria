from PyQt6.QtWidgets import *
from PyQt6.QtPrintSupport import QPrinterInfo
from app.database import db
from app.settings_service import get_setting, set_setting
from app.services.ticket_service import print_sale_ticket, print_order_ticket, print_loyalty_ticket, print_lines


class ToggleSettingButton(QPushButton):
    """Interruptor grande y clickeable; reemplaza checkboxes pequeños."""
    def __init__(self, label, checked=False, parent=None):
        super().__init__(parent)
        self.label = label
        self.setCheckable(True)
        self.setMinimumHeight(58)
        self.setChecked(bool(checked))
        self.toggled.connect(self.refresh_visual)
        self.refresh_visual(self.isChecked())

    def refresh_visual(self, checked):
        state = 'ACTIVADO' if checked else 'DESACTIVADO'
        icon = '✓' if checked else '○'
        color = '#25b86b' if checked else '#ece5e8'
        text_color = 'white' if checked else '#604f57'
        self.setText(f'{icon}  {self.label}\n{state}')
        self.setStyleSheet(f'''QPushButton{{background:{color};color:{text_color};border:2px solid {'#159552' if checked else '#d9cbd1'};
                              border-radius:13px;font-size:14px;font-weight:900;text-align:left;padding:8px 14px;}}
                              QPushButton:hover{{border:3px solid #4d2034;}}''')


class ImpresoraPage(QWidget):
    def __init__(self, back_callback):
        super().__init__()
        self.back_callback = back_callback
        self.build_ui()
        self.refresh_lists()

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 28)
        root.setSpacing(12)
        h = QHBoxLayout()
        b = QPushButton('← Volver a Opciones')
        b.setStyleSheet('background:#eee5ea;color:#4a3740;')
        b.clicked.connect(self.back_callback)
        t = QLabel('🖨 Tickets / Impresora térmica')
        t.setStyleSheet('font-size:28px;font-weight:900;')
        h.addWidget(b)
        h.addSpacing(16)
        h.addWidget(t)
        h.addStretch()
        root.addLayout(h)

        tabs = QTabWidget()
        root.addWidget(tabs)
        cfg = QWidget()
        cl = QVBoxLayout(cfg)
        formbox = QFrame()
        formbox.setStyleSheet('background:white;border:1px solid #eadfe4;border-radius:14px;')
        form = QFormLayout(formbox)
        form.setVerticalSpacing(12)
        self.store = QLineEdit(get_setting('store_name', 'Dulces Momentos'))
        self.address = QLineEdit(get_setting('store_address', ''))
        self.phone = QLineEdit(get_setting('store_phone', ''))
        self.footer = QLineEdit(get_setting('store_footer', '¡Gracias por su compra!'))
        self.width = QComboBox()
        self.width.addItems(['58', '80', '85'])
        cur = get_setting('ticket_width_mm', '58')
        self.width.setCurrentText(cur if cur in ['58', '80', '85'] else '58')
        self.printer = QComboBox()
        self.printer.addItem('Impresora predeterminada de Windows', '')
        configured = get_setting('printer_name', '')
        for info in QPrinterInfo.availablePrinters():
            self.printer.addItem(info.printerName(), info.printerName())
        idx = self.printer.findData(configured)
        if idx >= 0:
            self.printer.setCurrentIndex(idx)
        form.addRow('Nombre del negocio', self.store)
        form.addRow('Dirección', self.address)
        form.addRow('Teléfono', self.phone)
        form.addRow('Pie del ticket', self.footer)
        form.addRow('Ancho del papel', self.width)
        form.addRow('Impresora', self.printer)
        self.backend = QComboBox()
        self.backend.addItem('RAW ESC/POS · recomendado para térmica 58 mm', 'RAW_ESC_POS')
        self.backend.addItem('Windows / gráfico · alternativa', 'WINDOWS_GDI')
        self.backend.addItem('Automático · intenta RAW y luego Windows', 'AUTO')
        backend = get_setting('print_backend', 'RAW_ESC_POS')
        idxb = self.backend.findData(backend)
        self.backend.setCurrentIndex(idxb if idxb >= 0 else 0)
        self.cut = QCheckBox('Usar corte automático (solo si la impresora tiene cutter)')
        self.cut.setChecked(get_setting('thermal_auto_cut', '0') == '1')
        self.feed = QSpinBox(); self.feed.setRange(2, 10); self.feed.setValue(int(get_setting('thermal_feed_lines','4') or 4))
        form.addRow('Modo de impresión', self.backend)
        form.addRow('Avance final (líneas)', self.feed)
        form.addRow('', self.cut)
        cl.addWidget(formbox)

        toggles = QFrame()
        toggles.setStyleSheet('background:#fff;border:1px solid #eadfe4;border-radius:14px;')
        tl = QVBoxLayout(toggles)
        tl.setContentsMargins(14, 12, 14, 12)
        tl.addWidget(QLabel('IMPRESIÓN AUTOMÁTICA · Tocá el botón completo para activar/desactivar'))
        self.auto_sale = ToggleSettingButton('Imprimir automáticamente después de cobrar una venta', get_setting('auto_print_sale', '0') == '1')
        self.auto_order = ToggleSettingButton('Imprimir automáticamente al guardar un pedido', get_setting('auto_print_order', '0') == '1')
        self.auto_loyalty = ToggleSettingButton('Si la venta suma/canjea puntos, imprimir comprobante de fidelidad por separado', get_setting('auto_print_loyalty_receipt', '1') == '1')
        self.auto_sale.toggled.connect(lambda checked: set_setting('auto_print_sale', '1' if checked else '0'))
        self.auto_order.toggled.connect(lambda checked: set_setting('auto_print_order', '1' if checked else '0'))
        self.auto_loyalty.toggled.connect(lambda checked: set_setting('auto_print_loyalty_receipt', '1' if checked else '0'))
        tl.addWidget(self.auto_sale)
        tl.addWidget(self.auto_order)
        tl.addWidget(self.auto_loyalty)
        cl.addWidget(toggles)

        note = QLabel('Para térmicas de 58 mm usá primero RAW ESC/POS. Este modo evita el problema típico de que la impresora haga ruido, avance/corte papel y el ticket salga vacío. Dejá Corte automático desactivado si tu equipo no tiene cutter.')
        note.setWordWrap(True)
        note.setStyleSheet('color:#725f68;')
        cl.addWidget(note)

        row = QHBoxLayout()
        save = QPushButton('💾 GUARDAR DATOS DEL TICKET')
        save.setMinimumHeight(50)
        save.setStyleSheet('background:#34b96f;color:white;')
        save.clicked.connect(self.save_config)
        test = QPushButton('🧾 IMPRIMIR TICKET DE PRUEBA')
        test.setMinimumHeight(50)
        test.setStyleSheet('background:#f28b32;color:white;')
        test.clicked.connect(self.print_test)
        preview = QPushButton('👁 VISTA PREVIA ÚLTIMA VENTA')
        preview.setMinimumHeight(50)
        preview.setStyleSheet('background:#3e91e5;color:white;')
        preview.clicked.connect(self.preview_latest_sale)
        row.addWidget(save)
        row.addWidget(test)
        row.addWidget(preview)
        row.addStretch()
        cl.addLayout(row)
        cl.addStretch()
        tabs.addTab(cfg, 'Configuración')

        sales = QWidget()
        sl = QVBoxLayout(sales)
        bar = QHBoxLayout()
        ps = QPushButton('🖨 IMPRIMIR VENTA')
        ps.setStyleSheet('background:#33b96f;color:white;')
        ps.clicked.connect(lambda: self.print_selected_sale(False))
        vs = QPushButton('👁 VISTA PREVIA')
        vs.setStyleSheet('background:#3e91e5;color:white;')
        vs.clicked.connect(lambda: self.print_selected_sale(True))
        lp = QPushButton('⭐ IMPRIMIR COMPROBANTE DE PUNTOS')
        lp.setStyleSheet('background:#8059c8;color:white;')
        lp.clicked.connect(self.print_selected_loyalty)
        ref = QPushButton('⟳ ACTUALIZAR')
        ref.clicked.connect(self.refresh_lists)
        bar.addWidget(ps)
        bar.addWidget(vs)
        bar.addWidget(lp)
        bar.addWidget(ref)
        bar.addStretch()
        sl.addLayout(bar)
        self.sales = QTableWidget(0, 5)
        self.sales.setHorizontalHeaderLabels(['Venta', 'Fecha', 'Total', 'Pago', 'Estado'])
        self.sales.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.sales.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        sl.addWidget(self.sales)
        tabs.addTab(sales, 'Tickets de venta')

        orders = QWidget()
        ol = QVBoxLayout(orders)
        obar = QHBoxLayout()
        po = QPushButton('🖨 IMPRIMIR PEDIDO')
        po.setStyleSheet('background:#e55b88;color:white;')
        po.clicked.connect(lambda: self.print_selected_order(False))
        vo = QPushButton('👁 VISTA PREVIA')
        vo.setStyleSheet('background:#8b69d0;color:white;')
        vo.clicked.connect(lambda: self.print_selected_order(True))
        obar.addWidget(po)
        obar.addWidget(vo)
        obar.addStretch()
        ol.addLayout(obar)
        self.orders = QTableWidget(0, 6)
        self.orders.setHorizontalHeaderLabels(['Pedido', 'Fecha', 'Tipo', 'Estado', 'Total', 'Teléfono'])
        self.orders.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.orders.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        ol.addWidget(self.orders)
        tabs.addTab(orders, 'Tickets de pedidos')

    def save_config(self):
        set_setting('store_name', self.store.text().strip() or 'Dulces Momentos')
        set_setting('store_address', self.address.text().strip())
        set_setting('store_phone', self.phone.text().strip())
        set_setting('store_footer', self.footer.text().strip())
        set_setting('ticket_width_mm', self.width.currentText())
        set_setting('printer_name', self.printer.currentData() or '')
        set_setting('print_backend', self.backend.currentData() or 'RAW_ESC_POS')
        set_setting('thermal_auto_cut', '1' if self.cut.isChecked() else '0')
        set_setting('thermal_feed_lines', str(self.feed.value()))
        set_setting('auto_print_sale', '1' if self.auto_sale.isChecked() else '0')
        set_setting('auto_print_order', '1' if self.auto_order.isChecked() else '0')
        set_setting('auto_print_loyalty_receipt', '1' if self.auto_loyalty.isChecked() else '0')
        QMessageBox.information(self, 'Impresora', 'Configuración guardada.')

    def print_test(self):
        self.save_config()
        lines = [
            {'text': get_setting('store_name', 'Dulces Momentos'), 'align': 'center', 'bold': True, 'scale': 1.35},
            {'text': '--------------------------------'},
            {'text': 'TICKET DE PRUEBA', 'align': 'center', 'bold': True, 'scale': 1.2},
            {'text': 'Impresora configurada correctamente'},
            {'text': '1x Producto prueba       $ 1.000', 'bold': True},
            {'text': '--------------------------------'},
            {'text': 'TOTAL                    $ 1.000', 'bold': True, 'scale': 1.2},
            {'text': 'Si leés esto, la impresión funciona.', 'align': 'center'},
            {'text': ''}, {'text': ''}
        ]
        try:
            print_lines(lines, int(self.width.currentText()), self.printer.currentData() or '', preview=False, parent=self, backend=self.backend.currentData())
        except Exception as e:
            QMessageBox.critical(self, 'Ticket de prueba', f'No se pudo imprimir.\n\n{e}')

    def refresh_lists(self):
        with db() as conn:
            sales = conn.execute('SELECT id,created_at,total,payment_method,status FROM sales ORDER BY id DESC LIMIT 200').fetchall()
            orders = conn.execute('SELECT id,created_at,order_type,status,total,phone FROM orders ORDER BY id DESC LIMIT 200').fetchall()
        self.sales.setRowCount(len(sales))
        for i, r in enumerate(sales):
            vals = [r['id'], r['created_at'], f"$ {r['total']:,.0f}", r['payment_method'], r['status']]
            for c, v in enumerate(vals):
                self.sales.setItem(i, c, QTableWidgetItem(str(v)))
        self.sales.resizeColumnsToContents()
        self.sales.horizontalHeader().setStretchLastSection(True)
        self.orders.setRowCount(len(orders))
        for i, r in enumerate(orders):
            vals = [r['id'], r['created_at'], r['order_type'], r['status'], f"$ {r['total']:,.0f}", r['phone'] or '']
            for c, v in enumerate(vals):
                self.orders.setItem(i, c, QTableWidgetItem(str(v)))
        self.orders.resizeColumnsToContents()
        self.orders.horizontalHeader().setStretchLastSection(True)

    def selected_id(self, table):
        r = table.currentRow()
        if r < 0:
            QMessageBox.information(self, 'Imprimir', 'Seleccioná un registro.')
            return None
        return int(table.item(r, 0).text())

    def _do(self, fn, record_id, preview):
        try:
            fn(record_id, preview=preview, parent=self)
        except Exception as e:
            QMessageBox.critical(self, 'Impresión', f'No se pudo imprimir.\n\n{e}')

    def print_selected_sale(self, preview):
        sid = self.selected_id(self.sales)
        if sid:
            self._do(print_sale_ticket, sid, preview)

    def print_selected_loyalty(self):
        sid = self.selected_id(self.sales)
        if sid:
            self._do(print_loyalty_ticket, sid, False)

    def print_selected_order(self, preview):
        oid = self.selected_id(self.orders)
        if oid:
            self._do(print_order_ticket, oid, preview)

    def preview_latest_sale(self):
        with db() as conn:
            r = conn.execute('SELECT id FROM sales ORDER BY id DESC LIMIT 1').fetchone()
        if not r:
            QMessageBox.information(self, 'Ticket', 'Todavía no hay ventas.')
            return
        self._do(print_sale_ticket, r['id'], True)
