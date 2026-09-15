from PyQt6.QtWidgets import *
from app.database import db


class FlavorForm(QDialog):
    def __init__(self, flavor_id=None, parent=None):
        super().__init__(parent); self.flavor_id=flavor_id
        self.setWindowTitle('Editar sabor' if flavor_id else 'Nuevo sabor'); self.resize(430,500)
        f=QFormLayout(self); f.setSpacing(12)
        self.name=QLineEdit(); self.category=QComboBox(); self.category.addItems(['CREMAS','FRUTALES','CHOCOLATES','DULCE DE LECHE','PREMIUM','OTROS'])
        self.stock=QDoubleSpinBox(); self.stock.setMaximum(99999); self.stock.setDecimals(3); self.stock.setSuffix(' kg')
        self.minimum=QDoubleSpinBox(); self.minimum.setMaximum(99999); self.minimum.setDecimals(3); self.minimum.setSuffix(' kg'); self.minimum.setValue(1)
        self.premium=QCheckBox('Es sabor premium'); self.extra=QDoubleSpinBox(); self.extra.setMaximum(9999999); self.extra.setPrefix('$ ')
        self.available=QCheckBox('Disponible para vender'); self.available.setChecked(True)
        self.active=QCheckBox('Sabor activo'); self.active.setChecked(True)
        for label,w in [('Nombre *',self.name),('Categoría',self.category),('Stock actual',self.stock),('Stock mínimo',self.minimum),('Adicional premium',self.extra)]: f.addRow(label,w)
        f.addRow(self.premium); f.addRow(self.available); f.addRow(self.active)
        save=QPushButton('💾 GUARDAR SABOR'); save.setMinimumHeight(48); save.setStyleSheet('background:#26b86a;color:white;'); save.clicked.connect(self.save); f.addRow(save)
        if flavor_id: self.load_data()

    def load_data(self):
        with db() as conn: r=conn.execute('SELECT * FROM flavors WHERE id=?',(self.flavor_id,)).fetchone()
        if not r: return
        self.name.setText(r['name']); idx=self.category.findText(r['category']);
        if idx>=0: self.category.setCurrentIndex(idx)
        self.stock.setValue(float(r['stock_kg'])); self.minimum.setValue(float(r['min_stock_kg'])); self.premium.setChecked(bool(r['premium']))
        self.extra.setValue(float(r['premium_extra'])); self.available.setChecked(bool(r['available'])); self.active.setChecked(bool(r['active']))

    def save(self):
        if not self.name.text().strip(): QMessageBox.warning(self,'Sabor','Ingresá un nombre.'); return
        data=(self.name.text().strip(),self.category.currentText(),self.stock.value(),self.minimum.value(),int(self.premium.isChecked()),self.extra.value(),int(self.active.isChecked()),int(self.available.isChecked()))
        try:
            with db() as conn:
                if self.flavor_id:
                    conn.execute('UPDATE flavors SET name=?,category=?,stock_kg=?,min_stock_kg=?,premium=?,premium_extra=?,active=?,available=? WHERE id=?',data+(self.flavor_id,))
                else:
                    conn.execute('INSERT INTO flavors(name,category,stock_kg,min_stock_kg,premium,premium_extra,active,available) VALUES (?,?,?,?,?,?,?,?)',data)
            self.accept()
        except Exception as e: QMessageBox.critical(self,'Sabor',f'No se pudo guardar.\n{e}')


class SaboresPage(QWidget):
    def __init__(self, back_callback):
        super().__init__(); self.back_callback=back_callback; self.build_ui(); self.refresh()
    def build_ui(self):
        root=QVBoxLayout(self); root.setContentsMargins(28,24,28,28); root.setSpacing(12)
        h=QHBoxLayout(); b=QPushButton('← Volver a Opciones'); b.setStyleSheet('background:#eee5ea;color:#4a3740;'); b.clicked.connect(self.back_callback)
        t=QLabel('🍨 Sabores / Gustos'); t.setStyleSheet('font-size:28px;font-weight:900;'); h.addWidget(b); h.addSpacing(16); h.addWidget(t); h.addStretch(); root.addLayout(h)
        a=QHBoxLayout();
        new=QPushButton('＋ NUEVO SABOR'); new.setStyleSheet('background:#ff5f96;color:white;'); new.clicked.connect(lambda:self.open_form())
        edit=QPushButton('✏ EDITAR'); edit.setStyleSheet('background:#3f9df7;color:white;'); edit.clicked.connect(self.edit_selected)
        toggle=QPushButton('🍨 DISPONIBLE / AGOTADO'); toggle.setStyleSheet('background:#ff9f43;color:white;'); toggle.clicked.connect(self.toggle_available)
        active=QPushButton('✓ ACTIVAR / DESACTIVAR'); active.setStyleSheet('background:#8d6bd1;color:white;'); active.clicked.connect(self.toggle_active)
        for x in (new,edit,toggle,active): a.addWidget(x)
        a.addStretch(); root.addLayout(a)
        self.table=QTableWidget(0,8); self.table.setHorizontalHeaderLabels(['ID','Sabor','Categoría','Stock KG','Mínimo','Premium','Disponible','Activo'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.table.doubleClicked.connect(self.edit_selected)
        root.addWidget(self.table)
    def selected_id(self):
        r=self.table.currentRow(); return int(self.table.item(r,0).text()) if r>=0 else None
    def refresh(self):
        with db() as conn: rows=conn.execute('SELECT * FROM flavors ORDER BY category,name').fetchall()
        self.table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            vals=[r['id'],r['name'],r['category'],f"{r['stock_kg']:.3f}",f"{r['min_stock_kg']:.3f}",'Sí' if r['premium'] else 'No','DISPONIBLE' if r['available'] else 'AGOTADO','Sí' if r['active'] else 'No']
            for c,v in enumerate(vals): self.table.setItem(i,c,QTableWidgetItem(str(v)))
        self.table.resizeColumnsToContents(); self.table.horizontalHeader().setStretchLastSection(True)
    def open_form(self,fid=None):
        d=FlavorForm(fid,self)
        if d.exec()==QDialog.DialogCode.Accepted: self.refresh()
    def edit_selected(self,*_):
        fid=self.selected_id()
        if fid: self.open_form(fid)
    def toggle_available(self):
        fid=self.selected_id()
        if not fid: return
        with db() as conn: conn.execute('UPDATE flavors SET available=CASE available WHEN 1 THEN 0 ELSE 1 END WHERE id=?',(fid,))
        self.refresh()
    def toggle_active(self):
        fid=self.selected_id()
        if not fid: return
        with db() as conn: conn.execute('UPDATE flavors SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?',(fid,))
        self.refresh()
