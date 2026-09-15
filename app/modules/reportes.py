from PyQt6.QtWidgets import *
from app.database import db

class ReportesPage(QWidget):
    def __init__(self, back_callback):
        super().__init__(); root=QVBoxLayout(self); root.setContentsMargins(28,24,28,28)
        h=QHBoxLayout(); b=QPushButton("← Volver a Opciones"); b.setStyleSheet("background:#eee5ea;color:#4a3740;"); b.clicked.connect(back_callback); t=QLabel("📈 Reportes"); t.setStyleSheet("font-size:28px;font-weight:800;"); h.addWidget(b); h.addSpacing(20); h.addWidget(t); h.addStretch(); root.addLayout(h)
        with db() as conn:
            today=conn.execute("SELECT COALESCE(SUM(total),0) s, COUNT(*) c FROM sales WHERE date(created_at)=date('now','localtime') AND status='CONFIRMADA'").fetchone()
            month=conn.execute("SELECT COALESCE(SUM(total),0) s FROM sales WHERE strftime('%Y-%m',created_at)=strftime('%Y-%m','now','localtime') AND status='CONFIRMADA'").fetchone()
        cards=QHBoxLayout()
        for label,value in [("Ventas de hoy",f"$ {today['s']:,.0f}"),("Tickets de hoy",str(today['c'])),("Ventas del mes",f"$ {month['s']:,.0f}")]:
            frame=QFrame(); frame.setStyleSheet("background:white;border:1px solid #eadfe4;border-radius:16px;"); l=QVBoxLayout(frame); a=QLabel(label); a.setStyleSheet("font-size:15px;color:#77636c;"); v=QLabel(value); v.setStyleSheet("font-size:30px;font-weight:800;"); l.addWidget(a); l.addWidget(v); cards.addWidget(frame)
        root.addLayout(cards); root.addStretch()
