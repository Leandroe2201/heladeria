from PyQt6.QtWidgets import *
from app.database import db
from app.settings_service import get_setting, set_setting
from app.services.loyalty_service import list_rewards, create_or_update_customer


class RewardForm(QDialog):
    def __init__(self, reward_id=None, parent=None):
        super().__init__(parent); self.reward_id=reward_id
        self.setWindowTitle('Editar beneficio' if reward_id else 'Nuevo beneficio')
        f=QFormLayout(self)
        self.name=QLineEdit(); self.points=QSpinBox(); self.points.setRange(1,999999)
        self.type=QComboBox(); self.type.addItems(['DESCUENTO_FIJO','PORCENTAJE','PRODUCTO_GRATIS'])
        self.value=QDoubleSpinBox(); self.value.setRange(0,999999999); self.value.setDecimals(2)
        self.product=QComboBox(); self.product.addItem('Sin producto',None)
        with db() as c:
            for r in c.execute('SELECT id,name FROM products WHERE active=1 ORDER BY name'):
                self.product.addItem(r['name'],r['id'])
        self.active=QCheckBox('Activo'); self.active.setChecked(True)
        self.notes=QLineEdit()
        for lab,w in [('Nombre *',self.name),('Puntos requeridos',self.points),('Tipo de canje',self.type),('Valor',self.value),('Producto (si corresponde)',self.product),('Notas',self.notes)]:f.addRow(lab,w)
        f.addRow(self.active)
        b=QPushButton('💾 GUARDAR BENEFICIO'); b.setStyleSheet('background:#29b86d;color:white;'); b.clicked.connect(self.save); f.addRow(b)
        if reward_id:self.load()
    def load(self):
        with db() as c:r=c.execute('SELECT * FROM loyalty_rewards WHERE id=?',(self.reward_id,)).fetchone()
        if not r:return
        self.name.setText(r['name']);self.points.setValue(int(r['points_cost']));self.type.setCurrentText(r['reward_type']);self.value.setValue(float(r['value'] or 0));self.active.setChecked(bool(r['active']));self.notes.setText(r['notes'] or '')
        idx=self.product.findData(r['product_id']);
        if idx>=0:self.product.setCurrentIndex(idx)
    def save(self):
        if not self.name.text().strip():
            QMessageBox.information(self,'Beneficio','Ingresá un nombre para el beneficio.')
            return
        if self.type.currentText()=='PRODUCTO_GRATIS' and self.product.currentData() is None:
            QMessageBox.warning(self,'Beneficio','Para un canje directo de PRODUCTO_GRATIS tenés que seleccionar qué producto se entrega.')
            return
        data=(self.name.text().strip(),self.points.value(),self.type.currentText(),self.value.value(),self.product.currentData(),int(self.active.isChecked()),self.notes.text().strip())
        with db() as c:
            if self.reward_id:c.execute('UPDATE loyalty_rewards SET name=?,points_cost=?,reward_type=?,value=?,product_id=?,active=?,notes=? WHERE id=?',data+(self.reward_id,))
            else:c.execute('INSERT INTO loyalty_rewards(name,points_cost,reward_type,value,product_id,active,notes) VALUES (?,?,?,?,?,?,?)',data)
        self.accept()


class FidelidadPage(QWidget):
    def __init__(self, back_callback):
        super().__init__();self.back_callback=back_callback;self.build();self.refresh()
    def build(self):
        root=QVBoxLayout(self);root.setContentsMargins(28,24,28,28);root.setSpacing(12)
        h=QHBoxLayout();b=QPushButton('← Volver a Opciones');b.setStyleSheet('background:#eee5ea;color:#4a3740;');b.clicked.connect(self.back_callback);t=QLabel('⭐ Fidelidad / Puntos');t.setStyleSheet('font-size:28px;font-weight:900;');h.addWidget(b);h.addSpacing(16);h.addWidget(t);h.addStretch();root.addLayout(h)
        cfg=QFrame();cfg.setStyleSheet('background:white;border:1px solid #eadfe4;border-radius:14px;');f=QFormLayout(cfg)
        self.enabled=QCheckBox('Sistema de puntos activo');self.enabled.setChecked(get_setting('loyalty_enabled','1')=='1')
        self.amount=QDoubleSpinBox();self.amount.setRange(1,999999999);self.amount.setDecimals(0);self.amount.setPrefix('$ ');self.amount.setValue(float(get_setting('loyalty_amount_per_point','1000')))
        self.step=QSpinBox();self.step.setRange(1,1000);self.step.setValue(int(float(get_setting('loyalty_points_per_step','1'))))
        save=QPushButton('💾 GUARDAR REGLAS');save.setStyleSheet('background:#34b96f;color:white;');save.clicked.connect(self.save_rules)
        f.addRow(self.enabled);f.addRow('Cada este importe vendido',self.amount);f.addRow('Puntos que suma',self.step);f.addRow('',save);root.addWidget(cfg)
        info=QLabel('Ejemplo: si configurás $1.000 = 1 punto, una venta de $9.500 suma 9 puntos. Para el botón CANJEAR PUNTOS de la caja, creá beneficios PRODUCTO_GRATIS y asignales un producto; el canje genera una venta por $0 y descuenta los puntos.');info.setWordWrap(True);info.setStyleSheet('color:#6f5b66;');root.addWidget(info)
        bar=QHBoxLayout();n=QPushButton('＋ NUEVO BENEFICIO');n.setStyleSheet('background:#ff6a9d;color:white;');n.clicked.connect(lambda:self.open_reward());e=QPushButton('✏ EDITAR BENEFICIO');e.setStyleSheet('background:#4a9df3;color:white;');e.clicked.connect(self.edit_reward);bar.addWidget(n);bar.addWidget(e);bar.addStretch();root.addLayout(bar)
        self.rewards=QTableWidget(0,7);self.rewards.setHorizontalHeaderLabels(['ID','Beneficio','Puntos','Tipo','Valor','Producto','Activo']);self.rewards.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.rewards.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.rewards.doubleClicked.connect(self.edit_reward);root.addWidget(self.rewards)
        root.addWidget(QLabel('Clientes con tarjeta de fidelidad'))
        self.customers=QTableWidget(0,6);self.customers.setHorizontalHeaderLabels(['DNI','Cliente','Tarjeta','Puntos','Teléfono','Compras']);self.customers.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.customers.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);root.addWidget(self.customers)
    def save_rules(self):
        set_setting('loyalty_enabled','1' if self.enabled.isChecked() else '0');set_setting('loyalty_amount_per_point',str(self.amount.value()));set_setting('loyalty_points_per_step',str(self.step.value()));QMessageBox.information(self,'Fidelidad','Reglas de puntos guardadas.')
    def reward_id(self):
        r=self.rewards.currentRow();return int(self.rewards.item(r,0).text()) if r>=0 else None
    def open_reward(self,rid=None):
        d=RewardForm(rid,self)
        if d.exec()==QDialog.DialogCode.Accepted:self.refresh()
    def edit_reward(self,*_):
        rid=self.reward_id()
        if rid:self.open_reward(rid)
    def refresh(self):
        rows=list_rewards(False);self.rewards.setRowCount(len(rows))
        for i,r in enumerate(rows):
            val='-' if r['reward_type']=='PRODUCTO_GRATIS' else (f"{r['value']:g}%" if r['reward_type']=='PORCENTAJE' else f"$ {r['value']:,.0f}")
            vals=[r['id'],r['name'],r['points_cost'],r['reward_type'],val,r['product_name'] or '', 'Sí' if r['active'] else 'No']
            for c,v in enumerate(vals):self.rewards.setItem(i,c,QTableWidgetItem(str(v)))
        self.rewards.resizeColumnsToContents();self.rewards.horizontalHeader().setStretchLastSection(True)
        with db() as c:rows=c.execute('''SELECT c.*,COUNT(s.id) purchases FROM customers c LEFT JOIN sales s ON s.customer_id=c.id WHERE COALESCE(c.dni,'')<>'' GROUP BY c.id ORDER BY c.points DESC,c.name''').fetchall()
        self.customers.setRowCount(len(rows))
        for i,r in enumerate(rows):
            vals=[r['dni'],r['name'],r['loyalty_card_number'] or '',r['points'],r['phone'] or '',r['purchases']]
            for c,v in enumerate(vals):self.customers.setItem(i,c,QTableWidgetItem(str(v)))
        self.customers.resizeColumnsToContents();self.customers.horizontalHeader().setStretchLastSection(True)
