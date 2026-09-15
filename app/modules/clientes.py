import sqlite3
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QComboBox, QSpinBox, QCheckBox, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QInputDialog,
    QSplitter, QScrollArea, QSizePolicy, QDialog
)

from app.database import db
from app.services.loyalty_service import normalize_dni, ensure_customer_card, regenerate_customer_card
from app.services.order_service import customer_order_access


ACCENT = '#7c3aed'
GREEN = '#16a34a'
BLUE = '#2563eb'
ORANGE = '#ea580c'
RED = '#dc2626'
MUTED = '#6b7280'
CARD = '#ffffff'
BORDER = '#e5e7eb'
SOFT = '#f8fafc'


def _money_int(value):
    try:
        return f"{int(value):,}".replace(',', '.')
    except Exception:
        return str(value or 0)


def _birth_to_display(value):
    raw = str(value or '').strip()
    if not raw:
        return ''
    for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(raw, fmt).strftime('%d/%m/%Y')
        except ValueError:
            continue
    return raw


def _birth_to_db(value):
    raw = str(value or '').strip()
    if not raw or not any(ch.isdigit() for ch in raw):
        return ''
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(raw, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    raise ValueError('Usá el formato DD/MM/AAAA.')


class ClientesPage(QWidget):
    """V24 · CRM de escritorio rediseñado como ficha completa, sin popup principal."""

    def __init__(self, back_callback):
        super().__init__()
        self.back_callback = back_callback
        self.current_id = None
        self._loading = False
        self.build_ui()
        self.refresh()

    # ---------- UI ----------
    def _section(self, title, subtitle=''):
        box = QFrame()
        box.setObjectName('crmSection')
        box.setStyleSheet(
            "QFrame#crmSection{background:white;border:1px solid #e5e7eb;border-radius:16px;}"
        )
        layout = QVBoxLayout(box)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        head = QLabel(title)
        head.setStyleSheet('font-size:18px;font-weight:900;color:#1f2937;')
        layout.addWidget(head)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setWordWrap(True)
            sub.setStyleSheet('color:#6b7280;font-size:12px;')
            layout.addWidget(sub)
        return box, layout

    def _field_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet('font-weight:800;color:#374151;font-size:12px;')
        return lbl

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(14)

        header = QHBoxLayout()
        back = QPushButton('← VOLVER')
        back.setMinimumHeight(44)
        back.setStyleSheet('background:#f3f4f6;color:#374151;padding:10px 18px;')
        back.clicked.connect(self.back_callback)
        title_wrap = QVBoxLayout()
        title = QLabel('👥 Clientes / CRM')
        title.setStyleSheet('font-size:30px;font-weight:950;color:#111827;')
        subtitle = QLabel('Buscá un cliente y trabajá sobre su ficha sin abrir ventanas pequeñas.')
        subtitle.setStyleSheet('color:#6b7280;font-size:13px;')
        title_wrap.addWidget(title)
        title_wrap.addWidget(subtitle)
        new_btn = QPushButton('＋ NUEVO CLIENTE')
        new_btn.setMinimumHeight(48)
        new_btn.setStyleSheet(f'background:{GREEN};color:white;padding:12px 22px;')
        new_btn.clicked.connect(self.new_customer)
        header.addWidget(back)
        header.addSpacing(14)
        header.addLayout(title_wrap)
        header.addStretch()
        header.addWidget(new_btn)
        root.addLayout(header)

        toolbar = QFrame()
        toolbar.setStyleSheet('background:white;border:1px solid #e5e7eb;border-radius:14px;')
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(14, 10, 14, 10)
        tl.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText('🔎 DNI, Nº de tarjeta o apellido / nombre...')
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(42)
        self.search.textChanged.connect(self.refresh)
        self.status_filter = QComboBox()
        self.status_filter.addItems(['TODOS LOS ESTADOS', 'ACTIVO', 'SUSPENDIDO', 'BLOQUEADO'])
        self.status_filter.setMinimumWidth(190)
        self.status_filter.currentTextChanged.connect(self.refresh)
        refresh_btn = QPushButton('⟳ ACTUALIZAR')
        refresh_btn.setStyleSheet('background:#eef2ff;color:#3730a3;')
        refresh_btn.clicked.connect(self.refresh)
        tl.addWidget(self.search, 1)
        tl.addWidget(self.status_filter)
        tl.addWidget(refresh_btn)
        root.addWidget(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        # Lista compacta.
        left = QFrame()
        left.setStyleSheet('background:white;border:1px solid #e5e7eb;border-radius:16px;')
        ll = QVBoxLayout(left)
        ll.setContentsMargins(14, 14, 14, 14)
        ll.setSpacing(10)
        list_title = QLabel('CLIENTES')
        list_title.setStyleSheet('font-size:13px;font-weight:900;color:#6b7280;letter-spacing:1px;')
        self.counter = QLabel('0 clientes')
        self.counter.setStyleSheet('color:#6b7280;')
        lh = QHBoxLayout(); lh.addWidget(list_title); lh.addStretch(); lh.addWidget(self.counter)
        ll.addLayout(lh)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Cliente', 'DNI', 'Tarjeta', 'Puntos', 'Estado'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(50)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.doubleClicked.connect(lambda *_: self.name.setFocus())
        ll.addWidget(self.table, 1)
        splitter.addWidget(left)

        # Ficha editable.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.editor = QWidget()
        self.editor.setStyleSheet('background:#f8fafc;')
        el = QVBoxLayout(self.editor)
        el.setContentsMargins(2, 0, 2, 8)
        el.setSpacing(12)

        top_card, top_l = self._section('Ficha del cliente')
        row = QHBoxLayout()
        identity = QVBoxLayout()
        self.editor_title = QLabel('Seleccioná un cliente')
        self.editor_title.setStyleSheet('font-size:24px;font-weight:950;color:#111827;')
        self.editor_hint = QLabel('También podés crear uno nuevo con “Nuevo cliente”.')
        self.editor_hint.setStyleSheet('color:#6b7280;')
        identity.addWidget(self.editor_title)
        identity.addWidget(self.editor_hint)
        self.status_badge = QLabel('SIN SELECCIÓN')
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setMinimumWidth(120)
        self.status_badge.setStyleSheet('background:#e5e7eb;color:#374151;border-radius:12px;padding:8px 12px;font-weight:900;')
        row.addLayout(identity, 1)
        row.addWidget(self.status_badge)
        top_l.addLayout(row)
        el.addWidget(top_card)

        personal, pl = self._section('Datos personales', 'La fecha de nacimiento se carga como DD/MM/AAAA.')
        grid = QGridLayout(); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(8)
        self.dni = QLineEdit(); self.dni.setPlaceholderText('Ej. 37201948')
        self.name = QLineEdit(); self.name.setPlaceholderText('Nombre y apellido')
        self.phone = QLineEdit(); self.phone.setPlaceholderText('Ej. 341 555-0000')
        self.birth = QLineEdit(); self.birth.setPlaceholderText('DD/MM/AAAA'); self.birth.setInputMask('00/00/0000;_')
        self.address = QLineEdit(); self.address.setPlaceholderText('Calle, número, localidad')
        fields = [
            (0, 0, 'DNI', self.dni), (0, 1, 'Nombre *', self.name),
            (2, 0, 'Teléfono', self.phone), (2, 1, 'Nacimiento', self.birth),
        ]
        for r, c, label, widget in fields:
            grid.addWidget(self._field_label(label), r, c)
            grid.addWidget(widget, r + 1, c)
        grid.addWidget(self._field_label('Dirección'), 4, 0, 1, 2)
        grid.addWidget(self.address, 5, 0, 1, 2)
        pl.addLayout(grid)
        el.addWidget(personal)

        loyalty, loy = self._section('Fidelidad', 'La tarjeta puede regenerarse sin perder puntos ni historial.')
        lg = QGridLayout(); lg.setHorizontalSpacing(14); lg.setVerticalSpacing(8)
        self.card_number = QLineEdit(); self.card_number.setReadOnly(True); self.card_number.setPlaceholderText('Se genera automáticamente')
        self.points = QSpinBox(); self.points.setMaximum(999999)
        self.purchases = QLabel('0 compras')
        self.purchases.setStyleSheet('font-size:16px;font-weight:900;color:#111827;padding:9px;background:#f8fafc;border-radius:10px;')
        self.portal_status = QLabel('Portal: sin cuenta')
        self.portal_status.setStyleSheet('font-weight:800;color:#6b7280;')
        lg.addWidget(self._field_label('Tarjeta de 8 dígitos'), 0, 0)
        lg.addWidget(self._field_label('Puntos'), 0, 1)
        lg.addWidget(self.card_number, 1, 0)
        lg.addWidget(self.points, 1, 1)
        lg.addWidget(self.purchases, 2, 0)
        lg.addWidget(self.portal_status, 2, 1)
        loy.addLayout(lg)
        card_actions = QHBoxLayout()
        self.regenerate_btn = QPushButton('💳 REGENERAR TARJETA')
        self.regenerate_btn.setStyleSheet(f'background:{ORANGE};color:white;')
        self.regenerate_btn.clicked.connect(self.regenerate_card)
        self.movements_btn = QPushButton('📜 VER MOVIMIENTOS / HISTORIAL')
        self.movements_btn.setStyleSheet(f'background:{BLUE};color:white;')
        self.movements_btn.clicked.connect(self.show_movements)
        card_actions.addWidget(self.regenerate_btn)
        card_actions.addWidget(self.movements_btn)
        card_actions.addStretch()
        loy.addLayout(card_actions)
        self.card_history = QLabel('')
        self.card_history.setWordWrap(True)
        self.card_history.setStyleSheet('color:#6b7280;font-size:12px;')
        loy.addWidget(self.card_history)
        el.addWidget(loyalty)

        status_box, sl = self._section('Estado y pedidos Web')
        sg = QGridLayout(); sg.setHorizontalSpacing(14); sg.setVerticalSpacing(8)
        self.customer_status = QComboBox(); self.customer_status.addItems(['ACTIVO', 'SUSPENDIDO', 'BLOQUEADO'])
        self.block_reason = QLineEdit(); self.block_reason.setPlaceholderText('Motivo de suspensión o bloqueo')
        self.active = QCheckBox('Cliente habilitado en el sistema'); self.active.setChecked(True)
        self.temp_block = QLabel('Sin bloqueo temporal')
        self.temp_block.setWordWrap(True)
        self.temp_block.setStyleSheet('background:#f8fafc;padding:10px;border-radius:10px;color:#374151;')
        self.unblock_btn = QPushButton('🔓 LEVANTAR BLOQUEO TEMPORAL')
        self.unblock_btn.setStyleSheet('background:#fbbf24;color:#3f2b00;')
        self.unblock_btn.clicked.connect(self.clear_temp_block)
        sg.addWidget(self._field_label('Estado para pedidos'), 0, 0)
        sg.addWidget(self._field_label('Motivo'), 0, 1)
        sg.addWidget(self.customer_status, 1, 0)
        sg.addWidget(self.block_reason, 1, 1)
        sg.addWidget(self.active, 2, 0)
        sg.addWidget(self.temp_block, 3, 0, 1, 2)
        sg.addWidget(self.unblock_btn, 4, 0, 1, 2)
        sl.addLayout(sg)
        el.addWidget(status_box)

        notes_box, nl = self._section('Observaciones')
        self.notes = QTextEdit(); self.notes.setPlaceholderText('Notas internas del cliente...'); self.notes.setMinimumHeight(90)
        nl.addWidget(self.notes)
        el.addWidget(notes_box)

        action = QFrame(); action.setStyleSheet('background:white;border:1px solid #e5e7eb;border-radius:16px;')
        al = QHBoxLayout(action); al.setContentsMargins(14, 12, 14, 12)
        self.cancel_btn = QPushButton('LIMPIAR / CANCELAR')
        self.cancel_btn.setStyleSheet('background:#f3f4f6;color:#374151;')
        self.cancel_btn.clicked.connect(self.cancel_edit)
        self.save_btn = QPushButton('💾 GUARDAR CLIENTE')
        self.save_btn.setMinimumHeight(48)
        self.save_btn.setStyleSheet(f'background:{GREEN};color:white;padding:12px 22px;')
        self.save_btn.clicked.connect(self.save_customer)
        al.addWidget(self.cancel_btn)
        al.addStretch()
        al.addWidget(self.save_btn)
        el.addWidget(action)
        el.addStretch()

        scroll.setWidget(self.editor)
        splitter.addWidget(scroll)
        splitter.setSizes([560, 720])

        self._set_editor_enabled(False)

    def _set_editor_enabled(self, enabled):
        for w in (self.dni, self.name, self.phone, self.birth, self.address, self.points,
                  self.customer_status, self.block_reason, self.active, self.notes,
                  self.save_btn, self.cancel_btn):
            w.setEnabled(enabled)
        has_saved = bool(enabled and self.current_id)
        self.regenerate_btn.setEnabled(has_saved)
        self.movements_btn.setEnabled(has_saved)
        self.unblock_btn.setEnabled(has_saved)

    def _set_badge(self, status):
        status = str(status or 'ACTIVO').upper()
        colors = {
            'ACTIVO': ('#dcfce7', '#166534'),
            'SUSPENDIDO': ('#fef3c7', '#92400e'),
            'BLOQUEADO': ('#fee2e2', '#991b1b'),
        }
        bg, fg = colors.get(status, ('#e5e7eb', '#374151'))
        self.status_badge.setText(status)
        self.status_badge.setStyleSheet(f'background:{bg};color:{fg};border-radius:12px;padding:8px 12px;font-weight:900;')

    # ---------- Listado ----------
    def refresh(self, *_):
        text = self.search.text().strip().lower() if hasattr(self, 'search') else ''
        status_filter = self.status_filter.currentText() if hasattr(self, 'status_filter') else 'TODOS LOS ESTADOS'
        # V25: el CRM no lista toda la base al abrir. Primero se busca al cliente.
        if not text:
            self._loading = True
            self.table.setRowCount(0)
            self.table.clearSelection()
            self._loading = False
            self.counter.setText('Ingresá DNI, tarjeta o apellido')
            if self.current_id is None:
                self.clear_editor(False)
            return
        with db() as c:
            rows = c.execute('''
                SELECT c.*, COUNT(s.id) purchases,
                       CASE WHEN pa.id IS NULL THEN 0 ELSE 1 END portal_account
                FROM customers c
                LEFT JOIN sales s ON s.customer_id=c.id
                LEFT JOIN portal_accounts pa ON pa.customer_id=c.id
                GROUP BY c.id
                ORDER BY c.name COLLATE NOCASE
            ''').fetchall()
        filtered = []
        for r in rows:
            haystack = ' '.join(str(r[k] or '') for k in ('name', 'dni', 'phone', 'loyalty_card_number')).lower()
            if text and text not in haystack:
                continue
            st = str(r['customer_status'] or 'ACTIVO').upper()
            if status_filter != 'TODOS LOS ESTADOS' and st != status_filter:
                continue
            filtered.append(r)

        selected = self.current_id
        self._loading = True
        self.table.setRowCount(len(filtered))
        select_row = -1
        for i, r in enumerate(filtered):
            name_item = QTableWidgetItem(str(r['name'] or ''))
            name_item.setData(Qt.ItemDataRole.UserRole, int(r['id']))
            values = [name_item, QTableWidgetItem(str(r['dni'] or '')), QTableWidgetItem(str(r['loyalty_card_number'] or '—')),
                      QTableWidgetItem(_money_int(r['points'])), QTableWidgetItem(str(r['customer_status'] or 'ACTIVO'))]
            for col, item in enumerate(values):
                self.table.setItem(i, col, item)
                if col in (3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if int(r['id']) == selected:
                select_row = i
        self.counter.setText(f'{len(filtered)} cliente' + ('' if len(filtered) == 1 else 's'))
        self._loading = False
        if select_row >= 0:
            self.table.selectRow(select_row)
        elif len(filtered) == 1 and self.current_id is None:
            self.table.selectRow(0)
        elif not filtered:
            self.current_id = None
            self.clear_editor()

    def _selection_changed(self):
        if self._loading:
            return
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if not item:
            return
        cid = item.data(Qt.ItemDataRole.UserRole)
        if cid:
            self.load_customer(int(cid))

    # ---------- Editor ----------
    def new_customer(self):
        self.table.clearSelection()
        self.current_id = None
        self.clear_editor(new_mode=True)
        self.name.setFocus()

    def clear_editor(self, new_mode=False):
        self._loading = True
        self.dni.clear(); self.name.clear(); self.phone.clear(); self.address.clear(); self.birth.clear()
        self.points.setValue(0); self.notes.clear(); self.card_number.clear(); self.active.setChecked(True)
        self.customer_status.setCurrentText('ACTIVO'); self.block_reason.clear()
        self.purchases.setText('0 compras'); self.portal_status.setText('Portal: sin cuenta')
        self.card_history.clear(); self.temp_block.setText('Sin bloqueo temporal')
        self.editor_title.setText('Nuevo cliente' if new_mode else 'Seleccioná un cliente')
        self.editor_hint.setText('Completá los datos y guardá.' if new_mode else 'Elegí un cliente de la lista para abrir su ficha completa.')
        self._set_badge('ACTIVO' if new_mode else 'SIN SELECCIÓN')
        self._set_editor_enabled(new_mode)
        self._loading = False

    def cancel_edit(self):
        if self.current_id:
            self.load_customer(self.current_id)
        else:
            self.clear_editor(False)

    def load_customer(self, cid):
        with db() as c:
            r = c.execute('''SELECT c.*, COUNT(s.id) purchases,
                                   pa.email portal_email, pa.active portal_active, pa.last_login_at
                            FROM customers c
                            LEFT JOIN sales s ON s.customer_id=c.id
                            LEFT JOIN portal_accounts pa ON pa.customer_id=c.id
                            WHERE c.id=? GROUP BY c.id''', (cid,)).fetchone()
            hist = c.execute('''SELECT old_card_number,new_card_number,reason,created_at
                                FROM loyalty_card_history WHERE customer_id=? ORDER BY id DESC LIMIT 3''', (cid,)).fetchall()
        if not r:
            return
        self.current_id = cid
        self._loading = True
        self.dni.setText(str(r['dni'] or ''))
        self.name.setText(str(r['name'] or ''))
        self.phone.setText(str(r['phone'] or ''))
        self.address.setText(str(r['address'] or ''))
        self.birth.setText(_birth_to_display(r['birth_date']))
        self.points.setValue(int(r['points'] or 0))
        self.notes.setPlainText(str(r['notes'] or ''))
        self.active.setChecked(bool(r['active']))
        st = str(r['customer_status'] or 'ACTIVO').upper()
        self.customer_status.setCurrentText(st if st in ('ACTIVO', 'SUSPENDIDO', 'BLOQUEADO') else 'ACTIVO')
        self.block_reason.setText(str(r['order_block_reason'] or ''))
        self.card_number.setText(str(r['loyalty_card_number'] or ''))
        purchases = int(r['purchases'] or 0)
        self.purchases.setText(f'{purchases} compra' + ('' if purchases == 1 else 's'))
        if r['portal_email']:
            active = 'activo' if bool(r['portal_active']) else 'deshabilitado'
            self.portal_status.setText(f'Portal: {active} · {r["portal_email"]}')
        else:
            self.portal_status.setText('Portal: sin cuenta')
        if hist:
            chunks = []
            for h in hist:
                when = str(h['created_at'] or '').replace('T', ' ')
                chunks.append(f"{h['old_card_number'] or '—'} → {h['new_card_number']} · {h['reason'] or 'Reemplazo'} · {when}")
            self.card_history.setText('Últimos reemplazos: ' + ' | '.join(chunks))
        else:
            self.card_history.setText('Sin reemplazos de tarjeta registrados.')
        access = customer_order_access(cid, clear_expired=False)
        if access.get('kind') == 'BLOQUEO_TEMPORAL':
            self.temp_block.setText('⏳ ' + str(access.get('message') or 'Bloqueo temporal activo'))
            self.unblock_btn.setEnabled(True)
        else:
            self.temp_block.setText('✅ Sin bloqueo temporal de pedidos')
        self.editor_title.setText(str(r['name'] or 'Cliente'))
        self.editor_hint.setText(f"DNI {r['dni'] or 'sin DNI'} · Tarjeta {r['loyalty_card_number'] or 'sin tarjeta'}")
        self._set_badge(st)
        self._set_editor_enabled(True)
        self._loading = False

    def show_movements(self):
        if not self.current_id:
            return
        with db() as c:
            customer = c.execute('SELECT name,dni,loyalty_card_number,points FROM customers WHERE id=?', (self.current_id,)).fetchone()
            movements = c.execute('SELECT created_at,movement_type,points,balance_after,description,sale_id,order_id FROM loyalty_movements WHERE customer_id=? ORDER BY id DESC LIMIT 300', (self.current_id,)).fetchall()
            cards = c.execute('SELECT created_at,old_card_number,new_card_number,reason,actor FROM loyalty_card_history WHERE customer_id=? ORDER BY id DESC LIMIT 100', (self.current_id,)).fetchall()
        rows = []
        for m in movements:
            ref = ''
            if m['sale_id']:
                ref += f"Venta #{m['sale_id']} "
            if 'order_id' in m.keys() and m['order_id']:
                ref += f"Pedido #{m['order_id']}"
            detail = str(m['description'] or '')
            if ref.strip():
                detail = (detail + ' · ' + ref.strip()).strip(' ·')
            rows.append((str(m['created_at'] or ''), str(m['movement_type'] or 'PUNTOS'), str(int(m['points'] or 0)), str(int(m['balance_after'] or 0)), detail))
        for h in cards:
            detail = f"{h['old_card_number'] or '—'} → {h['new_card_number']} · {h['reason'] or 'Reemplazo'}"
            if h['actor']:
                detail += f" · {h['actor']}"
            rows.append((str(h['created_at'] or ''), 'REGENERACIÓN TARJETA', '—', '—', detail))
        rows.sort(key=lambda x: x[0], reverse=True)

        dlg = QDialog(self)
        dlg.setWindowTitle('Movimientos del cliente')
        dlg.resize(980, 650)
        lay = QVBoxLayout(dlg)
        title = QLabel(f"📜 {customer['name'] if customer else 'Cliente'}")
        title.setStyleSheet('font-size:24px;font-weight:950;color:#111827;')
        if customer:
            sub_text = f"DNI {customer['dni'] or '—'} · Tarjeta {customer['loyalty_card_number'] or '—'} · Saldo actual {int(customer['points'] or 0)} puntos"
        else:
            sub_text = ''
        sub = QLabel(sub_text)
        sub.setStyleSheet('color:#6b7280;font-weight:700;')
        table = QTableWidget(0,5)
        table.setHorizontalHeaderLabels(['Fecha','Movimiento','Puntos','Saldo','Detalle'])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        hh=table.horizontalHeader()
        hh.setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3,QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4,QHeaderView.ResizeMode.Stretch)
        table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for col,val in enumerate(row):
                table.setItem(r,col,QTableWidgetItem(val))
        close=QPushButton('CERRAR · ESC')
        close.setMinimumHeight(46)
        close.clicked.connect(dlg.accept)
        lay.addWidget(title); lay.addWidget(sub); lay.addWidget(table,1); lay.addWidget(close)
        dlg.exec()

    def save_customer(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, 'Cliente', 'El nombre es obligatorio.')
            self.name.setFocus()
            return
        dni = normalize_dni(self.dni.text()) or None
        try:
            birth = _birth_to_db(self.birth.text().replace('_', ''))
        except ValueError as exc:
            QMessageBox.warning(self, 'Fecha de nacimiento', str(exc))
            self.birth.setFocus()
            return
        try:
            with db() as c:
                if dni:
                    dup = c.execute('SELECT id,name FROM customers WHERE dni=? AND id<>COALESCE(?,0) LIMIT 1', (dni, self.current_id)).fetchone()
                    if dup:
                        QMessageBox.warning(self, 'DNI duplicado', f'El DNI {dni} ya está registrado para {dup["name"]}.')
                        return
                values = (
                    dni, self.name.text().strip(), self.phone.text().strip(), self.address.text().strip(),
                    birth, self.points.value(), self.notes.toPlainText().strip(), int(self.active.isChecked()),
                    self.customer_status.currentText(), self.block_reason.text().strip() or None
                )
                if self.current_id:
                    c.execute('''UPDATE customers SET dni=?,name=?,phone=?,address=?,birth_date=?,points=?,notes=?,active=?,customer_status=?,order_block_reason=? WHERE id=?''', values + (self.current_id,))
                    cid = self.current_id
                else:
                    cur = c.execute('''INSERT INTO customers(dni,name,phone,address,birth_date,points,notes,active,customer_status,order_block_reason)
                                       VALUES (?,?,?,?,?,?,?,?,?,?)''', values)
                    cid = int(cur.lastrowid)
                if dni:
                    ensure_customer_card(cid, c)
            self.current_id = cid
            self.refresh()
            self.load_customer(cid)
            QMessageBox.information(self, 'Cliente', 'Cliente guardado correctamente.')
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, 'DNI duplicado', 'Ese DNI ya existe y no puede registrarse dos veces.')
        except Exception as exc:
            QMessageBox.critical(self, 'Cliente', f'No se pudo guardar el cliente.\n\n{exc}')

    def regenerate_card(self):
        cid = self.current_id
        if not cid:
            return
        reasons = ['EXTRAVÍO / PÉRDIDA', 'CLIENTE NO RECUERDA TARJETA', 'TARJETA DETERIORADA', 'REEMPLAZO ADMINISTRATIVO']
        reason, ok = QInputDialog.getItem(self, 'Regenerar tarjeta de fidelidad', 'Motivo:', reasons, 0, False)
        if not ok:
            return
        if QMessageBox.question(
            self, 'Confirmar reemplazo',
            'Se invalidará el número de tarjeta actual y se generará uno nuevo.\n\nLos puntos y el historial se conservan.\n\n¿Continuar?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            result = regenerate_customer_card(cid, reason, actor='SISTEMA CENTRAL')
            self.refresh(); self.load_customer(cid)
            QMessageBox.information(self, 'Tarjeta regenerada', f'Tarjeta anterior: {result["old_card"] or "—"}\nNueva tarjeta: {result["new_card"]}\nPuntos conservados: {result["points"]}')
        except Exception as exc:
            QMessageBox.critical(self, 'Tarjeta de fidelidad', str(exc))

    def clear_temp_block(self):
        cid = self.current_id
        if not cid:
            return
        access = customer_order_access(cid, clear_expired=False)
        if access.get('kind') != 'BLOQUEO_TEMPORAL':
            QMessageBox.information(self, 'Bloqueo de pedidos', 'El cliente no tiene un bloqueo temporal activo.')
            return
        if QMessageBox.question(
            self, 'Levantar bloqueo',
            f'¿Habilitar nuevamente los pedidos para este cliente?\n\n{access.get("message", "")}',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        with db() as c:
            c.execute("UPDATE customers SET order_blocked_until=NULL,order_block_reason=CASE WHEN customer_status='ACTIVO' THEN NULL ELSE order_block_reason END WHERE id=?", (cid,))
        self.load_customer(cid)
        QMessageBox.information(self, 'Bloqueo de pedidos', 'Bloqueo temporal eliminado.')
