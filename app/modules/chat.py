from datetime import datetime
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QLineEdit, QMessageBox
from app.database import db


class ChatPage(QWidget):
    def __init__(self, back_callback, current_user):
        super().__init__()
        self.back_callback = back_callback
        self.current_user = current_user or {'name':'Sistema'}
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(12)
        top = QHBoxLayout()
        back = QPushButton('← VOLVER A VENTAS')
        back.setStyleSheet('background:#eee5ea;color:#4a3740;')
        back.clicked.connect(self.back_callback)
        title = QLabel('💬 Chat interno · Caja ↔ Panel Web')
        title.setStyleSheet('font-size:27px;font-weight:950;color:#4d2034;')
        top.addWidget(back); top.addSpacing(12); top.addWidget(title); top.addStretch()
        root.addLayout(top)
        note = QLabel('Los mensajes quedan guardados en la misma base. El panel web los ve casi en tiempo real.')
        note.setStyleSheet('color:#75636d;')
        root.addWidget(note)
        self.list = QListWidget()
        self.list.setStyleSheet('QListWidget{background:white;border:1px solid #eadfe4;border-radius:16px;padding:10px;font-size:15px;} QListWidget::item{padding:9px;border-bottom:1px solid #f2e8ed;}')
        root.addWidget(self.list, 1)
        sendrow = QHBoxLayout()
        self.message = QLineEdit()
        self.message.setPlaceholderText('Escribí un mensaje para administración web…')
        self.message.setStyleSheet('font-size:16px;padding:13px;border:2px solid #e1ccd6;border-radius:12px;')
        self.message.returnPressed.connect(self.send)
        send = QPushButton('ENVIAR')
        send.setMinimumSize(130, 52)
        send.setStyleSheet('background:#3b91e8;color:white;font-weight:950;font-size:16px;')
        send.clicked.connect(self.send)
        sendrow.addWidget(self.message, 1); sendrow.addWidget(send)
        root.addLayout(sendrow)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(3000)
        self.refresh()

    def refresh(self):
        current_id = self.list.property('lastMessageId') or 0
        with db() as conn:
            rows = conn.execute('SELECT * FROM internal_messages ORDER BY id DESC LIMIT 120').fetchall()[::-1]
        latest = rows[-1]['id'] if rows else 0
        if latest == current_id and self.list.count():
            return
        self.list.clear()
        for r in rows:
            origin = '🌐 WEB' if r['sender_type'] == 'WEB' else '🖥 CAJA'
            text = f"{origin} · {r['sender']} · {str(r['created_at']).replace('T',' ')}\n{r['message']}"
            item = QListWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft)
            self.list.addItem(item)
        self.list.setProperty('lastMessageId', latest)
        if rows:
            self.list.scrollToBottom()

    def send(self):
        text = self.message.text().strip()
        if not text:
            return
        with db() as conn:
            conn.execute('INSERT INTO internal_messages(created_at,sender,sender_type,message) VALUES (?,?,?,?)',
                         (datetime.now().isoformat(timespec='seconds'), self.current_user.get('name','Operador'), 'SISTEMA', text))
        self.message.clear()
        self.refresh()
