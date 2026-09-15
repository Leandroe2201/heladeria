from datetime import datetime, timedelta
import io
from PyQt6.QtCore import Qt, QTimer, QUrl, QDate
from PyQt6.QtGui import QDesktopServices, QColor, QPixmap
from PyQt6.QtWidgets import *
from app.database import db
from app.services.offer_service import price_with_offer, apply_cart_offers
from app.services.ticket_service import print_order_ticket
from app.settings_service import get_setting
from app.config import DATA_DIR
from app.services.loyalty_service import create_or_update_customer
from app.modules.ventas import FlavorDialog
from app.services.mercadopago_service import attach_qr_to_order, sync_local_order, configuration_status as mp_configuration_status


class OrderForm(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.items=[]; self.order_id=None
        self.setWindowTitle('Nuevo pedido'); self.resize(760,680)
        root=QVBoxLayout(self)
        form=QFormLayout(); self.order_type=QComboBox(); self.order_type.addItems(['MOSTRADOR - RETIRA LUEGO','RETIRO EN LOCAL','DELIVERY','WHATSAPP','TELEFÓNICO'])
        self.dni=QLineEdit(); self.dni.setPlaceholderText('Opcional - vincula fidelidad'); self.customer=QLineEdit(); self.phone=QLineEdit(); self.address=QLineEdit(); self.payment=QComboBox(); self.payment.addItems(['EFECTIVO','DÉBITO','CRÉDITO','QR / TRANSFERENCIA','A DEFINIR']); self.notes=QLineEdit()
        for label,w in [('Tipo',self.order_type),('DNI cliente',self.dni),('Cliente',self.customer),('Teléfono',self.phone),('Dirección',self.address),('Forma de pago',self.payment),('Observaciones',self.notes)]:form.addRow(label,w)
        root.addLayout(form)
        row=QHBoxLayout(); self.product=QComboBox(); self.qty=QSpinBox(); self.qty.setRange(1,20); self.qty.setValue(1); add=QPushButton('＋ AGREGAR PRODUCTO'); add.setStyleSheet('background:#36c978;color:white;'); add.clicked.connect(self.add_item)
        with db() as conn:
            for r in conn.execute('SELECT id,name,price,max_flavors FROM products WHERE active=1 ORDER BY sort_order,name'): self.product.addItem(f"{r['name']} · $ {r['price']:,.0f}",dict(r))
        row.addWidget(self.product,1); row.addWidget(QLabel('Cant.')); row.addWidget(self.qty); row.addWidget(add); root.addLayout(row)
        self.table=QTableWidget(0,5); self.table.setHorizontalHeaderLabels(['Producto','Cant.','Sabores','Unitario','Total']); self.table.horizontalHeader().setStretchLastSection(True); root.addWidget(self.table)
        btns=QHBoxLayout(); remove=QPushButton('Quitar seleccionado'); remove.setStyleSheet('background:#f6d6e0;color:#963d5e;'); remove.clicked.connect(self.remove_item); btns.addWidget(remove); btns.addStretch(); self.total=QLabel('TOTAL $ 0'); self.total.setStyleSheet('font-size:24px;font-weight:900;'); btns.addWidget(self.total); root.addLayout(btns)
        save=QPushButton('💾 GUARDAR PEDIDO'); save.setMinimumHeight(52); save.setStyleSheet('background:#3f9df7;color:white;font-size:18px;'); save.clicked.connect(self.save); root.addWidget(save)

    def add_item(self):
        p=self.product.currentData(); qty=self.qty.value(); flavors=[]
        if p and int(p.get('max_flavors',0))>0:
            d=FlavorDialog(p['name'],int(p['max_flavors']),self)
            if d.exec()!=QDialog.DialogCode.Accepted:return
            flavors=d.selected
        for _ in range(qty):
            final,offer=price_with_offer(p)
            self.items.append({'product_id':p['id'],'name':p['name'],'base_price':float(p['price']),'final_price':float(final),'quantity':1,'flavors':flavors,'offer_id':offer['id'] if offer else None,'offer_name':offer['name'] if offer else None})
        apply_cart_offers(self.items); self.refresh_items()

    def remove_item(self):
        r=self.table.currentRow()
        if r>=0 and r<len(self.items): self.items.pop(r); apply_cart_offers(self.items); self.refresh_items()

    def refresh_items(self):
        self.table.setRowCount(len(self.items)); total=0
        for i,it in enumerate(self.items):
            vals=[it['name'],'1',', '.join(it.get('flavors',[])),f"$ {it['final_price']:,.0f}",f"$ {it['final_price']:,.0f}"]
            total+=it['final_price']
            for c,v in enumerate(vals):self.table.setItem(i,c,QTableWidgetItem(str(v)))
        self.total.setText(f'TOTAL $ {total:,.0f}')

    def save(self):
        if not self.items: QMessageBox.warning(self,'Pedido','Agregá al menos un producto.');return
        total=sum(float(x['final_price']) for x in self.items); now=datetime.now().isoformat(timespec='seconds')
        with db() as conn:
            customer_id=None
            if self.dni.text().strip():
                cust=create_or_update_customer(self.dni.text(),self.customer.text().strip(),self.phone.text().strip(),self.address.text().strip())
                customer_id=cust['id']
            elif self.customer.text().strip():
                cur=conn.execute('INSERT INTO customers(name,phone,address) VALUES (?,?,?)',(self.customer.text().strip(),self.phone.text().strip(),self.address.text().strip())); customer_id=cur.lastrowid
            cur=conn.execute('''INSERT INTO orders(created_at,customer_id,user_id,order_type,status,total,address,phone,payment_method,notes,source,payment_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',(now,customer_id,1,self.order_type.currentText(),'NUEVO',total,self.address.text().strip(),self.phone.text().strip(),self.payment.currentText(),self.notes.text().strip(),'MANUAL','')); oid=cur.lastrowid
            for it in self.items:
                conn.execute('''INSERT INTO order_items(order_id,product_id,product_name,quantity,unit_price,line_total,flavor_text) VALUES (?,?,?,?,?,?,?)''',(oid,it['product_id'],it['name'],1,it['final_price'],it['final_price'],', '.join(it.get('flavors',[]))))
            conn.execute('INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)',(now,'Administrador','PEDIDO',f'Pedido #{oid} por ${total:,.2f}'))
        self.order_id=oid
        self.accept()



class PedidosPage(QWidget):
    """Gestión visual de pedidos Web / Delivery.

    V15 reemplaza el detalle en QMessageBox por una vista maestro/detalle
    permanente, pensada para operar el pedido sin abrir ventanas informativas.
    """

    TRACKING = ['EN PROCESO','EN PREPARACIÓN','PREPARADO','ENVIADO','ENTREGADO']
    TERMINAL = {'ENTREGADO','CANCELADO','RECHAZADO'}
    NEXT = {
        'NUEVO': 'EN PROCESO',
        'EN PROCESO': 'EN PREPARACIÓN',
        'EN PREPARACIÓN': 'PREPARADO',
        'PREPARADO': 'ENVIADO',
        'ENVIADO': 'ENTREGADO',
    }

    def __init__(self, back_callback, current_user=None):
        super().__init__()
        self.back_callback = back_callback
        self.current_user = current_user or {'name':'SISTEMA CENTRAL','role':'ADMIN'}
        self.current_order_id = None
        self._last_signature = None
        self._mp_sync_tick = 0
        self.build_ui()
        self.refresh(select_first=True)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.safe_refresh)
        self.timer.start(2500)

    # ---------- UI ----------
    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20,16,20,20)
        root.setSpacing(10)

        header = QHBoxLayout()
        back = QPushButton('← Volver')
        back.setMinimumHeight(44)
        back.setStyleSheet('background:#eee5ea;color:#4a3740;')
        back.clicked.connect(self.back_callback)
        title = QLabel('📲 Pedidos Web / Delivery')
        title.setStyleSheet('font-size:27px;font-weight:900;color:#352831;')
        self.live = QLabel('● EN VIVO')
        self.live.setStyleSheet('color:#168a56;font-weight:900;font-size:14px;')
        header.addWidget(back)
        header.addSpacing(8)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.live)
        root.addLayout(header)

        self.banner = QLabel('Seleccioná un pedido para gestionarlo.')
        self.banner.setWordWrap(True)
        self.banner.setMinimumHeight(36)
        self.banner.setStyleSheet('background:#eef6ff;color:#315b80;border-radius:10px;padding:8px 12px;font-weight:800;')
        root.addWidget(self.banner)

        # Resumen rápido.
        cards = QHBoxLayout(); cards.setSpacing(8)
        self.kpi_pending = self._kpi('⏳', 'Pendientes')
        self.kpi_preparing = self._kpi('👨‍🍳', 'Preparando')
        self.kpi_ready = self._kpi('📦', 'Preparados')
        self.kpi_sent = self._kpi('🛵', 'Enviados')
        for card in (self.kpi_pending,self.kpi_preparing,self.kpi_ready,self.kpi_sent):
            cards.addWidget(card)
        root.addLayout(cards)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        root.addWidget(splitter, 1)

        # ----- Columna izquierda: lista -----
        left = QFrame(); left.setObjectName('ordersListPanel')
        left.setStyleSheet('#ordersListPanel{background:#ffffff;border:1px solid #eadfe4;border-radius:14px;}')
        lv = QVBoxLayout(left); lv.setContentsMargins(12,12,12,12); lv.setSpacing(8)

        filters = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText('Buscar Nº de pedido, cliente, teléfono o dirección…')
        self.search.textChanged.connect(self.refresh)
        self.status_filter = QComboBox()
        self.status_filter.addItems(['ACTIVOS','NUEVOS / PENDIENTES','EN PREPARACIÓN','PREPARADO','ENVIADO','ENTREGADO','CANCELADO','RECHAZADO','TODOS'])
        self.status_filter.currentTextChanged.connect(self.refresh)
        self.date_filter = QComboBox()
        self.date_filter.addItems(['HOY','AYER','ÚLTIMOS 7 DÍAS','FECHA ELEGIDA','TODO EL HISTORIAL'])
        self.date_filter.currentTextChanged.connect(self._date_filter_changed)
        self.date_pick = QDateEdit(QDate.currentDate())
        self.date_pick.setCalendarPopup(True)
        self.date_pick.setDisplayFormat('dd/MM/yyyy')
        self.date_pick.setEnabled(False)
        self.date_pick.dateChanged.connect(self.refresh)
        new_btn = QPushButton('＋ Nuevo')
        new_btn.setStyleSheet('background:#36c978;color:white;')
        new_btn.clicked.connect(self.new_order)
        refresh_btn = QPushButton('↻')
        refresh_btn.setToolTip('Actualizar ahora')
        refresh_btn.setStyleSheet('background:#e8f2ff;color:#285f98;')
        refresh_btn.clicked.connect(lambda: self.refresh())
        filters.addWidget(self.search,1); filters.addWidget(self.status_filter); filters.addWidget(self.date_filter); filters.addWidget(self.date_pick); filters.addWidget(new_btn); filters.addWidget(refresh_btn)
        lv.addLayout(filters)

        self.table = QTableWidget(0,6)
        self.table.setHorizontalHeaderLabels(['#','Hora','Cliente','Estado','Pago','Total'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self.table.itemSelectionChanged.connect(self.load_selected_detail)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        lv.addWidget(self.table,1)
        splitter.addWidget(left)

        # ----- Columna derecha: gestión -----
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_host = QFrame(); self.detail_host.setObjectName('orderDetailPanel')
        self.detail_host.setStyleSheet('#orderDetailPanel{background:#ffffff;border:1px solid #eadfe4;border-radius:14px;}')
        dv = QVBoxLayout(self.detail_host); dv.setContentsMargins(16,14,16,18); dv.setSpacing(10)

        dh = QHBoxLayout()
        self.order_title = QLabel('Pedido')
        self.order_title.setStyleSheet('font-size:25px;font-weight:900;color:#30252c;')
        self.status_badge = QLabel('SIN SELECCIÓN'); self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setMinimumWidth(160); self.status_badge.setMinimumHeight(34)
        dh.addWidget(self.order_title); dh.addStretch(); dh.addWidget(self.status_badge)
        dv.addLayout(dh)

        self.order_meta = QLabel('Seleccioná un pedido de la lista.')
        self.order_meta.setWordWrap(True); self.order_meta.setStyleSheet('color:#78656f;font-size:13px;')
        dv.addWidget(self.order_meta)

        # Progreso visual.
        progress_box = QFrame(); progress_box.setObjectName('progressBox')
        progress_box.setStyleSheet('#progressBox{background:#faf7ff;border:1px solid #e6dcf7;border-radius:12px;}')
        pv = QVBoxLayout(progress_box); pv.setContentsMargins(10,10,10,10); pv.setSpacing(8)
        ptitle = QLabel('ESTADO DEL PEDIDO'); ptitle.setStyleSheet('font-size:12px;font-weight:900;color:#6b4ea1;')
        pv.addWidget(ptitle)
        steps = QHBoxLayout(); steps.setSpacing(6)
        step_defs=[('EN PROCESO','1\nRECIBIDO'),('EN PREPARACIÓN','2\nPREPARANDO'),('PREPARADO','3\nPREPARADO'),('ENVIADO','4\nENVIADO'),('ENTREGADO','5\nENTREGADO')]
        self.step_labels={}
        for key,txt in step_defs:
            lab=QLabel(txt); lab.setAlignment(Qt.AlignmentFlag.AlignCenter); lab.setMinimumHeight(52); lab.setWordWrap(True)
            self.step_labels[key]=lab; steps.addWidget(lab,1)
        pv.addLayout(steps); dv.addWidget(progress_box)

        # Datos del cliente.
        customer_box = self._section('👤 Cliente / Entrega')
        cg = QGridLayout(); cg.setHorizontalSpacing(18); cg.setVerticalSpacing(5)
        self.customer_name = self._value_label(); self.customer_phone = self._value_label(); self.customer_address = self._value_label(); self.customer_zone = self._value_label()
        cg.addWidget(QLabel('Cliente'),0,0); cg.addWidget(self.customer_name,0,1)
        cg.addWidget(QLabel('Teléfono'),1,0); cg.addWidget(self.customer_phone,1,1)
        cg.addWidget(QLabel('Dirección'),2,0); cg.addWidget(self.customer_address,2,1)
        cg.addWidget(QLabel('Zona'),3,0); cg.addWidget(self.customer_zone,3,1)
        customer_box.layout().addLayout(cg); dv.addWidget(customer_box)

        # Pago.
        payment_box = self._section('💳 Pago')
        pg = QGridLayout(); pg.setHorizontalSpacing(18); pg.setVerticalSpacing(5)
        self.payment_method = self._value_label(); self.payment_status = self._value_label(); self.payment_cash = self._value_label(); self.refund_status = self._value_label()
        pg.addWidget(QLabel('Medio'),0,0); pg.addWidget(self.payment_method,0,1)
        pg.addWidget(QLabel('Estado'),1,0); pg.addWidget(self.payment_status,1,1)
        pg.addWidget(QLabel('Efectivo / vuelto'),2,0); pg.addWidget(self.payment_cash,2,1)
        pg.addWidget(QLabel('Reintegro'),3,0); pg.addWidget(self.refund_status,3,1)
        payment_box.layout().addLayout(pg)
        pay_actions=QHBoxLayout(); pay_actions.setSpacing(6)
        self.btn_approve=QPushButton('✅ CONFIRMAR PAGO'); self.btn_approve.setStyleSheet('background:#17a66a;color:white;')
        self.btn_reject=QPushButton('❌ RECHAZAR PAGO'); self.btn_reject.setStyleSheet('background:#c83556;color:white;')
        self.btn_proof=QPushButton('📎 COMPROBANTE'); self.btn_proof.setStyleSheet('background:#5d6cc1;color:white;')
        self.btn_refund=QPushButton('💸 REINTEGRADO'); self.btn_refund.setStyleSheet('background:#7b5cc7;color:white;')
        self.btn_mp=QPushButton('↻ ACTUALIZAR MERCADO PAGO'); self.btn_mp.setStyleSheet('background:#009ee3;color:white;')
        self.btn_approve.clicked.connect(self.approve_transfer); self.btn_reject.clicked.connect(self.reject_transfer); self.btn_proof.clicked.connect(self.open_proof); self.btn_refund.clicked.connect(self.mark_refunded); self.btn_mp.clicked.connect(self.update_mercadopago)
        for b in (self.btn_approve,self.btn_reject,self.btn_proof,self.btn_refund,self.btn_mp): pay_actions.addWidget(b)
        payment_box.layout().addLayout(pay_actions); dv.addWidget(payment_box)

        # Productos.
        items_box = self._section('🍨 Productos y gustos')
        self.items_table = QTableWidget(0,4)
        self.items_table.setHorizontalHeaderLabels(['Cant.','Producto','Gustos','Total'])
        self.items_table.verticalHeader().setVisible(False); self.items_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.items_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        ih=self.items_table.horizontalHeader(); ih.setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents); ih.setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents); ih.setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch); ih.setSectionResizeMode(3,QHeaderView.ResizeMode.ResizeToContents)
        self.items_table.setMinimumHeight(125); self.items_table.setMaximumHeight(220)
        items_box.layout().addWidget(self.items_table); dv.addWidget(items_box)

        # Gestión del estado.
        manage_box = self._section('🚦 Gestionar pedido')
        self.next_hint=QLabel(''); self.next_hint.setWordWrap(True); self.next_hint.setStyleSheet('font-size:14px;font-weight:800;color:#54434c;')
        manage_box.layout().addWidget(self.next_hint)
        state_grid=QGridLayout(); state_grid.setSpacing(7)
        state_defs=[('EN PROCESO','⏳ RECIBIDO'),('EN PREPARACIÓN','👨‍🍳 EN PREPARACIÓN'),('PREPARADO','📦 PREPARADO'),('ENVIADO','🛵 ENVIADO'),('ENTREGADO','✅ ENTREGADO')]
        self.state_buttons={}
        for idx,(state,label) in enumerate(state_defs):
            b=QPushButton(label); b.setMinimumHeight(48); b.clicked.connect(lambda _, s=state:self.transition_to(s)); self.state_buttons[state]=b
            state_grid.addWidget(b,idx//3,idx%3)
        manage_box.layout().addLayout(state_grid)
        bottom_actions=QHBoxLayout(); bottom_actions.setSpacing(7)
        self.btn_cancel=QPushButton('🚫 CANCELAR PEDIDO'); self.btn_cancel.setStyleSheet('background:#d56a2d;color:white;'); self.btn_cancel.clicked.connect(self.cancel_order)
        self.btn_print=QPushButton('🖨 IMPRIMIR TICKET'); self.btn_print.setStyleSheet('background:#e55b88;color:white;'); self.btn_print.clicked.connect(self.print_selected)
        bottom_actions.addWidget(self.btn_cancel); bottom_actions.addWidget(self.btn_print)
        manage_box.layout().addLayout(bottom_actions); dv.addWidget(manage_box)

        # Historial y notas.
        history_box=self._section('🕘 Historial')
        self.history_table=QTableWidget(0,3); self.history_table.setHorizontalHeaderLabels(['Fecha / hora','Estado','Detalle']); self.history_table.verticalHeader().setVisible(False); self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.history_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        hh2=self.history_table.horizontalHeader(); hh2.setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents); hh2.setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents); hh2.setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        self.history_table.setMinimumHeight(120); self.history_table.setMaximumHeight(220)
        history_box.layout().addWidget(self.history_table)
        self.notes_label=QLabel(''); self.notes_label.setWordWrap(True); self.notes_label.setStyleSheet('background:#fff9e8;border-radius:8px;padding:8px;color:#5e4f31;')
        history_box.layout().addWidget(self.notes_label); dv.addWidget(history_box)
        dv.addStretch()

        scroll.setWidget(self.detail_host); splitter.addWidget(scroll)
        splitter.setStretchFactor(0,4); splitter.setStretchFactor(1,6); splitter.setSizes([500,720])

        self._clear_detail()

    def _kpi(self, icon, title):
        frame=QFrame(); frame.setStyleSheet('background:white;border:1px solid #eadfe4;border-radius:12px;')
        lay=QHBoxLayout(frame); lay.setContentsMargins(12,8,12,8)
        i=QLabel(icon); i.setStyleSheet('font-size:24px;border:none;')
        text=QVBoxLayout(); val=QLabel('0'); val.setObjectName('kpiValue'); val.setStyleSheet('font-size:22px;font-weight:900;border:none;'); cap=QLabel(title); cap.setStyleSheet('font-size:12px;color:#7a6670;border:none;')
        text.addWidget(val); text.addWidget(cap); lay.addWidget(i); lay.addLayout(text); lay.addStretch(); frame.value_label=val
        return frame

    def _section(self, title):
        frame=QFrame(); frame.setObjectName('sectionCard'); frame.setStyleSheet('#sectionCard{background:#fff;border:1px solid #eadfe4;border-radius:11px;}')
        lay=QVBoxLayout(frame); lay.setContentsMargins(12,10,12,11); lay.setSpacing(8)
        lab=QLabel(title); lab.setStyleSheet('font-size:15px;font-weight:900;color:#4b3942;border:none;'); lay.addWidget(lab)
        return frame

    def _value_label(self):
        lab=QLabel('—'); lab.setWordWrap(True); lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); lab.setStyleSheet('font-weight:800;color:#2f2530;')
        return lab

    def _set_banner(self, text, kind='info'):
        styles={
            'info':'background:#eef6ff;color:#315b80;',
            'ok':'background:#e8f8ee;color:#17613c;',
            'warn':'background:#fff3da;color:#7a5410;',
            'error':'background:#ffe8ed;color:#a72743;',
        }
        self.banner.setText(text); self.banner.setStyleSheet(styles.get(kind,styles['info'])+'border-radius:10px;padding:8px 12px;font-weight:800;')

    # ---------- Datos / refresco ----------
    def _date_filter_changed(self, *_):
        self.date_pick.setEnabled(self.date_filter.currentText() == 'FECHA ELEGIDA')
        self.refresh()

    def _row_matches_date(self, created_at):
        mode = self.date_filter.currentText() if hasattr(self,'date_filter') else 'HOY'
        if mode == 'TODO EL HISTORIAL':
            return True
        try:
            dt = datetime.fromisoformat(str(created_at or '').replace('Z','+00:00'))
            day = dt.date()
        except Exception:
            return False
        today = datetime.now().date()
        if mode == 'HOY':
            return day == today
        if mode == 'AYER':
            return day == (today - timedelta(days=1))
        if mode == 'ÚLTIMOS 7 DÍAS':
            return day >= (today - timedelta(days=6))
        if mode == 'FECHA ELEGIDA':
            return day == self.date_pick.date().toPyDate()
        return True

    def selected_id(self):
        r=self.table.currentRow()
        if r>=0 and self.table.item(r,0):
            try:return int(self.table.item(r,0).text())
            except Exception:return None
        return self.current_order_id

    def safe_refresh(self):
        try:
            self._mp_sync_tick += 1
            if self._mp_sync_tick >= 2:
                self._mp_sync_tick = 0
                self._sync_pending_mp_orders()
            self.refresh()
        except Exception as e:
            self.live.setText('● ERROR DE ACTUALIZACIÓN')
            self.live.setStyleSheet('color:#b4233d;font-weight:900;')
            self._set_banner(f'No se pudo actualizar la lista: {e}','error')

    def _sync_pending_mp_orders(self):
        # Mercado Pago es la fuente de verdad: si acredita, el pedido pasa solo a preparación.
        try:
            with db() as conn:
                rows=conn.execute("SELECT id FROM orders WHERE UPPER(COALESCE(payment_method,'')) IN ('MERCADO PAGO','MERCADOPAGO','MERCADO_PAGO') AND COALESCE(mercadopago_order_id,'')<>'' AND UPPER(COALESCE(status,'')) NOT IN ('ENTREGADO','CANCELADO','RECHAZADO') AND UPPER(COALESCE(payment_status,''))<>'PAGO_APROBADO' ORDER BY id DESC LIMIT 10").fetchall()
            for row in rows:
                try: sync_local_order(int(row['id']),auto_transition=True)
                except Exception: pass
        except Exception:
            pass

    def refresh(self, *_args, select_first=False):
        query=(self.search.text().strip() if hasattr(self,'search') else '').lower()
        status_filter=(self.status_filter.currentText() if hasattr(self,'status_filter') else 'TODOS')
        with db() as conn:
            rows=conn.execute("""SELECT o.*,COALESCE(c.name,'') customer_name FROM orders o
                               LEFT JOIN customers c ON c.id=o.customer_id ORDER BY o.id DESC""").fetchall()
        counts={'EN PROCESO':0,'EN PREPARACIÓN':0,'PREPARADO':0,'ENVIADO':0}
        filtered=[]
        for r in rows:
            state=str(r['status'] or '').upper()
            if state in counts:counts[state]+=1
            if not self._row_matches_date(r['created_at']): continue
            if status_filter=='ACTIVOS' and state in self.TERMINAL: continue
            if status_filter=='NUEVOS / PENDIENTES' and state not in ('NUEVO','EN PROCESO'): continue
            if status_filter not in ('TODOS','ACTIVOS','NUEVOS / PENDIENTES') and state!=status_filter: continue
            hay=' '.join([str(r['id']),str(r['customer_name'] or ''),str(r['phone'] or ''),str(r['address'] or ''),state,str(r['payment_status'] or ''),str(r['payment_method'] or '')]).lower()
            if query and query not in hay: continue
            filtered.append(r)
        self.kpi_pending.value_label.setText(str(counts['EN PROCESO']))
        self.kpi_preparing.value_label.setText(str(counts['EN PREPARACIÓN']))
        self.kpi_ready.value_label.setText(str(counts['PREPARADO']))
        self.kpi_sent.value_label.setText(str(counts['ENVIADO']))

        previous=self.current_order_id or self.selected_id()
        self.table.blockSignals(True)
        self.table.setRowCount(len(filtered))
        restore=-1
        for i,r in enumerate(filtered):
            if previous and int(r['id'])==int(previous):restore=i
            created=self._display_time(r['created_at'])
            pay=(r['payment_status'] or r['payment_method'] or '').replace('_',' ')
            vals=[r['id'],created,r['customer_name'] or 'Sin nombre',r['status'] or '',pay,f"$ {float(r['total'] or 0):,.0f}"]
            for c,v in enumerate(vals):
                item=QTableWidgetItem(str(v)); self.table.setItem(i,c,item)
            state=str(r['status'] or '').upper()
            bg = '#e4f7ec' if state=='ENTREGADO' else '#ffe2e7' if state in ('RECHAZADO','CANCELADO') else '#fff1d6' if state=='EN PROCESO' else '#e8f2ff' if state in ('EN PREPARACIÓN','PREPARADO') else '#efe8ff'
            for c in range(self.table.columnCount()):
                self.table.item(i,c).setBackground(QColor(bg))
        if restore>=0:
            self.table.selectRow(restore)
        elif (select_first or self.current_order_id is None) and filtered:
            self.table.selectRow(0); restore=0
        self.table.blockSignals(False)
        if restore>=0:
            self.current_order_id=int(self.table.item(restore,0).text())
            self.load_order_detail(self.current_order_id)
        elif not filtered:
            self.current_order_id=None; self._clear_detail()
        self.live.setText('● EN VIVO · sincronizado')
        self.live.setStyleSheet('color:#168a56;font-weight:900;font-size:14px;')

    def load_selected_detail(self):
        oid=self.selected_id()
        if oid:
            self.current_order_id=oid
            self.load_order_detail(oid)

    def load_order_detail(self, oid):
        try:
            try:
                sync_local_order(int(oid), auto_transition=True)
            except Exception:
                pass
            with db() as conn:
                o=conn.execute("""SELECT o.*,COALESCE(c.name,'') customer_name,COALESCE(c.dni,'') customer_dni,
                                         COALESCE(c.customer_status,'ACTIVO') customer_status,c.order_blocked_until,c.order_block_reason
                                  FROM orders o LEFT JOIN customers c ON c.id=o.customer_id WHERE o.id=?""",(int(oid),)).fetchone()
                if not o:
                    self._clear_detail(); return
                items=conn.execute('SELECT * FROM order_items WHERE order_id=? ORDER BY id',(int(oid),)).fetchall()
                events=conn.execute('SELECT * FROM order_status_events WHERE order_id=? ORDER BY id DESC LIMIT 20',(int(oid),)).fetchall()
            self.order_title.setText(f"Pedido #{o['id']}")
            points_txt=f" · ⭐ +{int(o['loyalty_points_earned'] or 0)} pts" if int(o['loyalty_points_earned'] or 0)>0 else ''
            redeem_txt=f" · 🎁 -{int(o['loyalty_points_redeemed'] or 0)} pts" if int(o['loyalty_points_redeemed'] or 0)>0 else ''
            fee_txt=(f" · Envío $ {float(o['delivery_fee'] or 0):,.0f}" if str(o['order_type'] or '').upper()=='DELIVERY' else ' · Retiro $ 0') if str(o['source'] or '').upper()=='WEB' else ''
            sale_txt=f" · Venta #{o['sale_id']}" if o['sale_id'] else ''
            self.order_meta.setText(f"{self._display_datetime(o['created_at'])} · Origen: {o['source'] or 'MANUAL'} · Tipo: {o['order_type'] or '—'} · Total: $ {float(o['total'] or 0):,.0f}{fee_txt}{redeem_txt}{points_txt}{sale_txt}")
            self._paint_status_badge(str(o['status'] or ''))
            self._update_progress(str(o['status'] or ''))

            name=o['customer_name'] or 'Sin nombre'; dni=o['customer_dni'] or ''
            cust_state=str(o['customer_status'] or 'ACTIVO').upper()
            block_extra=''
            if o['order_blocked_until']:
                block_extra=f" · PEDIDOS BLOQUEADOS HASTA {self._display_datetime(o['order_blocked_until'])}"
            elif cust_state in ('BLOQUEADO','SUSPENDIDO'):
                block_extra=f" · {cust_state}"
            self.customer_name.setText(name + (f" · DNI {dni}" if dni else '') + block_extra)
            self.customer_phone.setText(o['phone'] or '—')
            self.customer_address.setText(o['address'] or '—')
            zone=(o['zone_status'] or 'A VERIFICAR').replace('_',' ')
            dist=''
            if o['delivery_distance_km'] is not None:
                try:dist=f" · {float(o['delivery_distance_km']):.1f} km"
                except Exception:pass
            self.customer_zone.setText(zone+dist)

            method=(o['payment_method'] or '—').replace('_',' ')
            pstatus=(o['payment_status'] or method).replace('_',' ')
            self.payment_method.setText(method)
            self.payment_status.setText(pstatus)
            if str(o['payment_method'] or '').upper()=='EFECTIVO' and float(o['cash_tendered'] or 0)>0:
                self.payment_cash.setText(f"Paga con $ {float(o['cash_tendered']):,.0f} · Vuelto $ {float(o['change_due'] or 0):,.0f}")
            else:self.payment_cash.setText('—')
            self.refund_status.setText((o['refund_status'] or '—').replace('_',' '))

            self.items_table.setRowCount(len(items))
            for r,it in enumerate(items):
                vals=[f"{float(it['quantity'] or 0):g}",it['product_name'],it['flavor_text'] or '—',f"$ {float(it['line_total'] or 0):,.0f}"]
                for c,v in enumerate(vals):self.items_table.setItem(r,c,QTableWidgetItem(str(v)))
            self.items_table.resizeRowsToContents()

            self.history_table.setRowCount(len(events))
            for r,e in enumerate(events):
                vals=[self._display_datetime(e['created_at']),e['status'],e['note'] or '']
                for c,v in enumerate(vals):self.history_table.setItem(r,c,QTableWidgetItem(str(v)))
            self.history_table.resizeRowsToContents()

            notes=[]
            if o['notes']:notes.append('Notas: '+str(o['notes']))
            if int(o['loyalty_points_redeemed'] or 0)>0:
                notes.append(f"Canje online: {o['loyalty_reward_name'] or 'beneficio'} · -{int(o['loyalty_points_redeemed'])} pts · descuento $ {float(o['loyalty_discount'] or 0):,.0f}")
            if str(o['source'] or '').upper()=='WEB':
                notes.append(('Delivery' if str(o['order_type'] or '').upper()=='DELIVERY' else 'Retiro en local')+f" · costo $ {float(o['delivery_fee'] or 0):,.0f}")
            if 'mercadopago_order_id' in o.keys() and o['mercadopago_order_id']:
                notes.append(f"Mercado Pago: {o['mercadopago_order_id']} · {o['mercadopago_status'] or 'created'} / {o['mercadopago_status_detail'] or ''}")
            if o['payment_rejection_reason']:notes.append('Motivo rechazo: '+str(o['payment_rejection_reason']))
            if o['cancellation_reason']:notes.append('Motivo cancelación: '+str(o['cancellation_reason']))
            if o['refund_notes']:notes.append('Reintegro: '+str(o['refund_notes']))
            self.notes_label.setText('\n'.join(notes) if notes else 'Sin observaciones adicionales.')

            self._configure_actions(o)
            sig=(o['id'],o['status'],o['payment_status'],o['refund_status'],o['status_updated_at'])
            if self._last_signature and sig!=self._last_signature and self._last_signature[0]==o['id']:
                self._set_banner(f"Pedido #{o['id']} actualizado: {str(o['status']).replace('_',' ')}",'ok')
            self._last_signature=sig
        except Exception as e:
            self._set_banner(f'No se pudo cargar el pedido #{oid}: {e}','error')

    def _clear_detail(self):
        self.order_title.setText('Pedido')
        self.order_meta.setText('Seleccioná un pedido de la lista para verlo y gestionarlo acá.')
        self.status_badge.setText('SIN SELECCIÓN'); self.status_badge.setStyleSheet('background:#ece7ea;color:#67555e;border-radius:10px;padding:7px 10px;font-weight:900;')
        for lab in (self.customer_name,self.customer_phone,self.customer_address,self.customer_zone,self.payment_method,self.payment_status,self.payment_cash,self.refund_status):lab.setText('—')
        self.items_table.setRowCount(0); self.history_table.setRowCount(0); self.notes_label.setText('')
        self._update_progress('')
        for b in list(self.state_buttons.values())+[self.btn_approve,self.btn_reject,self.btn_proof,self.btn_refund,self.btn_mp,self.btn_cancel,self.btn_print]:b.setEnabled(False)
        self.next_hint.setText('Seleccioná un pedido para habilitar las acciones.')

    def _configure_actions(self, o):
        state=str(o['status'] or '').upper()
        pay_method=str(o['payment_method'] or '').upper()
        pay_status=str(o['payment_status'] or '').upper()
        terminal=state in self.TERMINAL
        pending_transfer=(pay_method=='TRANSFERENCIA' and pay_status in ('PENDIENTE_VERIFICACION','PENDIENTE DE VERIFICACION','PENDIENTE',''))
        is_mp=pay_method in ('MERCADO PAGO','MERCADOPAGO','MERCADO_PAGO')
        # V25: los botones visibles responden siempre que el pedido no esté cerrado.
        # Si una acción no corresponde, el propio handler explica el motivo.
        self.btn_approve.setEnabled(not terminal)
        self.btn_reject.setEnabled(not terminal)
        self.btn_proof.setEnabled(not terminal or bool(o['payment_proof_path']))
        self.btn_refund.setEnabled(state=='CANCELADO')
        mp_cfg=mp_configuration_status(); mp_ready=mp_cfg.get('qr_ready',False)
        mp_order=bool(o['mercadopago_order_id'] if 'mercadopago_order_id' in o.keys() else '')
        mp_qr=bool(o['mercadopago_qr_data'] if 'mercadopago_qr_data' in o.keys() else '')
        self.btn_mp.setEnabled(not terminal and is_mp)
        if mp_order and not mp_qr:
            self.btn_mp.setText('↻ ACTUALIZAR MERCADO PAGO')
        elif mp_order:
            self.btn_mp.setText('💙 VER / ACTUALIZAR QR MP')
        else:
            self.btn_mp.setText('💙 GENERAR QR MP')
        self.btn_cancel.setEnabled(not terminal)
        self.btn_print.setEnabled(True)

        current_alias={'APROBADO':'EN PREPARACIÓN','LISTO':'PREPARADO','EN REPARTO':'ENVIADO'}.get(state,state)
        expected=self.NEXT.get(current_alias)
        for target,b in self.state_buttons.items():
            is_current=(target==current_alias)
            enabled=(target==expected and not terminal)
            if target=='EN PREPARACIÓN' and current_alias=='EN PROCESO' and pay_method=='TRANSFERENCIA' and pay_status!='PAGO_APROBADO':
                enabled=False
            if target=='EN PREPARACIÓN' and current_alias=='EN PROCESO' and pay_method in ('MERCADO PAGO','MERCADOPAGO','MERCADO_PAGO') and pay_status!='PAGO_APROBADO':
                enabled=False
            b.setEnabled(enabled)
            if is_current:
                b.setStyleSheet('background:#352b73;color:white;border:3px solid #8f7ee7;')
                b.setText('✓ '+self._state_label(target))
            elif enabled:
                b.setStyleSheet('background:#3f9df7;color:white;border:3px solid #b9dcff;')
                b.setText('→ '+self._state_label(target))
            else:
                b.setStyleSheet('background:#eee9ef;color:#8f8389;')
                b.setText(self._state_label(target))

        if terminal:
            msg='Este pedido está cerrado. Ya no admite cambios de estado.'
        elif pending_transfer:
            msg='Primero verificá el comprobante y usá “APROBAR PAGO” o “RECHAZAR”.'
        elif pay_method in ('MERCADO PAGO','MERCADOPAGO','MERCADO_PAGO') and pay_status!='PAGO_APROBADO':
            msg='Mercado Pago pendiente. El sistema consulta el estado automáticamente; también podés abrir el QR con el botón azul.'
        elif expected:
            msg=f'Siguiente paso habilitado: {expected}. Tocá el botón azul para avanzar.'
        else:
            msg='No hay un siguiente estado operativo disponible.'
        self.next_hint.setText(msg)

    def _state_label(self,state):
        return {'EN PROCESO':'⏳ RECIBIDO','EN PREPARACIÓN':'👨‍🍳 EN PREPARACIÓN','PREPARADO':'📦 PREPARADO','ENVIADO':'🛵 ENVIADO','ENTREGADO':'✅ ENTREGADO'}.get(state,state)

    def _paint_status_badge(self,state):
        state=str(state or '').upper(); colors={'EN PROCESO':('#fff1d6','#795100'),'EN PREPARACIÓN':('#e7f1ff','#285f98'),'PREPARADO':('#e9e7ff','#53429a'),'ENVIADO':('#efe8ff','#6945a8'),'ENTREGADO':('#e4f7ec','#17613c'),'CANCELADO':('#ffe8e0','#9c3d18'),'RECHAZADO':('#ffe2e7','#a72743')}
        bg,fg=colors.get(state,('#ece7ea','#67555e'))
        self.status_badge.setText(state or '—'); self.status_badge.setStyleSheet(f'background:{bg};color:{fg};border-radius:10px;padding:7px 10px;font-weight:900;')

    def _update_progress(self,state):
        state={'APROBADO':'EN PREPARACIÓN','LISTO':'PREPARADO','EN REPARTO':'ENVIADO'}.get(str(state or '').upper(),str(state or '').upper())
        try:idx=self.TRACKING.index(state)
        except ValueError:idx=-1
        terminal_bad=state in ('CANCELADO','RECHAZADO')
        for i,key in enumerate(self.TRACKING):
            lab=self.step_labels[key]
            if terminal_bad:
                style='background:#f3eef1;color:#a18f98;border:1px solid #e3d8de;'
            elif i<idx:
                style='background:#e4f7ec;color:#17613c;border:2px solid #b6e5c9;'
            elif i==idx:
                style='background:#352b73;color:white;border:3px solid #8f7ee7;'
            else:
                style='background:#f2eef4;color:#8a7a82;border:1px solid #e3d8de;'
            lab.setStyleSheet(style+'border-radius:9px;padding:6px;font-size:11px;font-weight:900;')

    def _display_datetime(self,value):
        s=str(value or '')
        try:
            d=datetime.fromisoformat(s.replace('Z','+00:00')); return d.strftime('%d/%m/%Y %H:%M:%S')
        except Exception:return s

    def _display_time(self,value):
        s=str(value or '')
        try:
            d=datetime.fromisoformat(s.replace('Z','+00:00')); return d.strftime('%H:%M')
        except Exception:return s[-8:-3] if len(s)>=8 else s

    def actor(self):
        return str((self.current_user or {}).get('name') or 'SISTEMA CENTRAL')

    # ---------- Acciones ----------
    def new_order(self):
        d=OrderForm(self)
        if d.exec()==QDialog.DialogCode.Accepted:
            self.current_order_id=d.order_id; self.refresh()
            if d.order_id:
                should_print=get_setting('auto_print_order','0')=='1'
                if not should_print:
                    should_print=QMessageBox.question(self,'Pedido guardado',f'Pedido #{d.order_id} guardado.\n\n¿Imprimir ticket de pedido?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes
                if should_print:
                    try:print_order_ticket(d.order_id,parent=self)
                    except Exception as e:self._set_banner(f'Pedido guardado, pero no se pudo imprimir: {e}','warn')

    def print_selected(self):
        oid=self.current_order_id or self.selected_id()
        if not oid:return
        try:
            print_order_ticket(oid,parent=self); self._set_banner(f'Ticket del pedido #{oid} enviado a impresión.','ok')
        except Exception as e:QMessageBox.critical(self,'Ticket',f'No se pudo imprimir el pedido.\n\n{e}')

    def _show_mp_qr_dialog(self, oid):
        with db() as conn:
            o=conn.execute('SELECT total,mercadopago_qr_data,mercadopago_order_id,payment_status FROM orders WHERE id=?',(int(oid),)).fetchone()
        if not o or not o['mercadopago_qr_data']:
            QMessageBox.warning(self,'Mercado Pago','Mercado Pago no devolvió una trama QR para este pedido.')
            return
        try:
            import qrcode
            img=qrcode.make(str(o['mercadopago_qr_data']))
            out=io.BytesIO(); img.save(out,format='PNG')
            pix=QPixmap(); pix.loadFromData(out.getvalue(),'PNG')
        except Exception as exc:
            QMessageBox.warning(self,'Mercado Pago',f'No se pudo construir el QR.\n\n{exc}')
            return
        dlg=QDialog(self); dlg.setWindowTitle(f'Mercado Pago · Pedido #{oid}'); dlg.resize(480,620)
        lay=QVBoxLayout(dlg)
        title=QLabel(f'💙 MERCADO PAGO · PEDIDO #{oid}'); title.setAlignment(Qt.AlignmentFlag.AlignCenter); title.setStyleSheet('font-size:21px;font-weight:900;color:#0879a8;')
        amount=QLabel(f'TOTAL A COBRAR\n$ {float(o["total"] or 0):,.0f}'); amount.setAlignment(Qt.AlignmentFlag.AlignCenter); amount.setStyleSheet('font-size:26px;font-weight:950;background:#e9f8ff;padding:12px;border-radius:12px;')
        qr=QLabel(); qr.setAlignment(Qt.AlignmentFlag.AlignCenter); qr.setPixmap(pix.scaled(340,340,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        info=QLabel(f'Order MP: {o["mercadopago_order_id"]}\nEstado: {(o["payment_status"] or "PENDIENTE").replace("_"," ")}\n\nEl cliente escanea este QR con Mercado Pago y el importe aparece automáticamente.')
        info.setWordWrap(True); info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sync=QPushButton('↻ ACTUALIZAR ESTADO DE PAGO'); sync.setMinimumHeight(48); sync.setStyleSheet('background:#009ee3;color:white;font-weight:900;')
        sync.clicked.connect(lambda: self._sync_mp_and_close(dlg,oid))
        close=QPushButton('CERRAR · ESC'); close.clicked.connect(dlg.reject)
        lay.addWidget(title); lay.addWidget(amount); lay.addWidget(qr,1); lay.addWidget(info); lay.addWidget(sync); lay.addWidget(close)
        dlg.exec()

    def _sync_mp_and_close(self, dlg, oid):
        try:
            sync_local_order(int(oid), auto_transition=True)
            self.refresh()
            dlg.accept()
            self._set_banner(f'Pedido #{oid}: estado Mercado Pago actualizado.','ok')
        except Exception as exc:
            QMessageBox.warning(self,'Mercado Pago',str(exc))

    def update_mercadopago(self):
        oid=self.current_order_id or self.selected_id()
        if not oid:
            QMessageBox.information(self,'Pedidos','Seleccioná un pedido primero.')
            return
        with db() as conn:
            row=conn.execute('SELECT payment_method,mercadopago_order_id FROM orders WHERE id=?',(int(oid),)).fetchone()
        if not row:
            return
        if str(row['payment_method'] or '').upper() not in ('MERCADO PAGO','MERCADOPAGO','MERCADO_PAGO'):
            QMessageBox.information(self,'Mercado Pago','Este pedido no fue generado con Mercado Pago.')
            return
        if not row['mercadopago_order_id']:
            QMessageBox.warning(self,'Mercado Pago','El pedido todavía no tiene una orden de Mercado Pago asociada. Si el cliente aún no inició el pago, debe hacerlo desde su pedido Web.')
            return
        try:
            result=sync_local_order(int(oid),auto_transition=True)
            self.refresh()
            if result.get('payment_status')=='PAGO_APROBADO':
                self._set_banner(f'Pedido #{oid}: PAGO APROBADO · EN PREPARACIÓN.','ok')
            else:
                shown=str(result.get('payment_status') or 'PENDIENTE').replace('_',' ')
                self._set_banner(f'Pedido #{oid}: Mercado Pago respondió {shown}.','warn')
        except Exception as exc:
            QMessageBox.critical(self,'Mercado Pago',f'No se pudo actualizar el pago.\n\n{exc}')

    def generate_mp_qr(self):
        oid=self.current_order_id or self.selected_id()
        if not oid:return
        try:
            with db() as conn:
                row=conn.execute('SELECT mercadopago_order_id,mercadopago_qr_data FROM orders WHERE id=?',(int(oid),)).fetchone()
            # Un pago Web Checkout API tiene order de MP pero no trama QR.
            if row and row['mercadopago_order_id'] and not row['mercadopago_qr_data']:
                result=sync_local_order(int(oid),auto_transition=True)
                self.refresh()
                if result.get('payment_status')=='PAGO_APROBADO':
                    self._set_banner(f'Pedido #{oid}: PAGO APROBADO · pasó automáticamente a EN PREPARACIÓN.','ok')
                else:
                    shown=str(result.get('payment_status') or 'PENDIENTE').replace('_',' ')
                    self._set_banner(f'Pedido #{oid}: Mercado Pago actualizado · {shown}.','warn')
                return
            attach_qr_to_order(int(oid),recreate=False)
            self.refresh()
            self._show_mp_qr_dialog(int(oid))
        except Exception as exc:
            QMessageBox.critical(self,'Mercado Pago',str(exc))

    def approve_transfer(self):
        oid=self.current_order_id or self.selected_id()
        if not oid:return
        try:
            with db() as conn:
                row=conn.execute('SELECT payment_method,payment_status,mercadopago_order_id FROM orders WHERE id=?',(int(oid),)).fetchone()
            if not row:return
            method=str(row['payment_method'] or '').upper()
            if method in ('MERCADO PAGO','MERCADOPAGO','MERCADO_PAGO'):
                if not row['mercadopago_order_id']:
                    QMessageBox.warning(self,'Mercado Pago','Este pedido todavía no tiene una orden de Mercado Pago asociada.')
                    return
                result=sync_local_order(int(oid),auto_transition=True)
                self.refresh()
                if result.get('payment_status')=='PAGO_APROBADO':
                    self._set_banner(f'Pedido #{oid}: PAGO APROBADO · EN PREPARACIÓN.','ok')
                else:
                    QMessageBox.information(self,'Mercado Pago','Mercado Pago todavía no informó el pago como aprobado. El sistema no permite aprobarlo manualmente.')
                return
            if method!='TRANSFERENCIA':
                QMessageBox.information(self,'Confirmar pago','La confirmación manual se usa solamente para transferencias. Mercado Pago se confirma automáticamente.')
                return
            if QMessageBox.question(self,'Confirmar pago',f'¿Confirmás que verificaste la transferencia del pedido #{oid}?\n\nAl confirmar, pasa automáticamente a EN PREPARACIÓN.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            from app.services.order_service import approve_transfer
            approve_transfer(oid,self.actor())
            self.refresh(); self._set_banner(f'Pedido #{oid}: PAGO APROBADO · EN PREPARACIÓN.','ok')
            try:print_order_ticket(oid,parent=self)
            except Exception as e:self._set_banner(f'Pago aprobado. El ticket no pudo imprimirse: {e}','warn')
        except Exception as e:QMessageBox.critical(self,'No se pudo confirmar el pago',str(e))

    def reject_transfer(self):
        oid=self.current_order_id or self.selected_id()
        if not oid:return
        with db() as conn:
            row=conn.execute('SELECT payment_method,payment_status FROM orders WHERE id=?',(int(oid),)).fetchone()
        if not row:return
        if str(row['payment_method'] or '').upper()!='TRANSFERENCIA':
            QMessageBox.information(self,'Rechazar pago','El rechazo manual corresponde a transferencias. Los pagos de Mercado Pago toman el estado informado por Mercado Pago.')
            return
        reasons=['TRANSFERENCIA FRAUDULENTA','COMPROBANTE TRUCHO / ALTERADO','DATOS O IMPORTE NO COINCIDEN','TRANSFERENCIA NO RECIBIDA','OTRO']
        reason,ok=QInputDialog.getItem(self,'Rechazar transferencia','Motivo obligatorio:',reasons,0,False)
        if not ok:return
        if reason=='OTRO':
            reason,ok=QInputDialog.getText(self,'Motivo del rechazo','Describí el motivo:')
            if not ok:return
        try:
            from app.services.order_service import reject_transfer
            reject_transfer(oid,reason,self.actor()); self.refresh()
            suffix=' · cliente bloqueado para nuevos pedidos por 2 horas' if any(x in str(reason).upper() for x in ('FRAUD','TRUCHO','ALTERADO','FALSO')) else ''
            self._set_banner(f'Pedido #{oid} rechazado: {reason}{suffix}','error')
        except Exception as e:QMessageBox.critical(self,'No se pudo rechazar',str(e))

    def transition_to(self,target):
        oid=self.current_order_id or self.selected_id()
        if not oid:return
        try:
            with db() as conn:o=conn.execute('SELECT status,payment_method,payment_status FROM orders WHERE id=?',(oid,)).fetchone()
            if not o:return
            current={'APROBADO':'EN PREPARACIÓN','LISTO':'PREPARADO','EN REPARTO':'ENVIADO'}.get(str(o['status'] or '').upper(),str(o['status'] or '').upper())
            if target!=self.NEXT.get(current):
                self._set_banner(f'No se puede pasar directamente de {current} a {target}.','warn'); return
            if current=='EN PROCESO' and str(o['payment_method'] or '').upper()=='TRANSFERENCIA' and str(o['payment_status'] or '').upper()!='PAGO_APROBADO':
                self._set_banner('Primero tenés que aprobar la transferencia.','warn'); return
            if current=='EN PROCESO' and str(o['payment_method'] or '').upper() in ('MERCADO PAGO','MERCADOPAGO','MERCADO_PAGO') and str(o['payment_status'] or '').upper()!='PAGO_APROBADO':
                self._set_banner('Mercado Pago todavía no acreditó el pago.','warn'); return
            if QMessageBox.question(self,'Cambiar estado',f'Pedido #{oid}\n\n{current}  →  {target}\n\n¿Confirmar?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            from app.services.order_service import transition_order
            transition_order(oid,target,self.actor()); self.refresh(); self._set_banner(f'Pedido #{oid} actualizado a {target}.','ok')
        except Exception as e:QMessageBox.critical(self,'No se pudo cambiar el estado',str(e))

    def advance_status(self):
        oid=self.current_order_id or self.selected_id()
        if not oid:return
        with db() as conn:o=conn.execute('SELECT status FROM orders WHERE id=?',(oid,)).fetchone()
        if not o:return
        current={'APROBADO':'EN PREPARACIÓN','LISTO':'PREPARADO','EN REPARTO':'ENVIADO'}.get(str(o['status'] or '').upper(),str(o['status'] or '').upper())
        nxt=self.NEXT.get(current)
        if nxt:self.transition_to(nxt)

    def cancel_order(self):
        oid=self.current_order_id or self.selected_id()
        if not oid:return
        reason,ok=QInputDialog.getText(self,'Cancelar pedido','Motivo obligatorio de cancelación:')
        if not ok or not reason.strip():return
        try:
            from app.services.order_service import cancel_order
            result=cancel_order(oid,reason,self.actor()); self.refresh()
            if result.get('refund_status')=='PENDIENTE_REINTEGRO':
                self._set_banner(f'Pedido #{oid} CANCELADO · REINTEGRO PENDIENTE.','warn')
            else:self._set_banner(f'Pedido #{oid} cancelado.','warn')
        except Exception as e:QMessageBox.critical(self,'No se pudo cancelar',str(e))

    def mark_refunded(self):
        oid=self.current_order_id or self.selected_id()
        if not oid:return
        note,ok=QInputDialog.getText(self,'Confirmar reintegro','Referencia / observación del reintegro (opcional):')
        if not ok:return
        try:
            from app.services.order_service import mark_refunded
            mark_refunded(oid,note,self.actor()); self.refresh(); self._set_banner(f'Pedido #{oid}: reintegro marcado como REINTEGRADO.','ok')
        except Exception as e:QMessageBox.critical(self,'Reintegro',str(e))

    def open_proof(self):
        oid=self.current_order_id or self.selected_id()
        if not oid:return
        try:
            with db() as conn:o=conn.execute('SELECT payment_proof_path FROM orders WHERE id=?',(oid,)).fetchone()
            if not o or not o['payment_proof_path']:
                self._set_banner('Este pedido no tiene comprobante adjunto.','warn'); return
            path=(DATA_DIR/'comprobantes_web'/str(o['payment_proof_path'])).resolve()
            if not path.exists():
                self._set_banner('No se encontró el archivo del comprobante.','error'); return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception as e:QMessageBox.critical(self,'Comprobante',str(e))

    # Compatibilidad con botones/rutas de versiones anteriores.
    def change_status(self):
        self.advance_status()

    def detail(self,*_):
        # V15: el detalle ya vive de forma permanente en el panel derecho.
        self.load_selected_detail()
