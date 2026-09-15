from datetime import datetime
from PyQt6.QtWidgets import *
from app.database import db

class ComprasPage(QWidget):
    def __init__(self,back_callback):
        super().__init__();self.back_callback=back_callback;self.build();self.refresh()
    def build(self):
        l=QVBoxLayout(self);l.setContentsMargins(28,24,28,28);h=QHBoxLayout();b=QPushButton('← Volver a Opciones');b.setStyleSheet('background:#eee5ea;color:#4a3740;');b.clicked.connect(self.back_callback);t=QLabel('🛒 Compras');t.setStyleSheet('font-size:28px;font-weight:900;');h.addWidget(b);h.addSpacing(16);h.addWidget(t);h.addStretch();l.addLayout(h)
        n=QPushButton('＋ NUEVA COMPRA');n.setStyleSheet('background:#36c978;color:white;');n.clicked.connect(self.add);l.addWidget(n)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['ID','Fecha','Proveedor','Total','Pago','Notas']);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);l.addWidget(self.table)
    def refresh(self):
        with db() as c:rows=c.execute('''SELECT pu.*,COALESCE(s.name,'') supplier_name FROM purchases pu LEFT JOIN suppliers s ON s.id=pu.supplier_id ORDER BY pu.id DESC''').fetchall()
        self.table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            vals=[r['id'],r['created_at'],r['supplier_name'],f"$ {r['total']:,.0f}",r['payment_method'] or '',r['notes'] or '']
            for j,v in enumerate(vals):self.table.setItem(i,j,QTableWidgetItem(str(v)))
        self.table.resizeColumnsToContents();self.table.horizontalHeader().setStretchLastSection(True)
    def add(self):
        d=QDialog(self);d.setWindowTitle('Nueva compra');f=QFormLayout(d);sup=QComboBox();sup.addItem('Sin proveedor',None)
        with db() as c:
            for r in c.execute('SELECT id,name FROM suppliers WHERE active=1 ORDER BY name'):sup.addItem(r['name'],r['id'])
        amount=QDoubleSpinBox();amount.setMaximum(999999999);amount.setPrefix('$ ');pay=QComboBox();pay.addItems(['EFECTIVO','DÉBITO','CRÉDITO','QR / TRANSFERENCIA','CUENTA CORRIENTE']);notes=QLineEdit()
        f.addRow('Proveedor',sup);f.addRow('Total *',amount);f.addRow('Pago',pay);f.addRow('Detalle / notas',notes);s=QPushButton('Guardar compra');s.setStyleSheet('background:#26b86a;color:white;');f.addRow(s)
        def save():
            if amount.value()<=0:return
            with db() as c:c.execute('INSERT INTO purchases(created_at,supplier_id,total,payment_method,notes) VALUES (?,?,?,?,?)',(datetime.now().isoformat(timespec='seconds'),sup.currentData(),amount.value(),pay.currentText(),notes.text().strip()))
            d.accept();self.refresh()
        s.clicked.connect(save);d.exec()
