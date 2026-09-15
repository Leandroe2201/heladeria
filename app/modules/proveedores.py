from PyQt6.QtWidgets import *
from app.database import db

class SupplierForm(QDialog):
    def __init__(self,sid=None,parent=None):
        super().__init__(parent);self.sid=sid;self.setWindowTitle('Editar proveedor' if sid else 'Nuevo proveedor');f=QFormLayout(self)
        self.name=QLineEdit();self.tax=QLineEdit();self.phone=QLineEdit();self.email=QLineEdit();self.notes=QLineEdit();self.active=QCheckBox('Proveedor activo');self.active.setChecked(True)
        for a,w in [('Nombre *',self.name),('CUIT',self.tax),('Teléfono',self.phone),('Email',self.email),('Notas',self.notes)]:f.addRow(a,w)
        f.addRow(self.active);b=QPushButton('💾 GUARDAR');b.setStyleSheet('background:#26b86a;color:white;');b.clicked.connect(self.save);f.addRow(b)
        if sid:self.load()
    def load(self):
        with db() as c:r=c.execute('SELECT * FROM suppliers WHERE id=?',(self.sid,)).fetchone()
        if r:self.name.setText(r['name']);self.tax.setText(r['tax_id'] or '');self.phone.setText(r['phone'] or '');self.email.setText(r['email'] or '');self.notes.setText(r['notes'] or '');self.active.setChecked(bool(r['active']))
    def save(self):
        if not self.name.text().strip():return
        d=(self.name.text().strip(),self.tax.text().strip(),self.phone.text().strip(),self.email.text().strip(),self.notes.text().strip(),int(self.active.isChecked()))
        with db() as c:
            if self.sid:c.execute('UPDATE suppliers SET name=?,tax_id=?,phone=?,email=?,notes=?,active=? WHERE id=?',d+(self.sid,))
            else:c.execute('INSERT INTO suppliers(name,tax_id,phone,email,notes,active) VALUES (?,?,?,?,?,?)',d)
        self.accept()

class ProveedoresPage(QWidget):
    def __init__(self,back_callback):
        super().__init__();self.back_callback=back_callback;self.build();self.refresh()
    def build(self):
        l=QVBoxLayout(self);l.setContentsMargins(28,24,28,28);h=QHBoxLayout();b=QPushButton('← Volver a Opciones');b.setStyleSheet('background:#eee5ea;color:#4a3740;');b.clicked.connect(self.back_callback);t=QLabel('🚚 Proveedores');t.setStyleSheet('font-size:28px;font-weight:900;');h.addWidget(b);h.addSpacing(16);h.addWidget(t);h.addStretch();l.addLayout(h)
        a=QHBoxLayout();n=QPushButton('＋ NUEVO PROVEEDOR');n.setStyleSheet('background:#36c978;color:white;');n.clicked.connect(lambda:self.form());e=QPushButton('✏ EDITAR');e.setStyleSheet('background:#3f9df7;color:white;');e.clicked.connect(self.edit);a.addWidget(n);a.addWidget(e);a.addStretch();l.addLayout(a)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['ID','Proveedor','CUIT','Teléfono','Email','Activo']);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.table.doubleClicked.connect(self.edit);l.addWidget(self.table)
    def sid(self):
        r=self.table.currentRow();return int(self.table.item(r,0).text()) if r>=0 else None
    def refresh(self):
        with db() as c:rows=c.execute('SELECT * FROM suppliers ORDER BY name').fetchall()
        self.table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            vals=[r['id'],r['name'],r['tax_id'] or '',r['phone'] or '',r['email'] or '','Sí' if r['active'] else 'No']
            for j,v in enumerate(vals):self.table.setItem(i,j,QTableWidgetItem(str(v)))
        self.table.resizeColumnsToContents();self.table.horizontalHeader().setStretchLastSection(True)
    def form(self,sid=None):
        d=SupplierForm(sid,self)
        if d.exec()==QDialog.DialogCode.Accepted:self.refresh()
    def edit(self,*_):
        if self.sid():self.form(self.sid())
