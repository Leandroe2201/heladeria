from PyQt6.QtCore import QDate, QTime
from PyQt6.QtWidgets import *
from app.database import db

TYPE_LABELS = {
    'PRECIO_FIJO':'Precio especial de 1 unidad',
    'PORCENTAJE':'% de descuento',
    'DESCUENTO_MONTO':'Descuento de $',
    '2X1':'2x1 / NxM',
    'CANTIDAD_PRECIO':'Cantidad por un precio',
    'COMBO_PRECIO':'Combo de productos por un precio',
}

class OfferForm(QDialog):
    def __init__(self, offer_id=None, parent=None):
        super().__init__(parent); self.offer_id=offer_id
        self.setWindowTitle('Editar oferta' if offer_id else 'Nueva oferta'); self.resize(560,720)
        root=QVBoxLayout(self); form=QFormLayout(); form.setSpacing(10); root.addLayout(form)
        self.name=QLineEdit(); self.product=QComboBox(); self._load_products(self.product, include_general=True)
        self.typ=QComboBox()
        for code,label in TYPE_LABELS.items(): self.typ.addItem(label,code)
        self.typ.currentIndexChanged.connect(self.update_hint)
        self.value=QDoubleSpinBox(); self.value.setMaximum(999999999); self.value.setPrefix('$ ')
        self.trigger=QSpinBox(); self.trigger.setRange(2,20); self.trigger.setValue(2)
        self.pay_qty=QSpinBox(); self.pay_qty.setRange(1,20); self.pay_qty.setValue(1)
        self.bundle_qty=QSpinBox(); self.bundle_qty.setRange(2,20); self.bundle_qty.setValue(2)
        self.combo1=QComboBox(); self._load_products(self.combo1); self.combo1qty=QSpinBox(); self.combo1qty.setRange(1,20); self.combo1qty.setValue(1)
        self.combo2=QComboBox(); self._load_products(self.combo2); self.combo2qty=QSpinBox(); self.combo2qty.setRange(1,20); self.combo2qty.setValue(1)
        combo1w=QWidget(); l1=QHBoxLayout(combo1w); l1.setContentsMargins(0,0,0,0); l1.addWidget(self.combo1,1); l1.addWidget(QLabel('Cant.')); l1.addWidget(self.combo1qty)
        combo2w=QWidget(); l2=QHBoxLayout(combo2w); l2.setContentsMargins(0,0,0,0); l2.addWidget(self.combo2,1); l2.addWidget(QLabel('Cant.')); l2.addWidget(self.combo2qty)
        self.start=QDateEdit(QDate.currentDate()); self.start.setCalendarPopup(True)
        self.end=QDateEdit(QDate.currentDate().addMonths(1)); self.end.setCalendarPopup(True)
        self.days=QLineEdit('0,1,2,3,4,5,6'); self.days.setPlaceholderText('0=Lun ... 6=Dom')
        self.start_time=QTimeEdit(QTime(0,0)); self.end_time=QTimeEdit(QTime(23,59))
        self.priority=QSpinBox(); self.priority.setRange(0,999); self.priority.setValue(10)
        self.active=QCheckBox('Oferta activa'); self.active.setChecked(True); self.notes=QLineEdit()
        for label,w in [('Nombre *',self.name),('Tipo de oferta',self.typ),('Producto principal',self.product),('Precio / valor',self.value),('Cantidad que activa',self.trigger),('Cantidad que paga',self.pay_qty),('Cantidad del pack',self.bundle_qty),('Combo producto 1',combo1w),('Combo producto 2',combo2w),('Desde',self.start),('Hasta',self.end),('Días',self.days),('Hora desde',self.start_time),('Hora hasta',self.end_time),('Prioridad',self.priority),('Nota',self.notes)]: form.addRow(label,w)
        form.addRow(self.active)
        self.hint=QLabel(); self.hint.setWordWrap(True); self.hint.setStyleSheet('background:#fff1c9;border-radius:10px;padding:10px;color:#4d4035;'); root.addWidget(self.hint)
        save=QPushButton('💾 GUARDAR OFERTA'); save.setMinimumHeight(50); save.setStyleSheet('background:#26b86a;color:white;'); save.clicked.connect(self.save); root.addWidget(save)
        if offer_id: self.load_data()
        self.update_hint()

    def _load_products(self, combo, include_general=False):
        combo.clear()
        if include_general: combo.addItem('Seleccione producto',None)
        with db() as conn:
            for r in conn.execute('SELECT id,name FROM products WHERE active=1 ORDER BY sort_order,name'): combo.addItem(r['name'],r['id'])

    def update_hint(self):
        typ=self.typ.currentData()
        txt={
            'PRECIO_FIJO':'Ejemplo: 1 KG normalmente $18.000 → oferta a $15.900.',
            'PORCENTAJE':'El valor se interpreta como porcentaje. Ejemplo: 20 = 20% de descuento.',
            'DESCUENTO_MONTO':'El valor se resta al precio normal. Ejemplo: $1.500 de descuento.',
            '2X1':'Usá Cantidad que activa=2 y Cantidad que paga=1 para 2x1. También permite 3x2, 4x3, etc.',
            'CANTIDAD_PRECIO':'Ejemplo: Cantidad del pack=2 y Valor=$10.000 significa 2 unidades por $10.000.',
            'COMBO_PRECIO':'Elegí dos productos y cantidades. El Valor es el precio total del combo.',
        }.get(typ,'')
        self.hint.setText(txt)
        is_combo=typ=='COMBO_PRECIO'; is_nxm=typ=='2X1'; is_bundle=typ=='CANTIDAD_PRECIO'
        self.product.setEnabled(not is_combo); self.trigger.setEnabled(is_nxm); self.pay_qty.setEnabled(is_nxm); self.bundle_qty.setEnabled(is_bundle)
        self.combo1.setEnabled(is_combo); self.combo2.setEnabled(is_combo); self.combo1qty.setEnabled(is_combo); self.combo2qty.setEnabled(is_combo)
        self.value.setPrefix('% ' if typ=='PORCENTAJE' else '$ ')

    def load_data(self):
        with db() as conn:
            r=conn.execute('SELECT * FROM offers WHERE id=?',(self.offer_id,)).fetchone()
            items=conn.execute('SELECT * FROM offer_items WHERE offer_id=? ORDER BY id',(self.offer_id,)).fetchall()
        if not r:return
        self.name.setText(r['name']); idx=self.typ.findData(r['offer_type']);
        if idx>=0:self.typ.setCurrentIndex(idx)
        idx=self.product.findData(r['product_id']);
        if idx>=0:self.product.setCurrentIndex(idx)
        self.value.setValue(float(r['value'])); self.trigger.setValue(int(r['trigger_qty'] or 2)); self.pay_qty.setValue(int(r['pay_qty'] or 1)); self.bundle_qty.setValue(int(r['bundle_qty'] or 2))
        if r['start_date']: self.start.setDate(QDate.fromString(r['start_date'],'yyyy-MM-dd'))
        if r['end_date']: self.end.setDate(QDate.fromString(r['end_date'],'yyyy-MM-dd'))
        self.days.setText(r['days_csv'] or '0,1,2,3,4,5,6'); self.start_time.setTime(QTime.fromString(r['start_time'] or '00:00','HH:mm')); self.end_time.setTime(QTime.fromString(r['end_time'] or '23:59','HH:mm'))
        self.priority.setValue(int(r['priority'])); self.notes.setText(r['notes'] or ''); self.active.setChecked(bool(r['active']))
        if len(items)>0:
            i=self.combo1.findData(items[0]['product_id']);
            if i>=0:self.combo1.setCurrentIndex(i)
            self.combo1qty.setValue(int(items[0]['quantity']))
        if len(items)>1:
            i=self.combo2.findData(items[1]['product_id']);
            if i>=0:self.combo2.setCurrentIndex(i)
            self.combo2qty.setValue(int(items[1]['quantity']))

    def save(self):
        if not self.name.text().strip(): QMessageBox.warning(self,'Oferta','Ingresá un nombre.');return
        typ=self.typ.currentData(); pid=None if typ=='COMBO_PRECIO' else self.product.currentData()
        if typ!='COMBO_PRECIO' and not pid: QMessageBox.warning(self,'Oferta','Seleccioná un producto.');return
        if typ=='COMBO_PRECIO' and (not self.combo1.currentData() or not self.combo2.currentData()): QMessageBox.warning(self,'Oferta','Elegí los productos del combo.');return
        data=(self.name.text().strip(),pid,typ,self.value.value(),self.trigger.value(),self.pay_qty.value(),self.bundle_qty.value(),self.start.date().toString('yyyy-MM-dd'),self.end.date().toString('yyyy-MM-dd'),self.days.text().strip(),self.start_time.time().toString('HH:mm'),self.end_time.time().toString('HH:mm'),int(self.active.isChecked()),self.priority.value(),self.notes.text().strip())
        with db() as conn:
            if self.offer_id:
                conn.execute('''UPDATE offers SET name=?,product_id=?,offer_type=?,value=?,trigger_qty=?,pay_qty=?,bundle_qty=?,start_date=?,end_date=?,days_csv=?,start_time=?,end_time=?,active=?,priority=?,notes=? WHERE id=?''',data+(self.offer_id,)); oid=self.offer_id
                conn.execute('DELETE FROM offer_items WHERE offer_id=?',(oid,))
            else:
                cur=conn.execute('''INSERT INTO offers(name,product_id,offer_type,value,trigger_qty,pay_qty,bundle_qty,start_date,end_date,days_csv,start_time,end_time,active,priority,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',data); oid=cur.lastrowid
            if typ=='COMBO_PRECIO':
                conn.execute('INSERT INTO offer_items(offer_id,product_id,quantity) VALUES (?,?,?)',(oid,self.combo1.currentData(),self.combo1qty.value()))
                conn.execute('INSERT INTO offer_items(offer_id,product_id,quantity) VALUES (?,?,?)',(oid,self.combo2.currentData(),self.combo2qty.value()))
        self.accept()


class OfertasPage(QWidget):
    def __init__(self, back_callback):
        super().__init__(); self.back_callback=back_callback; self.build_ui(); self.refresh()
    def build_ui(self):
        root=QVBoxLayout(self); root.setContentsMargins(28,24,28,28); root.setSpacing(12)
        h=QHBoxLayout(); b=QPushButton('← Volver a Opciones'); b.setStyleSheet('background:#eee5ea;color:#4a3740;'); b.clicked.connect(self.back_callback); t=QLabel('🏷 Ofertas / Promociones'); t.setStyleSheet('font-size:28px;font-weight:900;'); h.addWidget(b); h.addSpacing(16); h.addWidget(t); h.addStretch(); root.addLayout(h)
        a=QHBoxLayout(); new=QPushButton('＋ NUEVA OFERTA'); new.setStyleSheet('background:#ff7d45;color:white;'); new.clicked.connect(lambda:self.open_form()); edit=QPushButton('✏ EDITAR'); edit.setStyleSheet('background:#3f9df7;color:white;'); edit.clicked.connect(self.edit_selected); toggle=QPushButton('▶ ACTIVAR / PAUSAR'); toggle.setStyleSheet('background:#8d6bd1;color:white;'); toggle.clicked.connect(self.toggle)
        for x in(new,edit,toggle):a.addWidget(x)
        a.addStretch(); root.addLayout(a)
        expl=QLabel('Admite: precio especial, % de descuento, descuento fijo, 2x1 / 3x2, 2 por un precio y combos de productos.'); expl.setStyleSheet('color:#725f68;'); root.addWidget(expl)
        self.table=QTableWidget(0,8); self.table.setHorizontalHeaderLabels(['ID','Oferta','Producto / Combo','Tipo','Valor','Desde','Hasta','Activa']); self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.table.doubleClicked.connect(self.edit_selected); root.addWidget(self.table)
    def selected_id(self):
        r=self.table.currentRow(); return int(self.table.item(r,0).text()) if r>=0 else None
    def refresh(self):
        with db() as conn:
            rows=conn.execute('''SELECT o.*,p.name product_name FROM offers o LEFT JOIN products p ON p.id=o.product_id ORDER BY o.priority DESC,o.id DESC''').fetchall()
            combo={}
            for r in rows:
                if r['offer_type']=='COMBO_PRECIO':
                    parts=conn.execute('''SELECT p.name,oi.quantity FROM offer_items oi JOIN products p ON p.id=oi.product_id WHERE oi.offer_id=?''',(r['id'],)).fetchall(); combo[r['id']]=' + '.join(f"{x['quantity']}x {x['name']}" for x in parts)
        self.table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            typ=TYPE_LABELS.get(r['offer_type'],r['offer_type']); product=combo.get(r['id']) or r['product_name'] or 'General'
            if r['offer_type']=='2X1': val=f"{r['trigger_qty']}x{r['pay_qty']}"
            elif r['offer_type']=='CANTIDAD_PRECIO': val=f"{r['bundle_qty']} por $ {r['value']:,.0f}"
            elif r['offer_type']=='PORCENTAJE': val=f"{r['value']:,.0f}%"
            else: val=f"$ {r['value']:,.0f}"
            vals=[r['id'],r['name'],product,typ,val,r['start_date'] or '',r['end_date'] or '','Sí' if r['active'] else 'No']
            for c,v in enumerate(vals):self.table.setItem(i,c,QTableWidgetItem(str(v)))
        self.table.resizeColumnsToContents(); self.table.horizontalHeader().setStretchLastSection(True)
    def open_form(self,oid=None):
        d=OfferForm(oid,self)
        if d.exec()==QDialog.DialogCode.Accepted:self.refresh()
    def edit_selected(self,*_):
        oid=self.selected_id()
        if oid:self.open_form(oid)
    def toggle(self):
        oid=self.selected_id()
        if not oid:return
        with db() as conn:conn.execute('UPDATE offers SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?',(oid,))
        self.refresh()
