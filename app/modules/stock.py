from PyQt6.QtWidgets import *
from app.database import db

class StockForm(QDialog):
    def __init__(self,sid=None,parent=None):
        super().__init__(parent);self.sid=sid;self.setWindowTitle('Editar insumo' if sid else 'Nuevo insumo');f=QFormLayout(self);self.name=QLineEdit();self.unit=QComboBox();self.unit.addItems(['u','kg','lt','caja','pack']);self.qty=QDoubleSpinBox();self.qty.setMaximum(99999999);self.qty.setDecimals(3);self.minimum=QDoubleSpinBox();self.minimum.setMaximum(99999999);self.minimum.setDecimals(3);self.active=QCheckBox('Insumo activo');self.active.setChecked(True)
        for a,w in [('Nombre *',self.name),('Unidad',self.unit),('Cantidad',self.qty),('Mínimo',self.minimum)]:f.addRow(a,w)
        f.addRow(self.active);b=QPushButton('💾 GUARDAR');b.setStyleSheet('background:#26b86a;color:white;');b.clicked.connect(self.save);f.addRow(b)
        if sid:self.load()
    def load(self):
        with db() as c:r=c.execute('SELECT * FROM stock_items WHERE id=?',(self.sid,)).fetchone()
        if r:self.name.setText(r['name']);i=self.unit.findText(r['unit']);self.unit.setCurrentIndex(max(0,i));self.qty.setValue(r['quantity']);self.minimum.setValue(r['minimum']);self.active.setChecked(bool(r['active']))
    def save(self):
        if not self.name.text().strip():return
        d=(self.name.text().strip(),self.unit.currentText(),self.qty.value(),self.minimum.value(),int(self.active.isChecked()))
        try:
            with db() as c:
                if self.sid:c.execute('UPDATE stock_items SET name=?,unit=?,quantity=?,minimum=?,active=? WHERE id=?',d+(self.sid,))
                else:c.execute('INSERT INTO stock_items(name,unit,quantity,minimum,active) VALUES (?,?,?,?,?)',d)
            self.accept()
        except Exception as e:QMessageBox.critical(self,'Stock',str(e))

class StockPage(QWidget):
    def __init__(self,back_callback):
        super().__init__();self.back_callback=back_callback;self.build();self.refresh()
    def build(self):
        l=QVBoxLayout(self);l.setContentsMargins(28,24,28,28);h=QHBoxLayout();b=QPushButton('← Volver a Opciones');b.setStyleSheet('background:#eee5ea;color:#4a3740;');b.clicked.connect(self.back_callback);t=QLabel('📊 Stock / Insumos');t.setStyleSheet('font-size:28px;font-weight:900;');h.addWidget(b);h.addSpacing(16);h.addWidget(t);h.addStretch();l.addLayout(h)
        a=QHBoxLayout();n=QPushButton('＋ NUEVO INSUMO');n.setStyleSheet('background:#36c978;color:white;');n.clicked.connect(lambda:self.form());e=QPushButton('✏ EDITAR');e.setStyleSheet('background:#3f9df7;color:white;');e.clicked.connect(self.edit);q=QPushButton('± AJUSTAR CANTIDAD');q.setStyleSheet('background:#ff9f43;color:white;');q.clicked.connect(self.adjust)
        for x in(n,e,q):a.addWidget(x)
        a.addStretch();l.addLayout(a)
        self.table=QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['ID','Insumo','Unidad','Cantidad','Mínimo','Estado','Activo']);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.table.doubleClicked.connect(self.edit);l.addWidget(self.table)
    def sid(self):
        r=self.table.currentRow();return int(self.table.item(r,0).text()) if r>=0 else None
    def refresh(self):
        with db() as c:rows=c.execute('SELECT * FROM stock_items ORDER BY name').fetchall()
        self.table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            state='STOCK BAJO' if r['quantity']<=r['minimum'] else 'OK';vals=[r['id'],r['name'],r['unit'],f"{r['quantity']:.3f}",f"{r['minimum']:.3f}",state,'Sí' if r['active'] else 'No']
            for j,v in enumerate(vals):self.table.setItem(i,j,QTableWidgetItem(str(v)))
        self.table.resizeColumnsToContents();self.table.horizontalHeader().setStretchLastSection(True)
    def form(self,sid=None):
        d=StockForm(sid,self)
        if d.exec()==QDialog.DialogCode.Accepted:self.refresh()
    def edit(self,*_):
        if self.sid():self.form(self.sid())
    def adjust(self):
        sid=self.sid()
        if not sid:return
        with db() as c:r=c.execute('SELECT quantity FROM stock_items WHERE id=?',(sid,)).fetchone()
        val,ok=QInputDialog.getDouble(self,'Ajustar stock','Nueva cantidad:',float(r['quantity']),0,99999999,3)
        if ok:
            with db() as c:c.execute('UPDATE stock_items SET quantity=? WHERE id=?',(val,sid))
            self.refresh()
