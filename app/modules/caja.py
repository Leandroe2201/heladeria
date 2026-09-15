from datetime import datetime
from PyQt6.QtWidgets import *
from PyQt6.QtCore import Qt
from app.database import db


class CajaPage(QWidget):
    def __init__(self, back_callback, current_user=None, limited=False):
        super().__init__()
        self.back_callback = back_callback
        self.current_user = current_user or {'id':1,'name':'Administrador','role':'ADMIN'}
        self.limited = limited
        self.build_ui(); self.refresh()

    def build_ui(self):
        root=QVBoxLayout(self); root.setContentsMargins(28,24,28,28); root.setSpacing(12)
        h=QHBoxLayout(); b=QPushButton('← Volver a Ventas' if self.limited else '← Volver a Opciones'); b.setStyleSheet('background:#eee5ea;color:#4a3740;'); b.clicked.connect(self.back_callback)
        t=QLabel('💰 CAJA'); t.setStyleSheet('font-size:28px;font-weight:950;color:#4d2034;')
        who=QLabel(f"Operador: {self.current_user.get('name','')}"); who.setStyleSheet('font-weight:800;color:#725f68;')
        h.addWidget(b); h.addSpacing(16); h.addWidget(t); h.addStretch(); h.addWidget(who); root.addLayout(h)
        self.status_label=QLabel(); self.status_label.setMinimumHeight(60); self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter); root.addWidget(self.status_label)
        self.summary=QHBoxLayout(); self.cards=[]
        for _ in range(4):
            frame=QFrame(); frame.setStyleSheet('background:white;border:1px solid #eadfe4;border-radius:14px;'); l=QVBoxLayout(frame); a=QLabel(''); a.setStyleSheet('color:#725f68;'); v=QLabel('$ 0'); v.setStyleSheet('font-size:25px;font-weight:900;'); l.addWidget(a); l.addWidget(v); self.summary.addWidget(frame); self.cards.append((a,v))
        root.addLayout(self.summary)
        actions=QHBoxLayout()
        op=QPushButton('🔓 ABRIR CAJA'); op.setMinimumHeight(58); op.setStyleSheet('background:#36c978;color:white;font-size:17px;font-weight:950;'); op.clicked.connect(self.open_session)
        close=QPushButton('🔒 CERRAR CAJA'); close.setMinimumHeight(58); close.setStyleSheet('background:#8d6bd1;color:white;font-size:17px;font-weight:950;'); close.clicked.connect(self.close_session)
        actions.addWidget(op); actions.addWidget(close)
        if not self.limited:
            inc=QPushButton('＋ INGRESO'); inc.setStyleSheet('background:#3f9df7;color:white;'); inc.clicked.connect(lambda:self.manual_movement('INGRESO'))
            eg=QPushButton('－ EGRESO'); eg.setStyleSheet('background:#ff7d45;color:white;'); eg.clicked.connect(lambda:self.manual_movement('EGRESO'))
            actions.addWidget(inc); actions.addWidget(eg)
        ref=QPushButton('⟳ ACTUALIZAR'); ref.setStyleSheet('background:#ece3e8;color:#4a3740;'); ref.clicked.connect(self.refresh); actions.addWidget(ref); actions.addStretch(); root.addLayout(actions)
        tabs=QTabWidget(); root.addWidget(tabs)
        mov=QWidget(); ml=QVBoxLayout(mov); self.mov_table=QTableWidget(0,9); self.mov_table.setHorizontalHeaderLabels(['ID','Fecha/Hora','Tipo','Concepto','Monto','Medio','Sesión','Ref.','Usuario']); self.mov_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.mov_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); ml.addWidget(self.mov_table); tabs.addTab(mov,'Movimientos')
        sales=QWidget(); sl=QVBoxLayout(sales); self.sales_table=QTableWidget(0,7); self.sales_table.setHorizontalHeaderLabels(['Venta','Fecha/Hora','Total','Pago','Descuento','Sesión','Usuario']); self.sales_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); sl.addWidget(self.sales_table); tabs.addTab(sales,'Ventas de hoy')
        sessions=QWidget(); ss=QVBoxLayout(sessions); self.session_table=QTableWidget(0,7); self.session_table.setHorizontalHeaderLabels(['ID','Apertura','Cierre','Inicial','Final','Estado','Operador']); self.session_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); ss.addWidget(self.session_table); tabs.addTab(sessions,'Turnos / Sesiones')

    def refresh(self):
        with db() as conn:
            total=conn.execute("SELECT COALESCE(SUM(total),0) s,COUNT(*) c FROM sales WHERE date(created_at)=date('now','localtime') AND status='CONFIRMADA'").fetchone()
            cash=conn.execute("SELECT COALESCE(SUM(total),0) s FROM sales WHERE date(created_at)=date('now','localtime') AND status='CONFIRMADA' AND payment_method='EFECTIVO'").fetchone()
            other=conn.execute("SELECT COALESCE(SUM(total),0) s FROM sales WHERE date(created_at)=date('now','localtime') AND status='CONFIRMADA' AND payment_method<>'EFECTIVO'").fetchone()
            sess=conn.execute("SELECT cs.*,COALESCE(u.name,'') user_name FROM cash_sessions cs LEFT JOIN users u ON u.id=cs.user_id WHERE cs.status='ABIERTA' ORDER BY cs.id DESC LIMIT 1").fetchone()
            moves=conn.execute("SELECT cm.*,COALESCE(u.name,'') user_name FROM cash_movements cm LEFT JOIN users u ON u.id=cm.user_id WHERE date(cm.created_at)=date('now','localtime') ORDER BY cm.id DESC").fetchall()
            sales=conn.execute("SELECT s.*,COALESCE(u.name,'') user_name FROM sales s LEFT JOIN users u ON u.id=s.user_id WHERE date(s.created_at)=date('now','localtime') ORDER BY s.id DESC").fetchall()
            sessions=conn.execute("SELECT cs.*,COALESCE(u.name,'') user_name FROM cash_sessions cs LEFT JOIN users u ON u.id=cs.user_id ORDER BY cs.id DESC LIMIT 100").fetchall()
        if sess:
            self.status_label.setText(f"🟢 CAJA ABIERTA · Sesión #{sess['id']} · {sess['user_name']} · desde {str(sess['opened_at']).replace('T',' ')}")
            self.status_label.setStyleSheet('background:#daf7e6;color:#16693e;border-radius:14px;font-size:17px;font-weight:950;')
        else:
            self.status_label.setText('🔴 CAJA CERRADA · Debe abrirse antes de comenzar el turno')
            self.status_label.setStyleSheet('background:#ffe0e4;color:#942640;border-radius:14px;font-size:17px;font-weight:950;')
        labels=[('Ventas de hoy',f"$ {total['s']:,.0f}"),('Tickets',str(total['c'])),('Efectivo',f"$ {cash['s']:,.0f}"),('Otros medios',f"$ {other['s']:,.0f}")]
        for (a,v),(la,va) in zip(self.cards,labels): a.setText(la); v.setText(va)
        self.mov_table.setRowCount(len(moves))
        for i,r in enumerate(moves):
            vals=[r['id'],r['created_at'],r['movement_type'],r['concept'],f"$ {r['amount']:,.0f}",r['payment_method'],r['session_id'] or '',f"{r['reference_type'] or ''} {r['reference_id'] or ''}",r['user_name']]
            for c,v in enumerate(vals): self.mov_table.setItem(i,c,QTableWidgetItem(str(v)))
        self.mov_table.resizeColumnsToContents(); self.mov_table.horizontalHeader().setStretchLastSection(True)
        self.sales_table.setRowCount(len(sales))
        for i,r in enumerate(sales):
            vals=[r['id'],r['created_at'],f"$ {r['total']:,.0f}",r['payment_method'],f"$ {r['discount']:,.0f}",r['cash_session_id'] or 'Sin sesión',r['user_name']]
            for c,v in enumerate(vals): self.sales_table.setItem(i,c,QTableWidgetItem(str(v)))
        self.sales_table.resizeColumnsToContents(); self.sales_table.horizontalHeader().setStretchLastSection(True)
        self.session_table.setRowCount(len(sessions))
        for i,r in enumerate(sessions):
            vals=[r['id'],r['opened_at'],r['closed_at'] or '',f"$ {r['opening_amount']:,.0f}",'' if r['closing_amount'] is None else f"$ {r['closing_amount']:,.0f}",r['status'],r['user_name']]
            for c,v in enumerate(vals): self.session_table.setItem(i,c,QTableWidgetItem(str(v)))
        self.session_table.resizeColumnsToContents(); self.session_table.horizontalHeader().setStretchLastSection(True)

    def open_session(self):
        with db() as conn:
            existing=conn.execute("SELECT * FROM cash_sessions WHERE status='ABIERTA' ORDER BY id DESC LIMIT 1").fetchone()
        if existing:
            QMessageBox.information(self,'Caja','Ya hay una caja abierta.'); return
        amount,ok=QInputDialog.getDouble(self,'Apertura de caja','Efectivo inicial:',0,0,999999999,2)
        if not ok: return
        with db() as conn:
            conn.execute("INSERT INTO cash_sessions(opened_at,opening_amount,user_id,status) VALUES (?,?,?,'ABIERTA')",(datetime.now().isoformat(timespec='seconds'),amount,int(self.current_user.get('id') or 1)))
            conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",(datetime.now().isoformat(timespec='seconds'),self.current_user.get('name'),'APERTURA_CAJA',f'Fondo inicial ${amount:,.2f}'))
        self.refresh()

    def manual_movement(self,typ):
        if self.limited: return
        with db() as conn: sess=conn.execute("SELECT * FROM cash_sessions WHERE status='ABIERTA' ORDER BY id DESC LIMIT 1").fetchone()
        amount,ok=QInputDialog.getDouble(self,typ,'Monto:',0,0,999999999,2)
        if not ok or amount<=0:return
        concept,ok=QInputDialog.getText(self,typ,'Concepto / motivo:')
        if not ok:return
        signed=amount if typ=='INGRESO' else -amount
        with db() as conn: conn.execute("INSERT INTO cash_movements(created_at,session_id,movement_type,concept,amount,payment_method,user_id) VALUES (?,?,?,?,?,'EFECTIVO',?)",(datetime.now().isoformat(timespec='seconds'),sess['id'] if sess else None,typ,concept.strip() or typ,signed,int(self.current_user.get('id') or 1)))
        self.refresh()

    def close_session(self):
        with db() as conn: sess=conn.execute("SELECT * FROM cash_sessions WHERE status='ABIERTA' ORDER BY id DESC LIMIT 1").fetchone()
        if not sess: QMessageBox.information(self,'Caja','No hay una caja abierta.'); return
        with db() as conn: mov=conn.execute("SELECT COALESCE(SUM(amount),0) s FROM cash_movements WHERE session_id=? AND payment_method='EFECTIVO'",(sess['id'],)).fetchone()['s']
        expected=float(sess['opening_amount'])+float(mov)
        value,ok=QInputDialog.getDouble(self,'Cerrar caja',f'Efectivo esperado: $ {expected:,.2f}\nEfectivo contado:',expected,0,999999999,2)
        if not ok:return
        now=datetime.now().isoformat(timespec='seconds')
        with db() as conn:
            conn.execute("UPDATE cash_sessions SET closed_at=?,closing_amount=?,status='CERRADA' WHERE id=?",(now,value,sess['id']))
            conn.execute("INSERT INTO audit_log(created_at,user_name,action,detail) VALUES (?,?,?,?)",(now,self.current_user.get('name'),'CIERRE_CAJA',f'Sesión #{sess["id"]} esperado ${expected:,.2f} declarado ${value:,.2f}'))
        diff=value-expected
        QMessageBox.information(self,'Caja cerrada',f'Esperado: $ {expected:,.2f}\nDeclarado: $ {value:,.2f}\nDiferencia: $ {diff:,.2f}')
        self.refresh()
