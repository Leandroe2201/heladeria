from datetime import datetime
from PyQt6.QtWidgets import *
from app.database import db

class GastosPage(QWidget):
    def __init__(self,back_callback):
        super().__init__();self.back_callback=back_callback;self.build();self.refresh()
    def build(self):
        l=QVBoxLayout(self);l.setContentsMargins(28,24,28,28);h=QHBoxLayout();b=QPushButton('← Volver a Opciones');b.setStyleSheet('background:#eee5ea;color:#4a3740;');b.clicked.connect(self.back_callback);t=QLabel('💸 Gastos');t.setStyleSheet('font-size:28px;font-weight:900;');h.addWidget(b);h.addSpacing(16);h.addWidget(t);h.addStretch();l.addLayout(h)
        n=QPushButton('＋ CARGAR GASTO');n.setStyleSheet('background:#ff7d45;color:white;');n.clicked.connect(self.add);l.addWidget(n)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['ID','Fecha','Categoría','Descripción','Monto','Pago']);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);l.addWidget(self.table)
    def refresh(self):
        with db() as c:rows=c.execute('SELECT * FROM expenses ORDER BY id DESC').fetchall()
        self.table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            vals=[r['id'],r['created_at'],r['category'],r['description'],f"$ {r['amount']:,.0f}",r['payment_method'] or '']
            for j,v in enumerate(vals):self.table.setItem(i,j,QTableWidgetItem(str(v)))
        self.table.resizeColumnsToContents();self.table.horizontalHeader().setStretchLastSection(True)
    def add(self):
        d=QDialog(self);d.setWindowTitle('Cargar gasto');f=QFormLayout(d);cat=QComboBox();cat.addItems(['MERCADERÍA','SERVICIOS','ALQUILER','SUELDOS','MANTENIMIENTO','DELIVERY','OTROS']);desc=QLineEdit();amt=QDoubleSpinBox();amt.setMaximum(999999999);amt.setPrefix('$ ');pay=QComboBox();pay.addItems(['EFECTIVO','DÉBITO','CRÉDITO','QR / TRANSFERENCIA']);notes=QLineEdit()
        for a,w in [('Categoría',cat),('Descripción *',desc),('Monto *',amt),('Pago',pay),('Notas',notes)]:f.addRow(a,w)
        s=QPushButton('Guardar gasto');s.setStyleSheet('background:#26b86a;color:white;');f.addRow(s)
        def save():
            if not desc.text().strip() or amt.value()<=0:return
            now=datetime.now().isoformat(timespec='seconds')
            with db() as c:
                cur=c.execute('INSERT INTO expenses(created_at,category,description,amount,payment_method,notes) VALUES (?,?,?,?,?,?)',(now,cat.currentText(),desc.text().strip(),amt.value(),pay.currentText(),notes.text().strip()));eid=cur.lastrowid
                sess=c.execute("SELECT id FROM cash_sessions WHERE status='ABIERTA' ORDER BY id DESC LIMIT 1").fetchone();sid=sess['id'] if sess else None
                c.execute('''INSERT INTO cash_movements(created_at,session_id,movement_type,concept,amount,payment_method,reference_type,reference_id,user_id) VALUES (?,?,?,?,?,?,?,?,1)''',(now,sid,'GASTO',desc.text().strip(),-amt.value(),pay.currentText(),'EXPENSE',eid))
            d.accept();self.refresh()
        s.clicked.connect(save);d.exec()
